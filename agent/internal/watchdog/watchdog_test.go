package watchdog

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type fakeChecker struct{ results []Result }

func (f *fakeChecker) Check(context.Context, Target) Result {
	r := f.results[0]
	if len(f.results) > 1 {
		f.results = f.results[1:]
	}
	return r
}

type fakeNotifier struct {
	sent []string
	fail bool
}

func (f *fakeNotifier) Send(_ context.Context, text string) error {
	if f.fail {
		return errors.New("offline")
	}
	f.sent = append(f.sent, text)
	return nil
}

type clock struct{ now time.Time }

func (c *clock) Now() time.Time { return c.now }

func newDog(results []Result, notifier *fakeNotifier, c *clock, remind time.Duration) *Watchdog {
	cfg := Config{
		Targets:             []Target{{Name: "Maestro", URL: "http://x"}},
		FailuresBeforeAlert: 3,
		RemindEvery:         remind,
		Texts:               TextsFor("pt-BR"),
	}
	return New(cfg, &fakeChecker{results: results}, notifier, c.Now, func(string, ...any) {})
}

func poll(dog *Watchdog, times int) {
	for range times {
		dog.Poll(context.Background())
	}
}

var down = Result{Detail: "HTTP 503"}
var up = Result{OK: true}

func TestAlertsOnlyAfterConsecutiveFailures(t *testing.T) {
	notifier := &fakeNotifier{}
	dog := newDog([]Result{down, down, up, down, down, down}, notifier, &clock{}, 0)

	poll(dog, 5)
	if len(notifier.sent) != 0 {
		t.Fatalf("alerted before three failures in a row: %v", notifier.sent)
	}
	poll(dog, 1)
	if want := "🔴 Vigia: Maestro não responde (HTTP 503)"; len(notifier.sent) != 1 || notifier.sent[0] != want {
		t.Fatalf("sent %v, want [%q]", notifier.sent, want)
	}
}

func TestAlertsOnceAndReportsRecovery(t *testing.T) {
	notifier := &fakeNotifier{}
	dog := newDog([]Result{down, down, down, down, down, up, up}, notifier, &clock{}, 0)

	poll(dog, 7)

	want := []string{"🔴 Vigia: Maestro não responde (HTTP 503)", "🟢 Vigia: Maestro voltou a responder"}
	if strings.Join(notifier.sent, "|") != strings.Join(want, "|") {
		t.Fatalf("sent %v, want %v", notifier.sent, want)
	}
}

func TestRemindsWhileDown(t *testing.T) {
	notifier := &fakeNotifier{}
	c := &clock{now: time.Date(2026, 11, 3, 12, 0, 0, 0, time.UTC)}
	dog := newDog([]Result{down}, notifier, c, time.Hour)

	poll(dog, 3)
	c.now = c.now.Add(30 * time.Minute)
	poll(dog, 1)
	c.now = c.now.Add(31 * time.Minute)
	poll(dog, 1)

	if len(notifier.sent) != 2 || !strings.Contains(notifier.sent[1], "continua sem responder") {
		t.Fatalf("sent %v, want the alert and one reminder", notifier.sent)
	}
}

func TestUndeliveredAlertIsRetried(t *testing.T) {
	notifier := &fakeNotifier{fail: true}
	dog := newDog([]Result{down}, notifier, &clock{}, 0)

	poll(dog, 3)
	notifier.fail = false
	poll(dog, 1)

	if len(notifier.sent) != 1 {
		t.Fatalf("sent %v, want the alert once Telegram is back", notifier.sent)
	}
}

func TestHTTPCheckerReportsMaestroProblems(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status":       "unhealthy",
			"dependencies": map[string]string{"redis": "ok", "clickhouse": "down"},
			"tasks": []map[string]any{
				{"name": "alert-evaluator", "state": "stale", "watched": true},
				{"name": "metrics-consumer", "state": "ok", "watched": true},
				{"name": "vuln-scanner", "state": "down", "watched": false},
			},
		})
	}))
	defer server.Close()

	result := HTTPChecker{Client: server.Client()}.Check(context.Background(), Target{Name: "Maestro", URL: server.URL})

	if want := "HTTP 503 (clickhouse: down, alert-evaluator: stale)"; result.OK || result.Detail != want {
		t.Fatalf("got %+v, want detail %q", result, want)
	}
}

func TestHTTPCheckerAcceptsAnyTwoHundred(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	if result := (HTTPChecker{Client: server.Client()}).Check(context.Background(), Target{URL: server.URL}); !result.OK {
		t.Fatalf("got %+v, want OK", result)
	}
}

func TestHTTPCheckerReportsRefusedConnection(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	url := server.URL
	server.Close()

	result := HTTPChecker{Client: &http.Client{Timeout: time.Second}}.Check(context.Background(), Target{URL: url})

	if result.OK || result.Detail != "connection refused" {
		t.Fatalf("got %+v, want connection refused", result)
	}
}

func TestTelegramSendsAndHidesTheToken(t *testing.T) {
	var gotPath string
	var gotBody map[string]any
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &gotBody)
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"ok":false,"description":"Bad Request: chat not found"}`))
	}))
	defer server.Close()

	tg := Telegram{Client: server.Client(), Token: "123:secret", ChatID: "-100", BaseURL: server.URL}
	err := tg.Send(context.Background(), "olá")

	if gotPath != "/bot123:secret/sendMessage" || gotBody["chat_id"] != "-100" || gotBody["text"] != "olá" {
		t.Fatalf("unexpected request %s %v", gotPath, gotBody)
	}
	if err == nil || err.Error() != "telegram: HTTP 400: Bad Request: chat not found" {
		t.Fatalf("got %v", err)
	}

	unreachable := Telegram{Client: &http.Client{Timeout: time.Second}, Token: "123:secret", ChatID: "-100", BaseURL: "http://127.0.0.1:1"}
	if err := unreachable.Send(context.Background(), "x"); err == nil || strings.Contains(err.Error(), "secret") {
		t.Fatalf("token leaked or no error: %v", err)
	}
}

func TestLoadSettings(t *testing.T) {
	env := map[string]string{
		"WATCHDOG_TARGETS":   "Maestro=https://m.example.com/api/health, Aegis=https://a.example.com/health?x=1",
		"TELEGRAM_BOT_TOKEN": "1:t",
		"TELEGRAM_CHAT_ID":   "-100",
		"WATCHDOG_INTERVAL":  "30s",
	}
	s, err := LoadSettings(func(k string) string { return env[k] })
	if err != nil {
		t.Fatal(err)
	}
	if len(s.Targets) != 2 || s.Targets[1].URL != "https://a.example.com/health?x=1" {
		t.Fatalf("targets %+v", s.Targets)
	}
	if s.Interval != 30*time.Second || s.FailuresBeforeAlert != 3 || s.RemindEvery != time.Hour || !s.Announce {
		t.Fatalf("defaults %+v", s)
	}

	for _, bad := range []string{"", "Maestro", "Maestro=ftp://x", "A=http://x,A=http://y"} {
		env["WATCHDOG_TARGETS"] = bad
		if _, err := LoadSettings(func(k string) string { return env[k] }); err == nil {
			t.Errorf("WATCHDOG_TARGETS=%q accepted", bad)
		}
	}
}
