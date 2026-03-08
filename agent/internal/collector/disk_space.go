package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/disk"
)

// CollectDiskSpace emits disk_used_bytes, disk_total_bytes, and disk_usage_percent
// for every mounted partition. Each metric carries a "mount" tag.
func CollectDiskSpace(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			partitions, err := disk.PartitionsWithContext(ctx, false)
			if err != nil {
				log.Printf("warn [disk_space]: failed to list partitions: %v", err)
				continue
			}

			now := t.UTC()
			for _, p := range partitions {
				usage, err := disk.UsageWithContext(ctx, p.Mountpoint)
				if err != nil {
					// Some mounts (e.g. /proc, /sys) may deny access — skip silently.
					log.Printf("warn [disk_space]: usage failed for %s: %v", p.Mountpoint, err)
					continue
				}
				tags := map[string]string{"mount": p.Mountpoint}
				out <- Metric{Name: "disk_used_bytes", Value: float64(usage.Used), Timestamp: now, Tags: tags}
				out <- Metric{Name: "disk_total_bytes", Value: float64(usage.Total), Timestamp: now, Tags: tags}
				out <- Metric{Name: "disk_usage_percent", Value: usage.UsedPercent, Timestamp: now, Tags: tags}
			}
		}
	}
}
