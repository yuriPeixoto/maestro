package transport

import (
	"context"
	"errors"
	"fmt"
	"log"
	"regexp"
	"sync/atomic"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"

	"github.com/yuriPeixoto/maestro/agent/internal/diskqueue"
)

const (
	natsReconnectWait = 2 * time.Second
	natsFirstBackoff  = time.Second
	bytesPerMB        = 1024 * 1024
)

// serverIDToken is a NATS subject token as ADR-015 writes server ids: lowercase, no dots.
var serverIDToken = regexp.MustCompile(`^[a-z0-9_-]+$`)

// ValidServerID reports whether id can be used as the <server> token of the NATS subjects.
func ValidServerID(id string) bool {
	return serverIDToken.MatchString(id)
}

// NATSOptions configures the NATS JetStream backend (ADR-015).
type NATSOptions struct {
	URL      string
	NKeyFile string
	// CAFile verifies the server's TLS certificate. Empty means no TLS (local development only).
	CAFile          string
	PublishTimeout  time.Duration
	BufferDir       string
	BufferMaxMB     int
	RetryInterval   time.Duration
	ShutdownTimeout time.Duration
}

// natsBackend publishes to maestro.ingest.<server>.* and waits for JetStream's ack. Metrics, logs and
// events go through the disk queue first and leave it only once acked; heartbeats are published
// directly and dropped on failure, because a late heartbeat is worthless.
type natsBackend struct {
	serverID string
	opts     NATSOptions
	nc       *nats.Conn
	js       jetstream.JetStream
	queue    *diskqueue.Queue

	heartbeatFailing atomic.Bool

	reconnected chan struct{}
	stop        chan struct{}
	done        chan struct{}
}

func newNATSBackend(serverID string, opts NATSOptions) (*natsBackend, error) {
	if !ValidServerID(serverID) {
		return nil, fmt.Errorf("server_id %q is not a valid NATS subject token (lowercase letters, digits, - and _)", serverID)
	}
	applyNATSDefaults(&opts)

	queue, err := diskqueue.Open(opts.BufferDir, int64(opts.BufferMaxMB)*bytesPerMB)
	if err != nil {
		return nil, err
	}

	b := &natsBackend{
		serverID:    serverID,
		opts:        opts,
		queue:       queue,
		reconnected: make(chan struct{}, 1),
		stop:        make(chan struct{}),
		done:        make(chan struct{}),
	}

	connectOpts, err := b.connectOptions()
	if err != nil {
		return nil, err
	}
	// RetryOnFailedConnect: the agent starts even when NATS is down, and the queue holds the data.
	nc, err := nats.Connect(opts.URL, connectOpts...)
	if err != nil {
		return nil, fmt.Errorf("nats: connect %s: %w", opts.URL, err)
	}
	js, err := jetstream.New(nc)
	if err != nil {
		nc.Close()
		return nil, fmt.Errorf("nats: jetstream: %w", err)
	}
	b.nc, b.js = nc, js

	if pending := queue.Len(); pending > 0 {
		log.Printf("info [transport/nats]: %d message(s) left in the buffer by the previous run (%d KB)",
			pending, queue.Bytes()/1024)
	}
	go b.drainLoop()
	return b, nil
}

func applyNATSDefaults(opts *NATSOptions) {
	if opts.PublishTimeout <= 0 {
		opts.PublishTimeout = 5 * time.Second
	}
	if opts.BufferMaxMB < 1 {
		opts.BufferMaxMB = 256
	}
	if opts.RetryInterval <= 0 {
		opts.RetryInterval = 30 * time.Second
	}
	if opts.ShutdownTimeout <= 0 {
		opts.ShutdownTimeout = 10 * time.Second
	}
}

func (b *natsBackend) connectOptions() ([]nats.Option, error) {
	opts := []nats.Option{
		nats.Name("maestro-agent " + b.serverID),
		// The credential may only subscribe to its own inbox (ADR-015), where JetStream sends the acks.
		nats.CustomInboxPrefix("_INBOX_" + b.serverID),
		nats.RetryOnFailedConnect(true),
		nats.MaxReconnects(-1),
		nats.ReconnectWait(natsReconnectWait),
		// No client-side reconnect buffer: while disconnected a publish fails at once and the
		// message stays in the disk queue, which survives a restart.
		nats.ReconnectBufSize(-1),
		nats.ConnectHandler(func(nc *nats.Conn) {
			log.Printf("info [transport/nats]: connected to %s", nc.ConnectedUrlRedacted())
			b.signalReconnect()
		}),
		nats.ReconnectHandler(func(nc *nats.Conn) {
			log.Printf("info [transport/nats]: reconnected to %s", nc.ConnectedUrlRedacted())
			b.signalReconnect()
		}),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			if err != nil {
				log.Printf("warn [transport/nats]: disconnected: %v", err)
			}
		}),
		nats.ErrorHandler(func(_ *nats.Conn, _ *nats.Subscription, err error) {
			log.Printf("warn [transport/nats]: %v", err)
		}),
	}

	if b.opts.NKeyFile != "" {
		nkey, err := nats.NkeyOptionFromSeed(b.opts.NKeyFile)
		if err != nil {
			return nil, fmt.Errorf("nats: read nkey seed %s: %w", b.opts.NKeyFile, err)
		}
		opts = append(opts, nkey)
	}
	if b.opts.CAFile != "" {
		opts = append(opts, nats.RootCAs(b.opts.CAFile))
	}
	return opts, nil
}

