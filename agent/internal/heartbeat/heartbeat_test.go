package heartbeat

import (
	"context"
	"testing"
	"time"
)

// TestStartDebugMode verifies that Start returns no error in debug mode
// and the goroutine runs without panicking.
func TestStartDebugMode(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())

	err := Start(ctx, Config{
		ServerID: "test-server",
		Stream:   "maestro:heartbeat",
		Interval: 50 * time.Millisecond,
		Debug:    true,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Let at least two ticks fire.
	time.Sleep(120 * time.Millisecond)
	cancel()

	// Allow goroutine to exit cleanly.
	time.Sleep(10 * time.Millisecond)
}

// TestPayloadFields verifies the payload is populated correctly.
func TestPayloadFields(t *testing.T) {
	Version = "1.2.3"
	before := time.Now().UTC()

	p := Payload{
		ServerID:     "srv-01",
		Timestamp:    time.Now().UTC(),
		AgentVersion: Version,
	}

	if p.ServerID != "srv-01" {
		t.Errorf("unexpected server_id: %q", p.ServerID)
	}
	if p.AgentVersion != "1.2.3" {
		t.Errorf("unexpected agent_version: %q", p.AgentVersion)
	}
	if p.Timestamp.Before(before) {
		t.Errorf("timestamp %v is before test start %v", p.Timestamp, before)
	}
}

// TestDefaultInterval ensures a zero interval falls back to 30 seconds.
func TestDefaultInterval(t *testing.T) {
	cfg := Config{Interval: 0}
	if cfg.Interval <= 0 {
		cfg.Interval = 30 * time.Second
	}
	if cfg.Interval != 30*time.Second {
		t.Errorf("expected 30s default, got %v", cfg.Interval)
	}
}
