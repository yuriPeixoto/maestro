// Package transport delivers what the agent collects to Maestro: Redis Streams (until 1.0.0), NATS
// JetStream (ADR-015), both during the parallel run, or stdout in debug mode. Collectors talk to a Sink
// and never to a transport directly.
package transport

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

// Message types. The first three have a subject of their own; every other type is an event and goes to
// maestro.ingest.<server>.events.
const (
	TypeMetrics   = "metrics"
	TypeLogs      = "logs"
	TypeHeartbeat = "heartbeat"

	EventAgentRegistered   = "agent_registered"
	EventAgentDeregistered = "agent_deregistered"
	EventPackages          = "packages"
	EventDBConnections     = "db_connections"
)

// LogLine is one line read from a log file.
type LogLine struct {
	Timestamp time.Time `json:"timestamp"`
	Line      string    `json:"line"`
}

// LogBatch is the data of a logs message.
type LogBatch struct {
	File  string    `json:"log_file"`
	Lines []LogLine `json:"lines"`
}

// DBSnapshot is the data of a db_connections event: the connections seen on one monitored database.
type DBSnapshot struct {
	DBType      string                   `json:"db_type"`
	Connections []collector.DBConnection `json:"connections"`
}

// Registration is the data of the agent_registered and agent_deregistered events.
type Registration struct {
	Hostname     string   `json:"hostname"`
	OS           string   `json:"os"`
	Tags         []string `json:"tags"`
	AgentVersion string   `json:"agent_version"`
}

// Message is one unit handed to the backends. The same ID reaches every backend, so the worker can
// drop a message it already stored, whichever path it came by.
type Message struct {
	ID     string
	Type   string
	SentAt time.Time
	Data   any
}

// envelope is the JSON published to NATS. The subject carries the server's identity; server_id is
// repeated so a consumer can drop a message whose payload disagrees with its subject (ADR-015).
type envelope struct {
	ID       string    `json:"id"`
	ServerID string    `json:"server_id"`
	Type     string    `json:"type"`
	SentAt   time.Time `json:"sent_at"`
	Data     any       `json:"data"`
}

func marshalEnvelope(serverID string, m Message) ([]byte, error) {
	return json.Marshal(envelope{ID: m.ID, ServerID: serverID, Type: m.Type, SentAt: m.SentAt, Data: m.Data})
}

func newMessage(msgType string, data any) Message {
	return Message{ID: NewID(), Type: msgType, SentAt: time.Now().UTC(), Data: data}
}

// NewID returns a UUIDv7 (RFC 9562): time-ordered, so ids sort roughly by creation, with 74 random bits.
func NewID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("transport: crypto/rand failed: " + err.Error())
	}

	var ms [8]byte
	binary.BigEndian.PutUint64(ms[:], uint64(time.Now().UnixMilli()))
	copy(b[0:6], ms[2:8])
	b[6] = (b[6] & 0x0f) | 0x70 // version 7
	b[8] = (b[8] & 0x3f) | 0x80 // RFC 9562 variant

	var out [36]byte
	hex.Encode(out[0:8], b[0:4])
	out[8] = '-'
	hex.Encode(out[9:13], b[4:6])
	out[13] = '-'
	hex.Encode(out[14:18], b[6:8])
	out[18] = '-'
	hex.Encode(out[19:23], b[8:10])
	out[23] = '-'
	hex.Encode(out[24:36], b[10:16])
	return string(out[:])
}
