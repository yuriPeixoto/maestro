package transport

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
	"github.com/nats-io/nkeys"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

const (
	waitTimeout = 10 * time.Second
	ownServer   = "dev-a"
)

// testNATS is a JetStream server with the account layout of ADR-015 (deploy/nats/render-users.sh):
// an operator, and a user for ownServer that may publish only maestro.ingest.dev-a.> and hear only
// its own commands and inbox.
type testNATS struct {
	t         *testing.T
	storeDir  string
	port      int
	adminSeed string
	ownSeed   string
	adminPub  string
	ownPub    string
	srv       *server.Server
}

func newUserSeed(t *testing.T, dir, name string) (seedFile, publicKey string) {
	t.Helper()
	kp, err := nkeys.CreateUser()
	if err != nil {
		t.Fatal(err)
	}
	seed, _ := kp.Seed()
	publicKey, _ = kp.PublicKey()
	seedFile = filepath.Join(dir, name+".nk")
	if err := os.WriteFile(seedFile, seed, 0o600); err != nil {
		t.Fatal(err)
	}
	return seedFile, publicKey
}

func startTestNATS(t *testing.T) *testNATS {
	t.Helper()
	keys := t.TempDir()
	n := &testNATS{t: t, storeDir: t.TempDir(), port: server.RANDOM_PORT}
	n.adminSeed, n.adminPub = newUserSeed(t, keys, "admin")
	n.ownSeed, n.ownPub = newUserSeed(t, keys, ownServer)
	n.start()
	n.createStreams()
	t.Cleanup(n.stop)
	return n
}

func (n *testNATS) options() *server.Options {
	return &server.Options{
		Host:      "127.0.0.1",
		Port:      n.port,
		JetStream: true,
		StoreDir:  n.storeDir,
		NoLog:     true,
		NoSigs:    true,
		Nkeys: []*server.NkeyUser{
			{Nkey: n.adminPub},
			{Nkey: n.ownPub, Permissions: &server.Permissions{
				Publish:   &server.SubjectPermission{Allow: []string{"maestro.ingest." + ownServer + ".>"}},
				Subscribe: &server.SubjectPermission{Allow: []string{"maestro.cmd." + ownServer, "_INBOX_" + ownServer + ".>"}},
				Response:  &server.ResponsePermission{MaxMsgs: 1, Expires: time.Minute},
			}},
		},
	}
}

func (n *testNATS) start() {
	n.t.Helper()
	srv, err := server.NewServer(n.options())
	if err != nil {
		n.t.Fatal(err)
	}
	go srv.Start()
	if !srv.ReadyForConnections(waitTimeout) {
		n.t.Fatal("nats server not ready")
	}
	n.srv = srv
	n.port = srv.Addr().(*net.TCPAddr).Port
}

func (n *testNATS) stop() {
	if n.srv == nil {
		return
	}
	n.srv.Shutdown()
	n.srv.WaitForShutdown()
	n.srv = nil
}

func (n *testNATS) url() string {
	return "nats://127.0.0.1:" + strconv.Itoa(n.port)
}

func (n *testNATS) admin() jetstream.JetStream {
	n.t.Helper()
	opt, err := nats.NkeyOptionFromSeed(n.adminSeed)
	if err != nil {
		n.t.Fatal(err)
	}
	nc, err := nats.Connect(n.url(), opt)
	if err != nil {
		n.t.Fatal(err)
	}
	n.t.Cleanup(nc.Close)
	js, err := jetstream.New(nc)
	if err != nil {
		n.t.Fatal(err)
	}
	return js
}

func (n *testNATS) createStreams() {
	js := n.admin()
	ctx, cancel := context.WithTimeout(context.Background(), waitTimeout)
	defer cancel()
	for _, kind := range []string{"metrics", "logs", "events"} {
		_, err := js.CreateStream(ctx, jetstream.StreamConfig{
			Name:       "MAESTRO_" + strings.ToUpper(kind),
			Subjects:   []string{"maestro.ingest.*." + kind},
			Duplicates: 2 * time.Minute,
		})
		if err != nil {
			n.t.Fatal(err)
		}
	}
	_, err := js.CreateStream(ctx, jetstream.StreamConfig{
		Name:              "MAESTRO_HEARTBEAT",
		Subjects:          []string{"maestro.ingest.*.heartbeat"},
		MaxMsgsPerSubject: 1,
		AllowDirect:       true,
		Duplicates:        2 * time.Minute,
	})
	if err != nil {
		n.t.Fatal(err)
	}
}

