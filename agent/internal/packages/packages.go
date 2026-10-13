// Package packages reports the OS packages installed on the host so the API
// can match them against distribution security advisories.
package packages

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"sort"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	// DefaultKey is the Redis hash holding one snapshot per server_id.
	DefaultKey = "maestro:packages"
	// DefaultInterval is how often the installed package list is re-read.
	DefaultInterval = 6 * time.Hour

	collectTimeout = 30 * time.Second
	osReleasePath  = "/etc/os-release"
)

// Package is an installed source package. Advisories are published per source
// package, so binary packages built from the same source collapse into one entry.
type Package struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// Snapshot is the payload stored in Redis for a server.
type Snapshot struct {
	ServerID    string    `json:"server_id"`
	Ecosystem   string    `json:"ecosystem"` // OSV ecosystem, e.g. "Debian:12"
	CollectedAt time.Time `json:"collected_at"`
	Packages    []Package `json:"packages"`
}

// Config holds all parameters needed by the reporter.
type Config struct {
	ServerID      string
	RedisAddr     string
	RedisPassword string
	Key           string
	Interval      time.Duration
	Debug         bool
}

// Start launches the package reporter as a goroutine. It publishes a snapshot
// right away and then on every interval. Hosts that are not Debian are skipped.
func Start(ctx context.Context, cfg Config) {
	if cfg.Key == "" {
		cfg.Key = DefaultKey
	}
	if cfg.Interval <= 0 {
		cfg.Interval = DefaultInterval
	}

	ecosystem := detectEcosystem()
	if ecosystem == "" {
		log.Printf("info [packages]: host is not a supported distribution — package reporting disabled")
		return
	}

	go func() {
		var client *redis.Client
		if !cfg.Debug {
			client = redis.NewClient(&redis.Options{Addr: cfg.RedisAddr, Password: cfg.RedisPassword})
			defer client.Close()
		}

		ticker := time.NewTicker(cfg.Interval)
		defer ticker.Stop()

		report(ctx, cfg, client, ecosystem)
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				report(ctx, cfg, client, ecosystem)
			}
		}
	}()
}

func report(ctx context.Context, cfg Config, client *redis.Client, ecosystem string) {
	pkgs, err := collect(ctx)
	if err != nil {
		log.Printf("warn [packages]: collection failed: %v — skipping", err)
		return
	}

	payload, err := json.Marshal(Snapshot{
		ServerID:    cfg.ServerID,
		Ecosystem:   ecosystem,
		CollectedAt: time.Now().UTC(),
		Packages:    pkgs,
	})
	if err != nil {
		log.Printf("warn [packages]: marshal failed: %v", err)
		return
	}

	if cfg.Debug {
		log.Printf("debug [packages]: %s — %d source packages", ecosystem, len(pkgs))
		return
	}

	if err := client.HSet(ctx, cfg.Key, cfg.ServerID, payload).Err(); err != nil {
		log.Printf("warn [packages]: HSET %q failed: %v — skipping", cfg.Key, err)
		return
	}
	log.Printf("info [packages]: reported %d source packages (%s)", len(pkgs), ecosystem)
}

func collect(ctx context.Context) ([]Package, error) {
	ctx, cancel := context.WithTimeout(ctx, collectTimeout)
	defer cancel()

	out, err := exec.CommandContext(ctx, "dpkg-query", "-W",
		"-f=${source:Package}\t${source:Version}\t${db:Status-Abbrev}\n").Output()
	if err != nil {
		return nil, fmt.Errorf("dpkg-query: %w", err)
	}
	return parseDpkg(out), nil
}

// parseDpkg turns dpkg-query output (source, version, status per line) into a
// sorted, de-duplicated list of fully installed source packages.
func parseDpkg(out []byte) []Package {
	seen := make(map[Package]struct{})
	scanner := bufio.NewScanner(bytes.NewReader(out))
	for scanner.Scan() {
		fields := strings.Split(scanner.Text(), "\t")
		if len(fields) != 3 || !strings.HasPrefix(fields[2], "ii") {
			continue
		}
		if fields[0] == "" || fields[1] == "" {
			continue
		}
		seen[Package{Name: fields[0], Version: fields[1]}] = struct{}{}
	}

	pkgs := make([]Package, 0, len(seen))
	for p := range seen {
		pkgs = append(pkgs, p)
	}
	sort.Slice(pkgs, func(i, j int) bool {
		if pkgs[i].Name != pkgs[j].Name {
			return pkgs[i].Name < pkgs[j].Name
		}
		return pkgs[i].Version < pkgs[j].Version
	})
	return pkgs
}

func detectEcosystem() string {
	f, err := os.Open(osReleasePath)
	if err != nil {
		return ""
	}
	defer f.Close()
	return parseEcosystem(f)
}

// parseEcosystem maps /etc/os-release to an OSV ecosystem name.
// Only Debian is supported; anything else returns "".
func parseEcosystem(r io.Reader) string {
	values := make(map[string]string)
	scanner := bufio.NewScanner(r)
	for scanner.Scan() {
		key, val, found := strings.Cut(scanner.Text(), "=")
		if found {
			values[key] = strings.Trim(val, `"`)
		}
	}

	if values["ID"] != "debian" || values["VERSION_ID"] == "" {
		return ""
	}
	return "Debian:" + values["VERSION_ID"]
}
