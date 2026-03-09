package config

import (
	"os"
	"time"
)

// Config holds all agent configuration. Values come from environment variables,
// with sensible defaults so the agent works out of the box for local development.
type Config struct {
	ServerID  string
	Redis     RedisConfig
	Intervals IntervalConfig
	Buffer    BufferConfig
	// Debug prints metrics to stdout instead of Redis. Set MAESTRO_DEBUG=true.
	Debug bool
}

// BufferConfig controls the in-memory ring buffer used when Redis is unavailable.
type BufferConfig struct {
	// Capacity is the maximum number of metric batches the ring buffer holds.
	// When full, the oldest batch is evicted. Default: 1000.
	Capacity int
	// RetryInterval is how often the publisher attempts to flush the buffer to Redis.
	RetryInterval time.Duration
}

type RedisConfig struct {
	Addr     string
	Password string
	Stream   string
}

// IntervalConfig defines per-metric sampling rates.
// Each metric is collected on its own independent ticker.
type IntervalConfig struct {
	CPU          time.Duration
	Memory       time.Duration
	DiskIO       time.Duration
	DiskSpace    time.Duration
	Network      time.Duration
	ProcessCount time.Duration
}

// Default returns a Config populated from environment variables,
// falling back to sensible defaults for local development.
func Default() Config {
	serverID := os.Getenv("MAESTRO_SERVER_ID")
	if serverID == "" {
		hostname, _ := os.Hostname()
		serverID = hostname
	}

	redisAddr := os.Getenv("MAESTRO_REDIS_ADDR")
	if redisAddr == "" {
		redisAddr = "localhost:6379"
	}

	stream := os.Getenv("MAESTRO_REDIS_STREAM")
	if stream == "" {
		stream = "maestro:metrics"
	}

	return Config{
		ServerID: serverID,
		Debug:    os.Getenv("MAESTRO_DEBUG") == "true",
		Redis: RedisConfig{
			Addr:     redisAddr,
			Password: os.Getenv("MAESTRO_REDIS_PASSWORD"),
			Stream:   stream,
		},
		Buffer: BufferConfig{
			Capacity:      1000,
			RetryInterval: 30 * time.Second,
		},
		Intervals: IntervalConfig{
			CPU:          5 * time.Second,
			Memory:       15 * time.Second,
			DiskIO:       5 * time.Second,
			DiskSpace:    60 * time.Second,
			Network:      5 * time.Second,
			ProcessCount: 30 * time.Second,
		},
	}
}
