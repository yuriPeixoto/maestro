package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/mem"
)

// CollectMemory emits memory_used_bytes, memory_available_bytes, and
// memory_usage_percent at the given interval.
func CollectMemory(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			v, err := mem.VirtualMemoryWithContext(ctx)
			if err != nil {
				log.Printf("warn [memory]: collection failed: %v", err)
				continue
			}
			now := t.UTC()
			out <- Metric{Name: "memory_used_bytes", Value: float64(v.Used), Timestamp: now}
			out <- Metric{Name: "memory_available_bytes", Value: float64(v.Available), Timestamp: now}
			out <- Metric{Name: "memory_usage_percent", Value: v.UsedPercent, Timestamp: now}
		}
	}
}
