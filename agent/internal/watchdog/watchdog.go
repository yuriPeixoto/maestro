// Package watchdog polls HTTP health endpoints from another host and reports
// on Telegram when one stops answering and when it comes back.
//
// It exists so the monitoring stack has a witness that does not run on the
// server it watches: if that server goes down, the Maestro API cannot send
// its own alert.
package watchdog

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"sort"
	"strings"
	"syscall"
	"time"
)

const maxBodyBytes = 64 << 10

// Target is one endpoint to poll. It is healthy when it answers 2xx in time.
type Target struct {
	Name string
	URL  string
}

// Result of one poll.
type Result struct {
	OK     bool
	Detail string
}

// Notifier delivers a text message.
type Notifier interface {
	Send(ctx context.Context, text string) error
}

// Checker polls a target.
type Checker interface {
	Check(ctx context.Context, target Target) Result
}

// HTTPChecker polls with a plain GET.
type HTTPChecker struct {
	Client *http.Client
}

// maestroHealth is the part of a Maestro /health body worth repeating in an alert.
type maestroHealth struct {
	Dependencies map[string]string `json:"dependencies"`
	Tasks        []struct {
		Name    string `json:"name"`
		State   string `json:"state"`
		Watched bool   `json:"watched"`
	} `json:"tasks"`
}

func (c HTTPChecker) Check(ctx context.Context, target Target) Result {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, target.URL, nil)
	if err != nil {
		return Result{Detail: "invalid URL"}
	}
	resp, err := c.Client.Do(req)
	if err != nil {
		return Result{Detail: describeTransportError(ctx, err)}
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return Result{OK: true}
	}
	detail := fmt.Sprintf("HTTP %d", resp.StatusCode)
	if problems := healthProblems(body); problems != "" {
		detail += " (" + problems + ")"
	}
	return Result{Detail: detail}
}

// describeTransportError names the failure without the error text, which repeats the URL.
func describeTransportError(ctx context.Context, err error) string {
	var netErr net.Error
	var dnsErr *net.DNSError
	var certErr *tls.CertificateVerificationError
	switch {
	case ctx.Err() != nil, errors.As(err, &netErr) && netErr.Timeout():
		return "timeout"
	case errors.As(err, &dnsErr):
		return "unknown host"
	case errors.As(err, &certErr):
		return "TLS certificate error"
	case isConnectionRefused(err):
		return "connection refused"
	}
	return "no answer"
}

// wsaConnRefused is WSAECONNREFUSED; Windows does not map it to syscall.ECONNREFUSED.
const wsaConnRefused syscall.Errno = 10061

func isConnectionRefused(err error) bool {
	var errno syscall.Errno
	return errors.As(err, &errno) && (errno == syscall.ECONNREFUSED || errno == wsaConnRefused)
}

// healthProblems lists the failing parts of a Maestro /health body, or "".
func healthProblems(body []byte) string {
	var health maestroHealth
	if json.Unmarshal(body, &health) != nil {
		return ""
	}
	var problems []string
	for name, state := range health.Dependencies {
		if state != "ok" {
			problems = append(problems, name+": "+state)
		}
	}
	sort.Strings(problems)
	for _, task := range health.Tasks {
		if task.Watched && task.State != "ok" && task.State != "starting" {
			problems = append(problems, task.Name+": "+task.State)
		}
	}
	return strings.Join(problems, ", ")
}

// Config of a Watchdog.
type Config struct {
	Targets []Target
	// Consecutive failed polls before the target is reported down.
	FailuresBeforeAlert int
	// While a target stays down, repeat the alert this often; 0 never repeats.
	RemindEvery time.Duration
	Texts       Texts
}

type targetState struct {
	failures   int
	down       bool // an alert was delivered and no recovery yet
	lastDetail string
	lastAlert  time.Time
}

// Watchdog keeps the state of every target between polls.
type Watchdog struct {
	cfg      Config
	checker  Checker
	notifier Notifier
	now      func() time.Time
	logf     func(format string, args ...any)
	states   map[string]*targetState
}

func New(cfg Config, checker Checker, notifier Notifier, now func() time.Time, logf func(string, ...any)) *Watchdog {
	states := make(map[string]*targetState, len(cfg.Targets))
	for _, target := range cfg.Targets {
		states[target.Name] = &targetState{}
	}
	return &Watchdog{cfg: cfg, checker: checker, notifier: notifier, now: now, logf: logf, states: states}
}

// Poll checks every target once and sends whatever changed.
func (w *Watchdog) Poll(ctx context.Context) {
	for _, target := range w.cfg.Targets {
		w.poll(ctx, target)
	}
}

func (w *Watchdog) poll(ctx context.Context, target Target) {
	state := w.states[target.Name]
	result := w.checker.Check(ctx, target)

	if result.OK {
		if state.down && w.send(ctx, w.cfg.Texts.Recovered(target.Name)) {
			state.down = false
		}
		if !state.down {
			state.failures = 0
		}
		return
	}

	state.failures++
	state.lastDetail = result.Detail
	w.logf("watchdog: %s failed (%d/%d): %s", target.Name, state.failures, w.cfg.FailuresBeforeAlert, result.Detail)
	if state.failures < w.cfg.FailuresBeforeAlert {
		return
	}
	if !state.down {
		if w.send(ctx, w.cfg.Texts.Down(target.Name, result.Detail)) {
			state.down = true
			state.lastAlert = w.now()
		}
		return
	}
	if w.cfg.RemindEvery > 0 && w.now().Sub(state.lastAlert) >= w.cfg.RemindEvery {
		since := w.now().Sub(state.lastAlert)
		if w.send(ctx, w.cfg.Texts.StillDown(target.Name, result.Detail)) {
			state.lastAlert = w.now()
			w.logf("watchdog: %s still down, reminded after %s", target.Name, since.Round(time.Minute))
		}
	}
}

// send reports whether the message was delivered; a failed one is retried on the next poll.
func (w *Watchdog) send(ctx context.Context, text string) bool {
	if err := w.notifier.Send(ctx, text); err != nil {
		w.logf("watchdog: could not notify: %v", err)
		return false
	}
	return true
}
