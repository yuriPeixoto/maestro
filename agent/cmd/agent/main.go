package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/heartbeat"
	"github.com/yuriPeixoto/maestro/agent/internal/inventory"
	"github.com/yuriPeixoto/maestro/agent/internal/logwatcher"
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

	// Inventory — detect installed runtimes and service statuses once at startup.
	log.Printf("info: collecting runtime inventory...")
	inv := inventory.Collect(ctx)
	log.Printf("info: inventory collected — %d entries", len(inv))

	// Log watcher — tails configured files and emits lines to Redis Streams.
	// Returns the subset of paths that actually exist (passed to heartbeat).
	watchedLogs := logwatcher.Start(ctx, logwatcher.Config{
		ServerID:      cfg.ServerID,
		Stream:        cfg.LogWatcher.Stream,
		Paths:         cfg.LogWatcher.Paths,
		RedisAddr:     cfg.Redis.Addr,
		RedisPassword: cfg.Redis.Password,
		Debug:         cfg.Debug,
	})

	// Heartbeat emitter — runs independently, failures never affect metric collection.
	if err := heartbeat.Start(ctx, heartbeat.Config{
		ServerID:         cfg.ServerID,
		Stream:           cfg.Heartbeat.Stream,
		Interval:         cfg.Heartbeat.Interval,
		RedisAddr:        cfg.Redis.Addr,
		RedisPassword:    cfg.Redis.Password,
		WatchedLogs:      watchedLogs,
		InitialInventory: inv,
		Debug:            cfg.Debug,
	}); err != nil {
		log.Printf("warn: heartbeat emitter failed to start: %v — continuing without heartbeat", err)
	}

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
