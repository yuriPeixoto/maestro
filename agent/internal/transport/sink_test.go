package transport

import (
	"regexp"
	"strings"
	"testing"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

type recordingBackend struct {
	sent   []Message
	closed bool
}

func (r *recordingBackend) send(m Message) { r.sent = append(r.sent, m) }
func (r *recordingBackend) close()         { r.closed = true }

func TestRouterGivesEveryBackendTheSameID(t *testing.T) {
	redisLike, natsLike := &recordingBackend{}, &recordingBackend{}
	r := newRouter(redisLike, natsLike)

	r.Metrics([]collector.Metric{{Name: "a"}})
	r.Event(EventPackages, map[string]string{})
	r.Heartbeat(map[string]string{})
	r.Close()

	if len(redisLike.sent) != 3 || len(natsLike.sent) != 3 {
		t.Fatalf("expected 3 messages per backend, got %d and %d", len(redisLike.sent), len(natsLike.sent))
	}
	for i := range redisLike.sent {
		if redisLike.sent[i].ID != natsLike.sent[i].ID {
			t.Errorf("message %d: ids differ (%s, %s)", i, redisLike.sent[i].ID, natsLike.sent[i].ID)
		}
	}
	if redisLike.sent[0].ID == redisLike.sent[1].ID {
		t.Error("two messages got the same id")
	}
	if !redisLike.closed || !natsLike.closed {
		t.Error("Close must close every backend")
	}
}

func TestRouterCopiesTheMetricBatch(t *testing.T) {
	b := &recordingBackend{}
	r := newRouter(b)
	batch := []collector.Metric{{Name: "original"}}
	r.Metrics(batch)
	batch[0].Name = "reused"

	if got := b.sent[0].Data.([]collector.Metric)[0].Name; got != "original" {
		t.Fatalf("the router must copy the batch, got %q", got)
	}
}

func TestRouterSkipsEmptyBatches(t *testing.T) {
	b := &recordingBackend{}
	r := newRouter(b)
	r.Metrics(nil)
	r.Logs("syslog", nil)
	if len(b.sent) != 0 {
		t.Fatalf("expected nothing sent, got %d", len(b.sent))
	}
}

func TestSplitLogLinesByCount(t *testing.T) {
	lines := make([]LogLine, maxLogLinesPerMessage*2+1)
	chunks := splitLogLines(lines)
	if len(chunks) != 3 || len(chunks[0]) != maxLogLinesPerMessage || len(chunks[2]) != 1 {
		t.Fatalf("unexpected chunking: %d chunks", len(chunks))
	}
}

func TestSplitLogLinesByBytes(t *testing.T) {
	big := strings.Repeat("x", maxLogBytesPerMessage/2+1)
	chunks := splitLogLines([]LogLine{{Line: big}, {Line: big}, {Line: "small"}})
	if len(chunks) != 2 || len(chunks[0]) != 1 || len(chunks[1]) != 2 {
		t.Fatalf("expected [1, 2] lines per chunk, got %d chunks", len(chunks))
	}
}

func TestSplitLogLinesKeepsAnOversizedLineAlone(t *testing.T) {
	huge := strings.Repeat("x", maxLogBytesPerMessage+1)
	chunks := splitLogLines([]LogLine{{Line: "a"}, {Line: huge}, {Line: "b"}})
	if len(chunks) != 3 {
		t.Fatalf("expected the oversized line in its own chunk, got %d chunks", len(chunks))
	}
}

var uuidV7 = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestNewIDIsUniqueUUIDv7(t *testing.T) {
	seen := make(map[string]bool)
	for i := 0; i < 1000; i++ {
		id := NewID()
		if !uuidV7.MatchString(id) {
			t.Fatalf("not a UUIDv7: %s", id)
		}
		if seen[id] {
			t.Fatalf("duplicate id %s", id)
		}
		seen[id] = true
	}
}

func TestParseMode(t *testing.T) {
	for _, s := range []string{"redis", "nats", "both"} {
		if _, err := ParseMode(s); err != nil {
			t.Errorf("%s: %v", s, err)
		}
	}
	if _, err := ParseMode("ambos"); err == nil {
		t.Error("expected an unknown mode to be rejected")
	}
	if !ModeBoth.UsesRedis() || !ModeBoth.UsesNATS() || ModeRedis.UsesNATS() || ModeNATS.UsesRedis() {
		t.Error("unexpected UsesRedis/UsesNATS")
	}
}

func TestValidServerID(t *testing.T) {
	for _, id := range []string{"web-1", "db-2", "dev_a"} {
		if !ValidServerID(id) {
			t.Errorf("%q should be valid", id)
		}
	}
	for _, id := range []string{"", "WebServer", "web.server", "a b", "a>"} {
		if ValidServerID(id) {
			t.Errorf("%q should be invalid", id)
		}
	}
}