func (b *natsBackend) signalReconnect() {
	select {
	case b.reconnected <- struct{}{}:
	default:
	}
}

func (b *natsBackend) subject(msgType string) string {
	switch msgType {
	case TypeMetrics, TypeLogs, TypeHeartbeat:
		return "maestro.ingest." + b.serverID + "." + msgType
	}
	return "maestro.ingest." + b.serverID + ".events"
}

func (b *natsBackend) send(m Message) {
	payload, err := marshalEnvelope(b.serverID, m)
	if err != nil {
		log.Printf("warn [transport/nats]: marshal %s failed: %v", m.Type, err)
		return
	}

	if m.Type == TypeHeartbeat {
		b.sendHeartbeat(m.ID, payload)
		return
	}

	dropped, err := b.queue.Put(m.ID, b.subject(m.Type), payload)
	if err != nil {
		log.Printf("warn [transport/nats]: %s message %s not buffered: %v", m.Type, m.ID, err)
		return
	}
	if dropped > 0 {
		log.Printf("warn [transport/nats]: buffer full (%d MB) — dropped the %d oldest message(s)",
			b.opts.BufferMaxMB, dropped)
	}
}

// sendHeartbeat publishes directly. During an outage it logs the first failure and the recovery only,
// not one line per interval.
func (b *natsBackend) sendHeartbeat(id string, payload []byte) {
	err := b.publish(id, b.subject(TypeHeartbeat), payload)
	wasFailing := b.heartbeatFailing.Swap(err != nil)
	switch {
	case err != nil && !wasFailing:
		log.Printf("warn [transport/nats]: heartbeat not sent: %v — dropping heartbeats until NATS answers", err)
	case err == nil && wasFailing:
		log.Printf("info [transport/nats]: heartbeats sent again")
	}
}

// publish sends one message and waits for the stream's ack. The message id makes a retry inside the
// stream's duplicate window harmless.
func (b *natsBackend) publish(id, subject string, payload []byte) error {
	ctx, cancel := context.WithTimeout(context.Background(), b.opts.PublishTimeout)
	defer cancel()
	_, err := b.js.Publish(ctx, subject, payload, jetstream.WithMsgID(id))
	return err
}

// drainLoop sends the queue oldest first, one message at a time, removing each only after its ack.
// On failure it backs off (1 s doubling up to RetryInterval) or wakes up on a reconnect.
func (b *natsBackend) drainLoop() {
	defer close(b.done)
	backoff := natsFirstBackoff
	failing := false
	var deadline time.Time

	for {
		if b.stopping() && deadline.IsZero() {
			deadline = time.Now().Add(b.opts.ShutdownTimeout)
		}
		if !deadline.IsZero() && (b.queue.Len() == 0 || time.Now().After(deadline)) {
			return
		}

		item, ok, err := b.queue.Peek()
		if err != nil {
			// An unreadable file was dropped, or the disk failed: pause so a disk error is not a hot loop.
			log.Printf("warn [transport/nats]: %v", err)
			b.waitBackoff(natsFirstBackoff)
			continue
		}
		if !ok {
			b.waitForWork()
			continue
		}

		err = b.publish(item.ID, item.Subject, item.Payload)
		if err == nil || errors.Is(err, nats.ErrMaxPayload) {
			b.logDropTooLarge(item, err)
			b.queue.Remove(item)
			if failing {
				log.Printf("info [transport/nats]: publishing again — %d message(s) still buffered", b.queue.Len())
			}
			failing, backoff = false, natsFirstBackoff
			continue
		}

		if !failing {
			log.Printf("warn [transport/nats]: publish failed: %v — keeping %d message(s) on disk", err, b.queue.Len())
			failing = true
		}
		if b.stopping() {
			// Shutting down with NATS unreachable: what is left is sent on the next start.
			return
		}
		b.waitBackoff(backoff)
		backoff = min(backoff*2, b.opts.RetryInterval)
	}
}

func (b *natsBackend) logDropTooLarge(item diskqueue.Item, err error) {
	if err == nil {
		return
	}
	log.Printf("warn [transport/nats]: dropped message %s on %s: %v", item.ID, item.Subject, err)
}

func (b *natsBackend) stopping() bool {
	select {
	case <-b.stop:
		return true
	default:
		return false
	}
}

func (b *natsBackend) waitForWork() {
	if b.stopping() {
		return
	}
	select {
	case <-b.queue.Notify():
	case <-b.stop:
	}
}

func (b *natsBackend) waitBackoff(d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
	case <-b.reconnected:
	case <-b.stop:
	}
}

// close gives the queue up to ShutdownTimeout to drain, then closes the connection. Whatever is left
// stays on disk for the next start.
func (b *natsBackend) close() {
	close(b.stop)
	<-b.done
	if pending := b.queue.Len(); pending > 0 {
		log.Printf("info [transport/nats]: %d message(s) kept on disk for the next start", pending)
	}
	b.nc.Close()
}
