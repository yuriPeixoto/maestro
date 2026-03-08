package collector

import (
	"context"
	"log"
	"time"

	"github.com/shirou/gopsutil/v3/net"
)

// CollectNetwork emits network_bytes_in_per_sec and network_bytes_out_per_sec
// per network interface. Rates are computed as delta between consecutive readings.
func CollectNetwork(ctx context.Context, interval time.Duration, out chan<- Metric) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	var prev []net.IOCountersStat
	elapsed := interval.Seconds()

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			counters, err := net.IOCountersWithContext(ctx, true) // true = per interface
			if err != nil {
				log.Printf("warn [network]: collection failed: %v", err)
				continue
			}

			if prev != nil {
				now := t.UTC()
				prevMap := make(map[string]net.IOCountersStat, len(prev))
				for _, p := range prev {
					prevMap[p.Name] = p
				}
				for _, curr := range counters {
					p, ok := prevMap[curr.Name]
					if !ok {
						continue
					}
					inRate := float64(curr.BytesRecv-p.BytesRecv) / elapsed
					outRate := float64(curr.BytesSent-p.BytesSent) / elapsed
					if inRate < 0 {
						inRate = 0
					}
					if outRate < 0 {
						outRate = 0
					}
					tags := map[string]string{"interface": curr.Name}
					out <- Metric{Name: "network_bytes_in_per_sec", Value: inRate, Timestamp: now, Tags: tags}
					out <- Metric{Name: "network_bytes_out_per_sec", Value: outRate, Timestamp: now, Tags: tags}
				}
			}
			prev = counters
		}
	}
}
