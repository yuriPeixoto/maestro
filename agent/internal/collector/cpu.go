package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
)

// CollectCPU emits cpu_usage_percent at the given interval.
// Uses a non-blocking interval measurement (0 duration = since last call).
func CollectCPU(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			percents, err := cpu.PercentWithContext(ctx, 0, false)
			if err != nil {
				log.Printf("warn [cpu]: collection failed: %v", err)
				continue
			}
			if len(percents) == 0 {
				continue
			}
			out <- Metric{
				Name:      MetricCPUUsagePercent,
				Value:     percents[0],
				Timestamp: t.UTC(),
			}
		}
	}
}