// messages returns what a stream holds, oldest first.
func (n *testNATS) messages(stream string) []*jetstream.RawStreamMsg {
	n.t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), waitTimeout)
	defer cancel()
	s, err := n.admin().Stream(ctx, stream)
	if err != nil {
		n.t.Fatal(err)
	}
	info, err := s.Info(ctx)
	if err != nil {
		n.t.Fatal(err)
	}
	var out []*jetstream.RawStreamMsg
	for seq := info.State.FirstSeq; seq <= info.State.LastSeq && info.State.Msgs > 0; seq++ {
		msg, err := s.GetMsg(ctx, seq)
		if err != nil {
			continue
		}
		out = append(out, msg)
	}
	return out
}

func (n *testNATS) waitForMessages(stream string, want int) []*jetstream.RawStreamMsg {
	n.t.Helper()
	deadline := time.Now().Add(waitTimeout)
	for {
		msgs := n.messages(stream)
		if len(msgs) >= want || time.Now().After(deadline) {
			if len(msgs) != want {
				n.t.Fatalf("%s: expected %d message(s), got %d", stream, want, len(msgs))
			}
			return msgs
		}
		time.Sleep(20 * time.Millisecond)
	}
}

func (n *testNATS) backend(serverID, bufferDir string) *natsBackend {
	n.t.Helper()
	b, err := newNATSBackend(serverID, NATSOptions{
		URL:             n.url(),
		NKeyFile:        n.ownSeed,
		PublishTimeout:  time.Second,
		BufferDir:       bufferDir,
		BufferMaxMB:     1,
		RetryInterval:   200 * time.Millisecond,
		ShutdownTimeout: 2 * time.Second,
	})
	if err != nil {
		n.t.Fatal(err)
	}
	return b
}

func waitQueueEmpty(t *testing.T, b *natsBackend) {
	t.Helper()
	deadline := time.Now().Add(waitTimeout)
	for b.queue.Len() > 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if b.queue.Len() != 0 {
		t.Fatalf("expected the buffer to drain, %d message(s) left", b.queue.Len())
	}
}

func decodeEnvelope(t *testing.T, data []byte) map[string]any {
	t.Helper()
	var env map[string]any
	if err := json.Unmarshal(data, &env); err != nil {
		t.Fatalf("payload is not JSON: %v", err)
	}
	return env
}

func TestNATSPublishesWithAckIDAndOwnSubject(t *testing.T) {
	n := startTestNATS(t)
	b := n.backend(ownServer, t.TempDir())
	defer b.close()

	m := newMessage(TypeMetrics, []collector.Metric{{ServerID: ownServer, Name: "cpu_usage_pct", Value: 12.5}})
	b.send(m)
	waitQueueEmpty(t, b)

	msgs := n.waitForMessages("MAESTRO_METRICS", 1)
	if msgs[0].Subject != "maestro.ingest.dev-a.metrics" {
		t.Errorf("unexpected subject %q", msgs[0].Subject)
	}
	if got := msgs[0].Header.Get(jetstream.MsgIDHeader); got != m.ID {
		t.Errorf("expected Nats-Msg-Id %q, got %q", m.ID, got)
	}
	env := decodeEnvelope(t, msgs[0].Data)
	if env["id"] != m.ID || env["server_id"] != ownServer || env["type"] != TypeMetrics {
		t.Errorf("unexpected envelope %v", env)
	}
	if data, ok := env["data"].([]any); !ok || len(data) != 1 {
		t.Errorf("expected one metric in data, got %v", env["data"])
	}
}

func TestNATSSubjectsPerType(t *testing.T) {
	n := startTestNATS(t)
	b := n.backend(ownServer, t.TempDir())
	defer b.close()

	b.send(newMessage(TypeLogs, LogBatch{File: "syslog", Lines: []LogLine{{Line: "hello"}}}))
	b.send(newMessage(EventAgentRegistered, Registration{Hostname: "h", OS: "linux", Tags: []string{}}))
	b.send(newMessage(TypeHeartbeat, map[string]string{"server_id": ownServer}))
	waitQueueEmpty(t, b)

	if msgs := n.waitForMessages("MAESTRO_LOGS", 1); msgs[0].Subject != "maestro.ingest.dev-a.logs" {
		t.Errorf("logs went to %q", msgs[0].Subject)
	}
	events := n.waitForMessages("MAESTRO_EVENTS", 1)
	if events[0].Subject != "maestro.ingest.dev-a.events" {
		t.Errorf("event went to %q", events[0].Subject)
	}
	if env := decodeEnvelope(t, events[0].Data); env["type"] != EventAgentRegistered {
		t.Errorf("expected an agent_registered event, got %v", env["type"])
	}
	if msgs := n.waitForMessages("MAESTRO_HEARTBEAT", 1); msgs[0].Subject != "maestro.ingest.dev-a.heartbeat" {
		t.Errorf("heartbeat went to %q", msgs[0].Subject)
	}
}

