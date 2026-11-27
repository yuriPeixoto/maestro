package transport

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/yuriPeixoto/maestro/agent/internal/buffer"
	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

// Redis keys the API reads. The stream names come from the configuration; the hashes are fixed.
const (
	redisPackagesKey   = "maestro:packages"
	redisDBSnapshotKey = "maestro:db_snapshots"

	redisMetricsMaxLen   = 10_000
	redisLogsMaxLen      = 20_000
	redisHeartbeatMaxLen = 1_000

	redisPingTimeout = 3 * time.Second
	redisOpTimeout   = 5 * time.Second

	redisShutdownRetryPause = 500 * time.Millisecond
)

// sleepCtx waits d or until ctx ends.
func sleepCtx(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

// RedisOptions configures the Redis Streams backend (the transport until 1.0.0).
type RedisOptions struct {
	Addr            string
	Password        string
	MetricsStream   string
	LogsStream      string
	HeartbeatStream string
	BufferCap       int
	RetryInterval   time.Duration
	ShutdownTimeout time.Duration
}

// redisBackend writes what 0.3.x wrote, with the message id in an extra msg_id field that today's
// consumers ignore. Failed metric batches wait in a memory ring; logs, heartbeats and snapshots that
// fail are dropped, as before.
type redisBackend struct {
	serverID string
	opts     RedisOptions
	client   *redis.Client
	ring     *buffer.Ring

	stop chan struct{}
	done chan struct{}
}

func newRedisBackend(serverID string, opts RedisOptions) (*redisBackend, error) {
	if opts.BufferCap < 1 {
		opts.BufferCap = 1000
	}
	if opts.RetryInterval <= 0 {
		opts.RetryInterval = 30 * time.Second
	}
	if opts.ShutdownTimeout <= 0 {
		opts.ShutdownTimeout = 10 * time.Second
	}

	client := redis.NewClient(&redis.Options{Addr: opts.Addr, Password: opts.Password})
	ctx, cancel := context.WithTimeout(context.Background(), redisPingTimeout)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		client.Close()
		return nil, fmt.Errorf("redis connection failed (%s): %w", opts.Addr, err)
	}
	log.Printf("info [transport/redis]: connected to %s, streams=%s,%s,%s",
		opts.Addr, opts.MetricsStream, opts.LogsStream, opts.HeartbeatStream)

	b := &redisBackend{
		serverID: serverID,
		opts:     opts,
		client:   client,
		ring:     buffer.New(opts.BufferCap),
		stop:     make(chan struct{}),
		done:     make(chan struct{}),
	}
	go b.retryLoop()
	return b, nil
}

func (b *redisBackend) send(m Message) {
	ctx, cancel := context.WithTimeout(context.Background(), redisOpTimeout)
	defer cancel()

	switch data := m.Data.(type) {
	case []collector.Metric:
		b.sendMetrics(ctx, m.ID, data)
	case LogBatch:
		b.sendLogs(ctx, m.ID, data)
	case DBSnapshot:
		b.hset(ctx, redisDBSnapshotKey, b.serverID+":"+data.DBType, data.Connections)
	default:
		b.sendOther(ctx, m)
	}
}

func (b *redisBackend) sendOther(ctx context.Context, m Message) {
	switch m.Type {
	case TypeHeartbeat:
		b.xadd(ctx, b.opts.HeartbeatStream, redisHeartbeatMaxLen, m.ID, m.Data)
	case EventPackages:
		b.hset(ctx, redisPackagesKey, b.serverID, m.Data)
	case EventAgentRegistered, EventAgentDeregistered:
		// Redis mode registers over HTTP (registry package); nothing to write here.
	default:
		log.Printf("warn [transport/redis]: no Redis destination for message type %q — skipped", m.Type)
	}
}

func (b *redisBackend) sendMetrics(ctx context.Context, id string, batch []collector.Metric) {
	failed := b.writeMetrics(ctx, id, batch)
	if len(failed) == 0 {
		return
	}
	b.ring.Push(id, failed)
	log.Printf("warn [transport/redis]: buffered %d failed metrics (buffer size: %d)", len(failed), b.ring.Len())
}

