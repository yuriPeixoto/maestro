package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/publisher"
)

func main() {
	cfg := config.Default()

	log.Printf("info: Maestro Agent starting — server_id=%s debug=%v", cfg.ServerID, cfg.Debug)

	// Shared metric channel — buffered to absorb bursts across all collectors.
	metrics := make(chan collector.Metric, 200)

	// Publisher: Redis Streams (or stdout in debug mode).
	pub, err := publisher.New(publisher.Config{
		RedisAddr:     cfg.Redis.Addr,
		RedisPassword: cfg.Redis.Password,
		Stream:        cfg.Redis.Stream,
		Debug:         cfg.Debug,
		BufferCap:     cfg.Buffer.Capacity,
		RetryInterval: cfg.Buffer.RetryInterval,
	})
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}

	// Context cancelled on SIGINT / SIGTERM for graceful shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Start all metric collectors (each runs as an independent goroutine).
	collector.Start(ctx, cfg.ServerID, collector.IntervalConfig{
		CPU:          cfg.Intervals.CPU,
		Memory:       cfg.Intervals.Memory,
		DiskIO:       cfg.Intervals.DiskIO,
		DiskSpace:    cfg.Intervals.DiskSpace,
		Network:      cfg.Intervals.Network,
		ProcessCount: cfg.Intervals.ProcessCount,
	}, metrics)

	// Publisher blocks until ctx is cancelled.
	pub.Run(ctx, metrics)

	log.Printf("info: Maestro Agent stopped.")
}
