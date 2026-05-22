package config

import (
	"fmt"
	"log"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

// Config holds all agent configuration.
type Config struct {
	ServerID   string
	Redis      RedisConfig
	Intervals  IntervalConfig
	Buffer     BufferConfig
	Heartbeat  HeartbeatConfig
	LogWatcher LogWatcherConfig
	Debug      bool
}

type RedisConfig struct {
	Addr     string
	Password string
	Stream   string
}

type HeartbeatConfig struct {
	Interval time.Duration
	Stream   string
}

type BufferConfig struct {
	Capacity        int
	RetryInterval   time.Duration
	ShutdownTimeout time.Duration
}

type IntervalConfig struct {
	CPU          time.Duration
	Memory       time.Duration
	DiskIO       time.Duration
	DiskSpace    time.Duration
	Network      time.Duration
	ProcessCount time.Duration
}

type LogWatcherConfig struct {
	Stream string
	Paths  []string
}

// yamlFile mirrors Config with YAML tags. Uses string durations (e.g. "30s")
// since time.Duration doesn't unmarshal from YAML natively.
type yamlFile struct {
	ServerID string `yaml:"server_id"`
	Debug    bool   `yaml:"debug"`

	Redis struct {
		Addr     string `yaml:"addr"`
		Password string `yaml:"password"`
		Stream   string `yaml:"stream"`
	} `yaml:"redis"`

	Heartbeat struct {
		Interval string `yaml:"interval"`
		Stream   string `yaml:"stream"`
	} `yaml:"heartbeat"`

	Buffer struct {
		Capacity        int    `yaml:"capacity"`
		RetryInterval   string `yaml:"retry_interval"`
		ShutdownTimeout string `yaml:"shutdown_timeout"`
	} `yaml:"buffer"`

	Intervals struct {
		CPU          string `yaml:"cpu"`
		Memory       string `yaml:"memory"`
		DiskIO       string `yaml:"disk_io"`
		DiskSpace    string `yaml:"disk_space"`
		Network      string `yaml:"network"`
		ProcessCount string `yaml:"process_count"`
	} `yaml:"intervals"`

	LogWatcher struct {
		Stream string   `yaml:"stream"`
		Paths  []string `yaml:"paths"`
	} `yaml:"log_watcher"`
}

// Load reads the YAML config file at path (if it exists), then overlays
// environment variables on top (env takes precedence). Validates on return.
func Load(path string) Config {
	cfg := defaults()

	if data, err := os.ReadFile(path); err == nil {
		var f yamlFile
		if err := yaml.Unmarshal(data, &f); err != nil {
			log.Fatalf("fatal: invalid config file %s: %v", path, err)
		}
		applyYAML(&cfg, f)
		log.Printf("info: loaded config from %s", path)
	} else if !os.IsNotExist(err) {
		log.Fatalf("fatal: cannot read config file %s: %v", path, err)
	}

	applyEnv(&cfg)

	if err := validate(cfg); err != nil {
		log.Fatalf("fatal: invalid configuration: %v", err)
	}

	return cfg
}

func defaults() Config {
	hostname, _ := os.Hostname()
	return Config{
		ServerID: hostname,
		Debug:    false,
		Redis: RedisConfig{
			Addr:   "localhost:6379",
			Stream: "maestro:metrics",
		},
		Heartbeat: HeartbeatConfig{
			Interval: 30 * time.Second,
			Stream:   "maestro:heartbeat",
		},
		Buffer: BufferConfig{
			Capacity:        1000,
			RetryInterval:   30 * time.Second,
			ShutdownTimeout: 10 * time.Second,
		},
		Intervals: IntervalConfig{
			CPU:          5 * time.Second,
			Memory:       15 * time.Second,
			DiskIO:       5 * time.Second,
			DiskSpace:    60 * time.Second,
			Network:      5 * time.Second,
			ProcessCount: 30 * time.Second,
		},
		LogWatcher: LogWatcherConfig{
			Stream: "maestro:logs",
			Paths: []string{
				"/var/log/syslog",
				"/var/log/auth.log",
				"/var/log/ufw.log",
				"/var/log/nginx/access.log",
				"/var/log/nginx/error.log",
				"/var/log/redis/redis-server.log",
				"/var/log/clickhouse-server/clickhouse-server.log",
			},
		},
	}
}

func applyYAML(cfg *Config, f yamlFile) {
	if f.ServerID != "" {
		cfg.ServerID = f.ServerID
	}
	if f.Debug {
		cfg.Debug = true
	}

	if f.Redis.Addr != "" {
		cfg.Redis.Addr = f.Redis.Addr
	}
	if f.Redis.Password != "" {
		cfg.Redis.Password = f.Redis.Password
	}
	if f.Redis.Stream != "" {
		cfg.Redis.Stream = f.Redis.Stream
	}

	if f.Heartbeat.Stream != "" {
		cfg.Heartbeat.Stream = f.Heartbeat.Stream
	}
	if d := parseDuration(f.Heartbeat.Interval, "heartbeat.interval"); d > 0 {
		cfg.Heartbeat.Interval = d
	}

	if f.Buffer.Capacity > 0 {
		cfg.Buffer.Capacity = f.Buffer.Capacity
	}
	if d := parseDuration(f.Buffer.RetryInterval, "buffer.retry_interval"); d > 0 {
		cfg.Buffer.RetryInterval = d
	}
	if d := parseDuration(f.Buffer.ShutdownTimeout, "buffer.shutdown_timeout"); d > 0 {
		cfg.Buffer.ShutdownTimeout = d
	}

	if d := parseDuration(f.Intervals.CPU, "intervals.cpu"); d > 0 {
		cfg.Intervals.CPU = d
	}
	if d := parseDuration(f.Intervals.Memory, "intervals.memory"); d > 0 {
		cfg.Intervals.Memory = d
	}
	if d := parseDuration(f.Intervals.DiskIO, "intervals.disk_io"); d > 0 {
		cfg.Intervals.DiskIO = d
	}
	if d := parseDuration(f.Intervals.DiskSpace, "intervals.disk_space"); d > 0 {
		cfg.Intervals.DiskSpace = d
	}
	if d := parseDuration(f.Intervals.Network, "intervals.network"); d > 0 {
		cfg.Intervals.Network = d
	}
	if d := parseDuration(f.Intervals.ProcessCount, "intervals.process_count"); d > 0 {
		cfg.Intervals.ProcessCount = d
	}

	if f.LogWatcher.Stream != "" {
		cfg.LogWatcher.Stream = f.LogWatcher.Stream
	}
	if len(f.LogWatcher.Paths) > 0 {
		cfg.LogWatcher.Paths = f.LogWatcher.Paths
	}
}

func applyEnv(cfg *Config) {
	if v := os.Getenv("MAESTRO_SERVER_ID"); v != "" {
		cfg.ServerID = v
	}
	if os.Getenv("MAESTRO_DEBUG") == "true" {
		cfg.Debug = true
	}
	if v := os.Getenv("MAESTRO_REDIS_ADDR"); v != "" {
		cfg.Redis.Addr = v
	}
	if v := os.Getenv("MAESTRO_REDIS_PASSWORD"); v != "" {
		cfg.Redis.Password = v
	}
	if v := os.Getenv("MAESTRO_REDIS_STREAM"); v != "" {
		cfg.Redis.Stream = v
	}
	if v := os.Getenv("MAESTRO_HEARTBEAT_STREAM"); v != "" {
		cfg.Heartbeat.Stream = v
	}
	if d := parseDuration(os.Getenv("MAESTRO_HEARTBEAT_INTERVAL"), "MAESTRO_HEARTBEAT_INTERVAL"); d > 0 {
		cfg.Heartbeat.Interval = d
	}
	if v := os.Getenv("MAESTRO_LOG_STREAM"); v != "" {
		cfg.LogWatcher.Stream = v
	}
	if d := parseDuration(os.Getenv("MAESTRO_SHUTDOWN_TIMEOUT"), "MAESTRO_SHUTDOWN_TIMEOUT"); d > 0 {
		cfg.Buffer.ShutdownTimeout = d
	}
}

func validate(cfg Config) error {
	if cfg.ServerID == "" {
		return fmt.Errorf("server_id is required (set MAESTRO_SERVER_ID or server_id in config file)")
	}
	if cfg.Redis.Addr == "" {
		return fmt.Errorf("redis.addr is required")
	}
	if cfg.Buffer.Capacity < 1 {
		return fmt.Errorf("buffer.capacity must be >= 1, got %d", cfg.Buffer.Capacity)
	}
	if cfg.Buffer.ShutdownTimeout < time.Second {
		return fmt.Errorf("buffer.shutdown_timeout must be >= 1s, got %s", cfg.Buffer.ShutdownTimeout)
	}
	if cfg.Intervals.CPU < time.Second {
		return fmt.Errorf("intervals.cpu must be >= 1s, got %s", cfg.Intervals.CPU)
	}
	return nil
}

func parseDuration(s, field string) time.Duration {
	if s == "" {
		return 0
	}
	d, err := time.ParseDuration(s)
	if err != nil {
		log.Printf("warn: invalid duration %q for %s — using default", s, field)
		return 0
	}
	return d
}
