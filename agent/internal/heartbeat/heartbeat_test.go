package heartbeat

import (
	"context"
	"sync"
	"testing"
	"time"
)

type recordingSink struct {
	mu       sync.Mutex
	payloads []Payload
}

func (s *recordingSink) Heartbeat(payload any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.payloads = append(s.payloads, payload.(Payload))
}

func (s *recordingSink) count() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.payloads)
}

func TestStartEmitsAtOnceAndOnEveryTick(t *testing.T) {
	Version = "1.2.3"
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sink := &recordingSink{}
	before := time.Now().UTC()
	Start(ctx, Config{ServerID: "srv-01", Interval: 50 * time.Millisecond, WatchedLogs: []string{"syslog"}}, sink)

	deadline := time.Now().Add(2 * time.Second)
	for sink.count() < 3 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if sink.count() < 3 {
		t.Fatalf("expected at least 3 heartbeats, got %d", sink.count())
	}

	sink.mu.Lock()
	p := sink.payloads[0]
	sink.mu.Unlock()
	if p.ServerID != "srv-01" || p.AgentVersion != "1.2.3" || len(p.WatchedLogs) != 1 {
		t.Errorf("unexpected payload %+v", p)
	}
	if p.Timestamp.Before(before) {
		t.Errorf("timestamp %v is before test start %v", p.Timestamp, before)
	}
}