// writeMetrics XADDs one entry per metric, as the API's consumer expects, and returns the ones that failed.
func (b *redisBackend) writeMetrics(ctx context.Context, id string, batch []collector.Metric) []collector.Metric {
	var failed []collector.Metric
	for _, metric := range batch {
		payload, err := json.Marshal(metric)
		if err != nil {
			log.Printf("warn [transport/redis]: marshal failed: %v", err)
			continue
		}
		err = b.client.XAdd(ctx, &redis.XAddArgs{
			Stream: b.opts.MetricsStream,
			MaxLen: redisMetricsMaxLen,
			Approx: true,
			Values: map[string]any{"data": string(payload), "msg_id": id},
		}).Err()
		if err != nil {
			failed = append(failed, metric)
		}
	}
	return failed
}

func (b *redisBackend) sendLogs(ctx context.Context, id string, batch LogBatch) {
	for _, line := range batch.Lines {
		err := b.client.XAdd(ctx, &redis.XAddArgs{
			Stream: b.opts.LogsStream,
			MaxLen: redisLogsMaxLen,
			Approx: true,
			Values: map[string]any{
				"server_id": b.serverID,
				"log_file":  batch.File,
				"timestamp": line.Timestamp.Format(time.RFC3339Nano),
				"line":      line.Line,
				"msg_id":    id,
			},
		}).Err()
		if err != nil {
			log.Printf("warn [transport/redis]: XADD failed for %s: %v", batch.File, err)
			return
		}
	}
}

func (b *redisBackend) xadd(ctx context.Context, stream string, maxLen int64, id string, data any) {
	payload, err := json.Marshal(data)
	if err != nil {
		log.Printf("warn [transport/redis]: marshal failed: %v", err)
		return
	}
	err = b.client.XAdd(ctx, &redis.XAddArgs{
		Stream: stream,
		MaxLen: maxLen,
		Approx: true,
		Values: map[string]any{"data": string(payload), "msg_id": id},
	}).Err()
	if err != nil {
		log.Printf("warn [transport/redis]: XADD to %q failed: %v — skipping", stream, err)
	}
}

func (b *redisBackend) hset(ctx context.Context, key, field string, data any) {
	payload, err := json.Marshal(data)
	if err != nil {
		log.Printf("warn [transport/redis]: marshal failed: %v", err)
		return
	}
	if err := b.client.HSet(ctx, key, field, payload).Err(); err != nil {
		log.Printf("warn [transport/redis]: HSET %q failed: %v — skipping", key, err)
	}
}

func (b *redisBackend) retryLoop() {
	defer close(b.done)
	ticker := time.NewTicker(b.opts.RetryInterval)
	defer ticker.Stop()
	for {
		select {
		case <-b.stop:
			return
		case <-ticker.C:
			ctx, cancel := context.WithTimeout(context.Background(), redisOpTimeout)
			b.drainRing(ctx)
			cancel()
		}
	}
}

// drainRing retries every buffered batch once; the ones that fail again go back to the ring.
func (b *redisBackend) drainRing(ctx context.Context) {
	batches := b.ring.PopAll()
	if len(batches) == 0 {
		return
	}

	requeued := 0
	for _, batch := range batches {
		failed := b.writeMetrics(ctx, batch.ID, batch.Metrics)
		if len(failed) > 0 {
			b.ring.Push(batch.ID, failed)
			requeued++
		}
	}
	log.Printf("info [transport/redis]: retried %d buffered batch(es), %d re-queued", len(batches), requeued)
}

// close stops the retry loop and gives the ring up to ShutdownTimeout to drain.
func (b *redisBackend) close() {
	close(b.stop)
	<-b.done
	defer b.client.Close()

	ctx, cancel := context.WithTimeout(context.Background(), b.opts.ShutdownTimeout)
	defer cancel()
	for b.ring.Len() > 0 && ctx.Err() == nil {
		b.drainRing(ctx)
		if b.ring.Len() > 0 {
			sleepCtx(ctx, redisShutdownRetryPause)
		}
	}
	if pending := b.ring.Len(); pending > 0 {
		log.Printf("warn [transport/redis]: shutdown timeout — %d batch(es) dropped", pending)
	}
}
