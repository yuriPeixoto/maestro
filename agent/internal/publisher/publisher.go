package publisher

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/redis/go-redis/v9"

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
}

// Publisher drains the metric channel, batches metrics, and sends them
// to Redis Streams. In Debug mode it prints to stdout instead.
type Publisher struct {
	cfg    Config
	client *redis.Client
}

// New creates a Publisher. In non-debug mode it establishes a Redis connection.
func New(cfg Config) (*Publisher, error) {
	p := &Publisher{cfg: cfg}

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
// batchSize is reached or flushTimeout elapses. Blocks until ctx is cancelled.
func (p *Publisher) Run(ctx context.Context, in <-chan collector.Metric) {
	batch := make([]collector.Metric, 0, batchSize)
	timer := time.NewTimer(flushTimeout)
	defer timer.Stop()

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
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				timer.Reset(flushTimeout)
			}

		case <-timer.C:
			flush()
			timer.Reset(flushTimeout)
		}
	}
}

// sendBatch serialises each Metric and sends it to Redis Streams via XADD.
func (p *Publisher) sendBatch(ctx context.Context, batch []collector.Metric) {
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
			log.Printf("warn [publisher]: redis XADD failed: %v", err)
		}
	}
	log.Printf("debug [publisher]: flushed %d metrics to stream %s", len(batch), p.cfg.Stream)
}

// printBatch prints metrics as formatted JSON lines for debug inspection.
func (p *Publisher) printBatch(batch []collector.Metric) {
	for _, m := range batch {
		b, _ := json.Marshal(m)
		fmt.Println(string(b))
	}
}
