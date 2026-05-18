package inventory

import (
	"bufio"
	"context"
	"os"
	"os/exec"
	"regexp"
	"strings"
	"sync"
	"time"
)

// Entry describes a single runtime or service detected on the host.
type Entry struct {
	Name        string     `json:"name"`
	Version     string     `json:"version"`
	Status      string     `json:"status"`       // "active" | "inactive" | "failed" | "unknown" | "n/a"
	UptimeSince *time.Time `json:"uptime_since"` // nil for non-daemon runtimes
}

type descriptor struct {
	name        string
	versionArgs []string
	versionRe   *regexp.Regexp
	versionFile string // read version from file when command is not in PATH
	versionFileRe *regexp.Regexp
	service     string // systemd unit name; empty = no daemon
}

var runtimes = []descriptor{
	{
		name: "Go", versionArgs: []string{"go", "version"},
		versionRe:     regexp.MustCompile(`go(\d+\.\d+(?:\.\d+)?)`),
		versionFile:   "/usr/local/go/VERSION",
		versionFileRe: regexp.MustCompile(`go(\d+\.\d+(?:\.\d+)?)`),
	},
	{name: "Python", versionArgs: []string{"python3", "--version"}, versionRe: regexp.MustCompile(`Python (\S+)`)},
	{name: "Node.js", versionArgs: []string{"node", "--version"}, versionRe: regexp.MustCompile(`v(\S+)`)},
	{name: "PHP", versionArgs: []string{"php", "--version"}, versionRe: regexp.MustCompile(`PHP (\d+\.\d+\.\d+)`)},
	{name: "Composer", versionArgs: []string{"composer", "--version", "--no-ansi"}, versionRe: regexp.MustCompile(`Composer version (\S+)`)},
	{name: "PostgreSQL", versionArgs: []string{"psql", "--version"}, versionRe: regexp.MustCompile(`(\d+\.\d+(?:\.\d+)?)`), service: "postgresql"},
	{name: "ClickHouse", versionArgs: []string{"clickhouse-client", "--version"}, versionRe: regexp.MustCompile(`(\d+\.\d+\.\d+\.\d+)`), service: "clickhouse-server"},
	{name: "Redis", versionArgs: []string{"redis-cli", "--version"}, versionRe: regexp.MustCompile(`redis-cli (\S+)`), service: "redis"},
	{name: "Nginx", versionArgs: []string{"nginx", "-v"}, versionRe: regexp.MustCompile(`nginx/(\S+)`), service: "nginx"},
}

// Collect detects installed runtimes and their service statuses concurrently.
// Safe to call once at agent startup; results should be cached and refreshed
// via RefreshStatus on subsequent heartbeats.
func Collect(ctx context.Context) []Entry {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	entries := make([]Entry, len(runtimes)+1) // +1 for OS
	entries[0] = osEntry()

	var wg sync.WaitGroup
	for i, rt := range runtimes {
		wg.Add(1)
		go func(idx int, d descriptor) {
			defer wg.Done()
			entries[idx+1] = detect(ctx, d)
		}(i, rt)
	}
	wg.Wait()

	return entries
}

// RefreshStatus re-checks systemd service status for daemon entries,
// preserving the version strings from the original Collect call.
func RefreshStatus(ctx context.Context, entries []Entry) []Entry {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()

	// Build a service→index map to avoid O(n²) lookup.
	serviceIdx := make(map[string]int, len(entries))
	for i, e := range entries {
		if e.Name == "OS" {
			continue
		}
		for _, d := range runtimes {
			if d.name == e.Name && d.service != "" {
				serviceIdx[d.service] = i
			}
		}
	}

	refreshed := make([]Entry, len(entries))
	copy(refreshed, entries)

	var wg sync.WaitGroup
	for svc, idx := range serviceIdx {
		wg.Add(1)
		go func(service string, i int) {
			defer wg.Done()
			status, since := serviceStatus(ctx, service)
			refreshed[i].Status = status
			refreshed[i].UptimeSince = since
		}(svc, idx)
	}
	wg.Wait()

	return refreshed
}

func osEntry() Entry {
	version := osVersion()
	return Entry{Name: "OS", Version: version, Status: "n/a"}
}

func osVersion() string {
	f, err := os.Open("/etc/os-release")
	if err != nil {
		return "unknown"
	}
	defer f.Close()

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "PRETTY_NAME=") {
			val := strings.TrimPrefix(line, "PRETTY_NAME=")
			return strings.Trim(val, `"`)
		}
	}
	return "unknown"
}

func detect(ctx context.Context, d descriptor) Entry {
	e := Entry{Name: d.name, Version: "not found", Status: "n/a"}

	out, _ := exec.CommandContext(ctx, d.versionArgs[0], d.versionArgs[1:]...).CombinedOutput()
	if m := d.versionRe.FindSubmatch(out); len(m) > 1 {
		e.Version = string(m[1])
	} else if d.versionFile != "" {
		// Command not in PATH — try reading version from a well-known file.
		if content, err := os.ReadFile(d.versionFile); err == nil {
			if m := d.versionFileRe.FindSubmatch(content); len(m) > 1 {
				e.Version = string(m[1])
			}
		}
	}

	if e.Version == "not found" {
		return e
	}

	if d.service != "" {
		e.Status, e.UptimeSince = serviceStatus(ctx, d.service)
	}
	return e
}

func serviceStatus(ctx context.Context, service string) (string, *time.Time) {
	out, err := exec.CommandContext(ctx, "systemctl", "is-active", service).Output()
	status := strings.TrimSpace(string(out))
	if err != nil || status == "" {
		status = "inactive"
	}

	if status != "active" {
		return status, nil
	}

	tsOut, err := exec.CommandContext(ctx, "systemctl", "show", service,
		"--property=ActiveEnterTimestamp", "--value").Output()
	if err != nil {
		return status, nil
	}

	raw := strings.TrimSpace(string(tsOut))
	if raw == "" || raw == "n/a" {
		return status, nil
	}

	// systemd format: "Mon 2026-05-18 14:30:00 -0400"
	for _, layout := range []string{
		"Mon 2006-01-02 15:04:05 -0700",
		"Mon 2006-01-02 15:04:05 MST",
	} {
		if t, err := time.Parse(layout, raw); err == nil {
			utc := t.UTC()
			return status, &utc
		}
	}
	return status, nil
}
