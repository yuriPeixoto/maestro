package transport

import (
	"fmt"
	"log"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

// Mode is the agent.yaml transport setting.
type Mode string

const (
	ModeRedis Mode = "redis"
	ModeNATS  Mode = "nats"
	ModeBoth  Mode = "both"
)

// UsesRedis reports whether the mode publishes to Redis.
func (m Mode) UsesRedis() bool { return m == ModeRedis || m == ModeBoth }

// UsesNATS reports whether the mode publishes to NATS.
func (m Mode) UsesNATS() bool { return m == ModeNATS || m == ModeBoth }

// ParseMode validates a transport setting.
func ParseMode(s string) (Mode, error) {
	switch m := Mode(s); m {
	case ModeRedis, ModeNATS, ModeBoth:
		return m, nil
	}
	return "", fmt.Errorf("transport must be redis, nats or both, got %q", s)
}

// Log batches are split so that one NATS message stays well under the server's 1 MB max_payload.
const (
	maxLogLinesPerMessage = 500
	maxLogBytesPerMessage = 512 * 1024
)

// Sink is what collectors hand their data to. Calls never block for long and never fail: a transport
// that is down keeps the data in its buffer or drops it, and logs why.
type Sink interface {
	Metrics(batch []collector.Metric)
	Logs(file string, lines []LogLine)
	Heartbeat(payload any)
	Event(eventType string, payload any)
	Close()
}

// backend is one transport. send owns nothing it receives: the Router copies what callers may reuse.
type backend interface {
	send(m Message)
	close()
}

// Router is the Sink: it turns each call into Messages with one id and gives them to every backend.
type Router struct {
	backends []backend
}

func newRouter(backends ...backend) *Router {
	return &Router{backends: backends}
}

func (r *Router) dispatch(m Message) {
	for _, b := range r.backends {
		b.send(m)
	}
}

// Metrics sends one batch as one message.
func (r *Router) Metrics(batch []collector.Metric) {
	if len(batch) == 0 {
		return
	}
	cp := make([]collector.Metric, len(batch))
	copy(cp, batch)
	r.dispatch(newMessage(TypeMetrics, cp))
}

// Logs sends the new lines of a file, as many messages as needed to keep each one small.
func (r *Router) Logs(file string, lines []LogLine) {
	for _, chunk := range splitLogLines(lines) {
		r.dispatch(newMessage(TypeLogs, LogBatch{File: file, Lines: chunk}))
	}
}

// Heartbeat sends one heartbeat.
func (r *Router) Heartbeat(payload any) {
	r.dispatch(newMessage(TypeHeartbeat, payload))
}

// Event sends a server event (registration, package snapshot, database connections).
func (r *Router) Event(eventType string, payload any) {
	r.dispatch(newMessage(eventType, payload))
}

// Close flushes and closes every backend, in order.
func (r *Router) Close() {
	for _, b := range r.backends {
		b.close()
	}
}

func splitLogLines(lines []LogLine) [][]LogLine {
	var chunks [][]LogLine
	start, size := 0, 0
	for i, l := range lines {
		lineSize := len(l.Line)
		full := i-start >= maxLogLinesPerMessage || (size+lineSize > maxLogBytesPerMessage && i > start)
		if full {
			chunks = append(chunks, lines[start:i])
			start, size = i, 0
		}
		size += lineSize
	}
	if start < len(lines) {
		chunks = append(chunks, lines[start:])
	}
	return chunks
}

// stdoutBackend prints every message, for debug mode.
type stdoutBackend struct {
	serverID string
}

func (s stdoutBackend) send(m Message) {
	b, err := marshalEnvelope(s.serverID, m)
	if err != nil {
		log.Printf("warn [transport/stdout]: marshal failed: %v", err)
		return
	}
	fmt.Println(string(b))
}

func (stdoutBackend) close() {}
