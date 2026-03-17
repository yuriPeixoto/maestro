package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/process"
)

// CollectProcessCount emits process_count — the total number of running processes.
func CollectProcessCount(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			procs, err := process.ProcessesWithContext(ctx)
			if err != nil {
				log.Printf("warn [process]: collection failed: %v", err)
				continue
			}
			out <- Metric{
				Name:      MetricProcessCount,
				Value:     float64(len(procs)),
				Timestamp: t.UTC(),
			}
		}
	}
}
