package heartbeat

import (
	"context"
	"log"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/inventory"
)

// Version is the current agent version, injected at build time via -ldflags.
// Falls back to "dev" when not set.
var Version = "dev"

// Payload is the heartbeat message.
type Payload struct {
	ServerID     string            `json:"server_id"`
	Timestamp    time.Time         `json:"timestamp"`
	AgentVersion string            `json:"agent_version"`
	WatchedLogs  []string          `json:"watched_logs,omitempty"`
	Inventory    []inventory.Entry `json:"inventory,omitempty"`
}

// Sink receives the heartbeats (transport.Sink in the agent).
type Sink interface {
	Heartbeat(payload any)
}

// Config holds all parameters needed by the emitter.
type Config struct {
	ServerID         string
	Interval         time.Duration
	WatchedLogs      []string
	InitialInventory []inventory.Entry
}

// Start launches the heartbeat emitter as a goroutine. It emits right away and then on every tick;
// a failed heartbeat is the transport's to log and never affects metric collection.
func Start(ctx context.Context, cfg Config, sink Sink) {
	if cfg.Interval <= 0 {
		cfg.Interval = 30 * time.Second
	}
	log.Printf("info [heartbeat]: interval=%s", cfg.Interval)

	go func() {
		ticker := time.NewTicker(cfg.Interval)
		defer ticker.Stop()

		cachedInventory := cfg.InitialInventory

		// Emit immediately on startup so the server is visible right away.
		sink.Heartbeat(newPayload(cfg, cachedInventory))

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				cachedInventory = inventory.RefreshStatus(ctx, cachedInventory)
				sink.Heartbeat(newPayload(cfg, cachedInventory))
			}
		}
	}()
}

func newPayload(cfg Config, inv []inventory.Entry) Payload {
	return Payload{
		ServerID:     cfg.ServerID,
		Timestamp:    time.Now().UTC(),
		AgentVersion: Version,
		WatchedLogs:  cfg.WatchedLogs,
		Inventory:    inv,
	}
}
