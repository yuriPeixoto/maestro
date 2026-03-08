package collector

import (
	"context"
	"time"
)

// IntervalConfig mirrors config.IntervalConfig to avoid a circular import.
type IntervalConfig struct {
	CPU          time.Duration
	Memory       time.Duration
	DiskIO       time.Duration
	DiskSpace    time.Duration
	Network      time.Duration
	ProcessCount time.Duration
}

// Start launches one goroutine per metric type. Each goroutine runs independently
// on its own ticker and sends Metrics to the shared out channel.
// The serverID is injected into every Metric here, so individual collectors
// don't need to know about it.
// Start returns when ctx is cancelled.
func Start(ctx context.Context, serverID string, intervals IntervalConfig, out chan<- Metric) {
	wrap := func(fn func(context.Context, time.Duration, chan<- Metric), interval time.Duration) {
		go func() {
			// Intermediate channel so we can inject serverID.
			raw := make(chan Metric, 50)
			go fn(ctx, interval, raw)
			for {
				select {
				case <-ctx.Done():
					return
				case m := <-raw:
					m.ServerID = serverID
					out <- m
				}
			}
		}()
	}

	wrap(CollectCPU, intervals.CPU)
	wrap(CollectMemory, intervals.Memory)
	wrap(CollectDiskIO, intervals.DiskIO)
	wrap(CollectDiskSpace, intervals.DiskSpace)
	wrap(CollectNetwork, intervals.Network)
	wrap(CollectProcessCount, intervals.ProcessCount)
}
