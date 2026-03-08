package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/disk"
)

// CollectDiskIO emits disk_read_bytes_per_sec and disk_write_bytes_per_sec
// per physical device. Rates are computed as delta between consecutive readings.
func CollectDiskIO(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	var prev map[string]disk.IOCountersStat
	elapsed := interval.Seconds()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			counters, err := disk.IOCountersWithContext(ctx)
			if err != nil {
				log.Printf("warn [disk_io]: collection failed: %v", err)
				continue
			}

			if prev != nil {
				now := t.UTC()
				for device, curr := range counters {
					p, ok := prev[device]
					if !ok {
						continue
					}
					readRate := float64(curr.ReadBytes-p.ReadBytes) / elapsed
					writeRate := float64(curr.WriteBytes-p.WriteBytes) / elapsed
					if readRate < 0 {
						readRate = 0
					}
					if writeRate < 0 {
						writeRate = 0
					}
					tags := map[string]string{"device": device}
					out <- Metric{Name: "disk_read_bytes_per_sec", Value: readRate, Timestamp: now, Tags: tags}
					out <- Metric{Name: "disk_write_bytes_per_sec", Value: writeRate, Timestamp: now, Tags: tags}
				}
			}
			prev = counters
		}
	}
}