func TestNATSDuplicateIDIsStoredOnce(t *testing.T) {
	n := startTestNATS(t)
	b := n.backend(ownServer, t.TempDir())
	defer b.close()

	m := newMessage(TypeMetrics, []collector.Metric{{Name: "x"}})
	b.send(m)
	b.send(m) // a retry after a lost ack
	waitQueueEmpty(t, b)

	n.waitForMessages("MAESTRO_METRICS", 1)
}

func TestNATSBuffersOnDiskWhileServerIsDownAndResends(t *testing.T) {
	n := startTestNATS(t)
	n.stop()

	b := n.backend(ownServer, t.TempDir())
	defer b.close()
	for i := 0; i < 3; i++ {
		b.send(newMessage(TypeMetrics, []collector.Metric{{Name: "during_outage"}}))
	}
	time.Sleep(300 * time.Millisecond)
	if got := b.queue.Len(); got != 3 {
		t.Fatalf("expected 3 messages kept on disk during the outage, got %d", got)
	}

	n.start()
	waitQueueEmpty(t, b)
	n.waitForMessages("MAESTRO_METRICS", 3)
}

func TestNATSBufferSurvivesAgentRestart(t *testing.T) {
	n := startTestNATS(t)
	n.stop()
	bufferDir := t.TempDir()

	first := n.backend(ownServer, bufferDir)
	first.send(newMessage(EventAgentRegistered, Registration{Hostname: "h"}))
	first.send(newMessage(TypeMetrics, []collector.Metric{{Name: "before_restart"}}))
	first.close() // NATS unreachable: both stay on disk

	n.start()
	second := n.backend(ownServer, bufferDir)
	defer second.close()
	waitQueueEmpty(t, second)
	n.waitForMessages("MAESTRO_EVENTS", 1)
	n.waitForMessages("MAESTRO_METRICS", 1)
}

func TestNATSHeartbeatIsNotBuffered(t *testing.T) {
	n := startTestNATS(t)
	n.stop()

	b := n.backend(ownServer, t.TempDir())
	defer b.close()
	b.send(newMessage(TypeHeartbeat, map[string]string{"server_id": ownServer}))
	if got := b.queue.Len(); got != 0 {
		t.Fatalf("a heartbeat must not be buffered, queue has %d", got)
	}
}

func TestNATSRefusedOnNeighbourSubject(t *testing.T) {
	n := startTestNATS(t)
	// dev-a's credential claiming to be dev-b: the server refuses, nothing is stored, the data stays on disk.
	b := n.backend("dev-b", t.TempDir())
	defer b.close()

	b.send(newMessage(TypeMetrics, []collector.Metric{{Name: "spoofed"}}))
	time.Sleep(1500 * time.Millisecond)

	if got := len(n.messages("MAESTRO_METRICS")); got != 0 {
		t.Fatalf("the neighbour's subject must be refused, stream has %d message(s)", got)
	}
	if b.queue.Len() != 1 {
		t.Fatalf("a refused message stays buffered, queue has %d", b.queue.Len())
	}
}

func TestNATSAckNeedsTheServersInboxPrefix(t *testing.T) {
	n := startTestNATS(t)
	opt, err := nats.NkeyOptionFromSeed(n.ownSeed)
	if err != nil {
		t.Fatal(err)
	}
	// Default _INBOX. prefix: the credential may not subscribe there, so the ack never arrives.
	nc, err := nats.Connect(n.url(), opt)
	if err != nil {
		t.Fatal(err)
	}
	defer nc.Close()
	js, _ := jetstream.New(nc)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if _, err := js.Publish(ctx, "maestro.ingest.dev-a.metrics", []byte("{}")); err == nil {
		t.Fatal("expected the publish to fail without the _INBOX_<server> prefix")
	}
}

func TestNATSRejectsInvalidServerID(t *testing.T) {
	_, err := newNATSBackend("Web.Server", NATSOptions{URL: "nats://127.0.0.1:1", BufferDir: t.TempDir()})
	if err == nil {
		t.Fatal("expected an invalid server id to be rejected")
	}
}
