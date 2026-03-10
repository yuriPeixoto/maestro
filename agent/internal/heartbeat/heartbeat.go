package heartbeat

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/redis/go-redis/v9"
)

// Version is the current agent version, injected at build time via -ldflags.
// Falls back to "dev" when not set.
var Version = "dev"

// Payload is the heartbeat message emitted to Redis Streams.
type Payload struct {
	ServerID     string    `json:"server_id"`
	Timestamp    time.Time `json:"timestamp"`
	AgentVersion string    `json:"agent_version"`
}

// Config holds all parameters needed by the emitter.
type Config struct {
	ServerID      string
	Stream        string
	Interval      time.Duration
	RedisAddr     string
	RedisPassword string
	Debug         bool
}

// Start launches the heartbeat emitter as a goroutine.
// It connects to Redis independently from the metric publisher, emits a
// heartbeat on every tick, and logs failures without affecting metric collection.
func Start(ctx context.Context, cfg Config) error {
	if cfg.Interval <= 0 {
		cfg.Interval = 30 * time.Second
	}

	var client *redis.Client
	if !cfg.Debug {
		client = redis.NewClient(&redis.Options{
			Addr:     cfg.RedisAddr,
			Password: cfg.RedisPassword,
		})
		pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		if err := client.Ping(pingCtx).Err(); err != nil {
			return fmt.Errorf("heartbeat: redis connection failed (%s): %w", cfg.RedisAddr, err)
		}
		log.Printf("info [heartbeat]: connected to Redis at %s, stream=%s, interval=%s",
			cfg.RedisAddr, cfg.Stream, cfg.Interval)
	} else {
		log.Printf("info [heartbeat]: DEBUG mode — heartbeats will be printed to stdout")
	}

	go func() {
		if client != nil {
			defer client.Close()
		}

		ticker := time.NewTicker(cfg.Interval)
		defer ticker.Stop()

		// Emit immediately on startup so the server is visible right away.
		emit(ctx, cfg, client)

		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				emit(ctx, cfg, client)
			}
		}
	}()

	return nil
}

func emit(ctx context.Context, cfg Config, client *redis.Client) {
	p := Payload{
		ServerID:     cfg.ServerID,
		Timestamp:    time.Now().UTC(),
		AgentVersion: Version,
	}

	payload, err := json.Marshal(p)
	if err != nil {
		log.Printf("warn [heartbeat]: marshal failed: %v", err)
		return
	}

	if cfg.Debug {
		log.Printf("debug [heartbeat]: %s", string(payload))
		return
	}

	err = client.XAdd(ctx, &redis.XAddArgs{
		Stream: cfg.Stream,
		Values: map[string]any{"data": string(payload)},
	}).Err()
	if err != nil {
		log.Printf("warn [heartbeat]: XADD to stream %q failed: %v — skipping", cfg.Stream, err)
	} else {
		log.Printf("debug [heartbeat]: emitted to stream %s", cfg.Stream)
	}
}
