package publisher

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

const (
	batchSize    = 50
	flushTimeout = 5 * time.Second
)

// Config holds publisher-specific settings.
type Config struct {
	RedisAddr     string
	RedisPassword string
	Stream        string
	Debug         bool // if true, print to stdout instead of Redis
	BufferCap     int
	RetryInterval time.Duration
}

// Publisher drains the metric channel, batches metrics, and sends them
// to Redis Streams. Failed writes are retained in a local ring buffer and
// retried on a separate ticker. In Debug mode it prints to stdout instead.
type Publisher struct {
	cfg    Config
	client *redis.Client
	ring   *buffer.Ring
}

// New creates a Publisher. In non-debug mode it establishes a Redis connection.
func New(cfg Config) (*Publisher, error) {
	cap := cfg.BufferCap
	if cap < 1 {
		cap = 1000
	}
	p := &Publisher{
		cfg:  cfg,
		ring: buffer.New(cap),
	}

	if !cfg.Debug {
		p.client = redis.NewClient(&redis.Options{
			Addr:     cfg.RedisAddr,
			Password: cfg.RedisPassword,
		})
		// Verify connection on startup.
		ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		if err := p.client.Ping(ctx).Err(); err != nil {
			return nil, fmt.Errorf("redis connection failed (%s): %w", cfg.RedisAddr, err)
		}
		log.Printf("info [publisher]: connected to Redis at %s, stream=%s", cfg.RedisAddr, cfg.Stream)
	} else {
		log.Printf("info [publisher]: DEBUG mode — metrics will be printed to stdout")
	}

	return p, nil
}

// Run reads from in, accumulates a batch, and flushes when either
// batchSize is reached or flushTimeout elapses. A separate retry ticker
// drains the ring buffer back to Redis when it becomes available.
// Blocks until ctx is cancelled.
func (p *Publisher) Run(ctx context.Context, in <-chan collector.Metric) {
	batch := make([]collector.Metric, 0, batchSize)
	flushTicker := time.NewTicker(flushTimeout)
	defer flushTicker.Stop()

	retryInterval := p.cfg.RetryInterval
	if retryInterval <= 0 {
		retryInterval = 30 * time.Second
	}
	retryTicker := time.NewTicker(retryInterval)
	defer retryTicker.Stop()

	flush := func() {
		if len(batch) == 0 {
			return
		}
		if p.cfg.Debug {
			p.printBatch(batch)
		} else {
			p.sendBatch(ctx, batch)
		}
		batch = batch[:0]
	}

	for {
		select {
		case <-ctx.Done():
			flush() // best-effort final flush
			return

		case m := <-in:
			batch = append(batch, m)
			if len(batch) >= batchSize {
				flush()
				flushTicker.Reset(flushTimeout)
			}

		case <-flushTicker.C:
			flush()

		case <-retryTicker.C:
			p.drainBuffer(ctx)
		}
	}
}

// sendBatch serialises each Metric and sends it to Redis Streams via XADD.
// On failure the entire batch is pushed to the ring buffer for later retry.
func (p *Publisher) sendBatch(ctx context.Context, batch []collector.Metric) {
	var failed []collector.Metric

	for _, m := range batch {
		payload, err := json.Marshal(m)
		if err != nil {
			log.Printf("warn [publisher]: marshal failed: %v", err)
			continue
		}
		err = p.client.XAdd(ctx, &redis.XAddArgs{
			Stream: p.cfg.Stream,
			Values: map[string]any{
				"data": string(payload),
			},
		}).Err()
		if err != nil {
			log.Printf("warn [publisher]: redis XADD failed: %v — buffering metric", err)
			failed = append(failed, m)
		}
	}

	if len(failed) > 0 {
		p.ring.Push(failed)
		log.Printf("warn [publisher]: buffered %d failed metrics (buffer size: %d)", len(failed), p.ring.Len())
	} else {
		log.Printf("debug [publisher]: flushed %d metrics to stream %s", len(batch), p.cfg.Stream)
	}
}

// drainBuffer attempts to flush all buffered batches back to Redis.
// Batches that fail again are re-queued into the ring buffer.
func (p *Publisher) drainBuffer(ctx context.Context) {
	batches := p.ring.PopAll()
	if len(batches) == 0 {
		return
	}

	log.Printf("info [publisher]: retrying %d buffered batch(es)...", len(batches))
	requeued := 0

	for _, batch := range batches {
		var failed []collector.Metric
		for _, m := range batch {
			payload, err := json.Marshal(m)
			if err != nil {
				continue
			}
			err = p.client.XAdd(ctx, &redis.XAddArgs{
				Stream: p.cfg.Stream,
				Values: map[string]any{"data": string(payload)},
			}).Err()
			if err != nil {
				failed = append(failed, m)
			}
		}
		if len(failed) > 0 {
			p.ring.Push(failed)
			requeued++
		}
	}

	flushed := len(batches) - requeued
	if flushed > 0 {
		log.Printf("info [publisher]: retry flushed %d batch(es), %d re-queued", flushed, requeued)
	} else {
		log.Printf("warn [publisher]: retry failed — all %d batch(es) re-queued", requeued)
	}
}

// printBatch prints metrics as formatted JSON lines for debug inspection.
func (p *Publisher) printBatch(batch []collector.Metric) {
	for _, m := range batch {
		b, _ := json.Marshal(m)
		fmt.Println(string(b))
	}
}
