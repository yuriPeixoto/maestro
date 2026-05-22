package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/redis/go-redis/v9"
	"github.com/yuriPeixoto/maestro/agent/internal/collector"
	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/heartbeat"
	"github.com/yuriPeixoto/maestro/agent/internal/inventory"
	"github.com/yuriPeixoto/maestro/agent/internal/logwatcher"
	"github.com/yuriPeixoto/maestro/agent/internal/publisher"
	"github.com/yuriPeixoto/maestro/agent/internal/registry"
)

func main() {
	configPath := flag.String("config", "/etc/maestro/agent.yaml", "path to YAML config file")
	flag.Parse()

	cfg := config.Load(*configPath)

	log.Printf("info: Maestro Agent starting — server_id=%s debug=%v", cfg.ServerID, cfg.Debug)

	// Shared metric channel — buffered to absorb bursts across all collectors.
	metrics := make(chan collector.Metric, 200)

	// Publisher: Redis Streams (or stdout in debug mode).
	pub, err := publisher.New(publisher.Config{
		RedisAddr:       cfg.Redis.Addr,
		RedisPassword:   cfg.Redis.Password,
		Stream:          cfg.Redis.Stream,
		Debug:           cfg.Debug,
		BufferCap:       cfg.Buffer.Capacity,
		RetryInterval:   cfg.Buffer.RetryInterval,
		ShutdownTimeout: cfg.Buffer.ShutdownTimeout,
	})
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}

	// Context cancelled on SIGINT / SIGTERM for graceful shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// Register with the API in the background — never blocks startup.
	go registry.Register(cfg)

	// Inventory — detect installed runtimes and service statuses once at startup.
	log.Printf("info: collecting runtime inventory...")
	inv := inventory.Collect(ctx)
	log.Printf("info: inventory collected — %d entries", len(inv))

	// Log watcher — tails configured files and emits lines to Redis Streams.
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

	// DB connection pool collectors — opt-in, only started when db_monitor is configured.
	if len(cfg.DBMonitor) > 0 {
		rdb := redis.NewClient(&redis.Options{
			Addr:     cfg.Redis.Addr,
			Password: cfg.Redis.Password,
		})
		dbConfigs := make([]collector.DBConfig, len(cfg.DBMonitor))
		for i, m := range cfg.DBMonitor {
			dbConfigs[i] = collector.DBConfig{
				DBType:                      m.DBType,
				DSN:                         m.DSN,
				SamplingInterval:            m.SamplingInterval,
				LongRunningThresholdSeconds: m.LongRunningThresholdSeconds,
				AllowedUsers:                m.AllowedUsers,
			}
		}
		collector.StartDBCollectors(ctx, cfg.ServerID, rdb, dbConfigs, metrics)
		log.Printf("info: DB connection pool monitoring started — %d database(s)", len(dbConfigs))
	}

	// Publisher blocks until ctx is cancelled, then flushes ring buffer before returning.
	pub.Run(ctx, metrics)

	// Deregister from the API on clean shutdown (best-effort).
	registry.Deregister(cfg)

	log.Printf("info: Maestro Agent stopped.")
}
