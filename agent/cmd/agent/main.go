package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/heartbeat"
	"github.com/yuriPeixoto/maestro/agent/internal/inventory"
	"github.com/yuriPeixoto/maestro/agent/internal/logwatcher"
	"github.com/yuriPeixoto/maestro/agent/internal/packages"
	"github.com/yuriPeixoto/maestro/agent/internal/publisher"
	"github.com/yuriPeixoto/maestro/agent/internal/registry"
	"github.com/yuriPeixoto/maestro/agent/internal/transport"
)

func main() {
	configPath := flag.String("config", "/etc/maestro/agent.yaml", "path to YAML config file")
	flag.Parse()

	cfg := config.Load(*configPath)

	log.Printf("info: Maestro Agent starting — server_id=%s transport=%s debug=%v", cfg.ServerID, cfg.Transport, cfg.Debug)

	// Shared metric channel — buffered to absorb bursts across all collectors.
	metrics := make(chan collector.Metric, 200)

	// Transport: Redis Streams, NATS JetStream or both (or stdout in debug mode).
	sink, err := transport.Open(transportOptions(cfg))
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}

	// Context cancelled on SIGINT / SIGTERM for graceful shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	registerAgent(cfg, sink)

	// Inventory — detect installed runtimes and service statuses once at startup.
	log.Printf("info: collecting runtime inventory...")
	inv := inventory.Collect(ctx)
	log.Printf("info: inventory collected — %d entries", len(inv))

	// OS package reporter — feeds the API's advisory scan. No-op on unsupported distributions.
	packages.Start(ctx, packages.Config{ServerID: cfg.ServerID}, sink)

	// Log watcher — tails configured files and hands new lines to the transport.
	watchedLogs := logwatcher.Start(ctx, cfg.LogWatcher.Paths, sink)

	// Heartbeat emitter — runs independently, failures never affect metric collection.
	heartbeat.Start(ctx, heartbeat.Config{
		ServerID:         cfg.ServerID,
		Interval:         cfg.Heartbeat.Interval,
		WatchedLogs:      watchedLogs,
		InitialInventory: inv,
	}, sink)

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
		startDBMonitors(ctx, cfg, sink, metrics)
	}

	// Batches metrics until ctx is cancelled, then flushes the last batch.
	publisher.Run(ctx, metrics, sink)

	deregisterAgent(cfg, sink)

	// Flushes the transports: Redis drains its ring, NATS what it can of the disk queue.
	sink.Close()

	log.Printf("info: Maestro Agent stopped.")
}

func transportOptions(cfg config.Config) transport.Options {
	return transport.Options{
		ServerID: cfg.ServerID,
		Mode:     cfg.Transport,
		Debug:    cfg.Debug,
		Redis: transport.RedisOptions{
			Addr:            cfg.Redis.Addr,
			Password:        cfg.Redis.Password,
			MetricsStream:   cfg.Redis.Stream,
			LogsStream:      cfg.LogWatcher.Stream,
			HeartbeatStream: cfg.Heartbeat.Stream,
			BufferCap:       cfg.Buffer.Capacity,
			RetryInterval:   cfg.Buffer.RetryInterval,
			ShutdownTimeout: cfg.Buffer.ShutdownTimeout,
		},
		NATS: transport.NATSOptions{
			URL:             cfg.NATS.URL,
			NKeyFile:        cfg.NATS.NKeyFile,
			CAFile:          cfg.NATS.CAFile,
			PublishTimeout:  cfg.NATS.PublishTimeout,
			BufferDir:       cfg.NATS.BufferDir,
			BufferMaxMB:     cfg.NATS.BufferMaxMB,
			RetryInterval:   cfg.Buffer.RetryInterval,
			ShutdownTimeout: cfg.Buffer.ShutdownTimeout,
		},
	}
}

// registerAgent registers over NATS when the transport has it (the server's credential authenticates
// the machine), and otherwise over HTTP as before, in the background, never blocking startup.
func registerAgent(cfg config.Config, sink transport.Sink) {
	if cfg.Transport.UsesNATS() || cfg.Debug {
		registry.Announce(sink, cfg)
		return
	}
	go registry.Register(cfg)
}

func deregisterAgent(cfg config.Config, sink transport.Sink) {
	if cfg.Transport.UsesNATS() || cfg.Debug {
		registry.Retire(sink, cfg)
		return
	}
	registry.Deregister(cfg)
}

func startDBMonitors(ctx context.Context, cfg config.Config, sink transport.Sink, metrics chan<- collector.Metric) {
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
	snapshot := func(dbType string, conns []collector.DBConnection) {
		sink.Event(transport.EventDBConnections, transport.DBSnapshot{DBType: dbType, Connections: conns})
	}
	collector.StartDBCollectors(ctx, cfg.ServerID, snapshot, dbConfigs, metrics)
	log.Printf("info: DB connection pool monitoring started — %d database(s)", len(dbConfigs))
}
