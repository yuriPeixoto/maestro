// Package publisher batches the collectors' metrics and hands each batch to the transport.
package publisher

import (
	"context"

	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

const (
	batchSize    = 50
	flushTimeout = 5 * time.Second
)

// MetricsSink receives the batches (transport.Sink in the agent).
type MetricsSink interface {
	Metrics(batch []collector.Metric)
}

// Run reads from in and flushes a batch when it reaches batchSize metrics or flushTimeout elapses.
// On ctx cancellation it flushes what it holds and returns; buffering and retries belong to the transport.
func Run(ctx context.Context, in <-chan collector.Metric, sink MetricsSink) {
	batch := make([]collector.Metric, 0, batchSize)
	ticker := time.NewTicker(flushTimeout)
	defer ticker.Stop()

	flush := func() {
		if len(batch) == 0 {
			return
		}
		sink.Metrics(batch)
		batch = batch[:0]
	}

	for {
		select {
		case <-ctx.Done():
			flush()
			return

		case m := <-in:
			batch = append(batch, m)
			if len(batch) >= batchSize {
				flush()
				ticker.Reset(flushTimeout)
			}

		case <-ticker.C:
			flush()
		}
	}
}
