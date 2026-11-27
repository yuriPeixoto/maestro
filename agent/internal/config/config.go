package config

import (
	"fmt"
	"log"
	"os"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/yuriPeixoto/maestro/agent/internal/transport"
)

// Config holds all agent configuration.
type Config struct {
	ServerID   string
	Transport  transport.Mode
	Redis      RedisConfig
	NATS       NATSConfig
	API        APIConfig
	Tags       []string
	Intervals  IntervalConfig
	Buffer     BufferConfig
	Heartbeat  HeartbeatConfig
	LogWatcher LogWatcherConfig
	DBMonitor  []DBMonitorConfig
	Debug      bool
}

// APIConfig holds settings for communicating with the Maestro API.
type APIConfig struct {
	// URL is the base URL of the Maestro API (e.g. http://localhost:8000).
	// Leave empty to disable agent registration.
	URL             string
	RegisterTimeout time.Duration
}

type RedisConfig struct {
	Addr     string
	Password string
	Stream   string
}

// NATSConfig holds the NATS JetStream transport settings (ADR-015).
type NATSConfig struct {
	URL      string
	NKeyFile string
	// CAFile verifies the server's certificate; empty connects without TLS (local development).
	CAFile         string
	PublishTimeout time.Duration
	BufferDir      string
	BufferMaxMB    int
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

// DBMonitorConfig holds settings for a single database connection to monitor.
// Opt-in: the collector only runs if at least one entry is present in Config.DBMonitor.
type DBMonitorConfig struct {
	// DBType is "mysql", "mariadb", "postgres", or "clickhouse".
	DBType string
	// DSN is the data source name in the driver's native format.
	// MySQL/MariaDB: "monitor:pass@tcp(localhost:3306)/"
	// PostgreSQL:    "postgres://monitor:pass@localhost:5432/postgres?sslmode=disable"
	// ClickHouse:    "http://monitor:pass@localhost:8123/maestro"
	DSN                         string
	SamplingInterval            time.Duration
	LongRunningThresholdSeconds int
	// AllowedUsers is a whitelist for anomaly detection. Connections from
	// users not in this list emit MetricDBUnexpectedUserAccess.
	// An empty list disables this check.
	AllowedUsers []string
}

// yamlFile mirrors Config with YAML tags. Uses string durations (e.g. "30s")
// since time.Duration doesn't unmarshal from YAML natively.
type yamlFile struct {
	ServerID  string   `yaml:"server_id"`
	Transport string   `yaml:"transport"`
	Debug     bool     `yaml:"debug"`
	Tags      []string `yaml:"tags"`

	NATS struct {
		URL            string `yaml:"url"`
		NKeyFile       string `yaml:"nkey_file"`
		CAFile         string `yaml:"ca_file"`
		PublishTimeout string `yaml:"publish_timeout"`
		Buffer         struct {
			Dir   string `yaml:"dir"`
			MaxMB int    `yaml:"max_mb"`
		} `yaml:"buffer"`
	} `yaml:"nats"`

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

	API struct {
		URL             string `yaml:"url"`
		RegisterTimeout string `yaml:"register_timeout"`
	} `yaml:"api"`

	DBMonitor []struct {
		DBType                      string   `yaml:"db_type"`
		DSN                         string   `yaml:"dsn"`
		SamplingInterval            string   `yaml:"sampling_interval"`
		LongRunningThresholdSeconds int      `yaml:"long_running_threshold_seconds"`
		AllowedUsers                []string `yaml:"allowed_users"`
	} `yaml:"db_monitor"`
}

// Load reads the YAML config file at path (if it exists), then overlays
// environment variables on top (env takes precedence). Validates on return.
func Load(path string) Config {
	cfg, err := load(path)
	if err != nil {
		log.Fatalf("fatal: %v", err)
	}
	return cfg
}

func load(path string) (Config, error) {
	cfg := defaults()

	if data, err := os.ReadFile(path); err == nil {
		var f yamlFile
		if err := yaml.Unmarshal(data, &f); err != nil {
			return Config{}, fmt.Errorf("invalid config file %s: %w", path, err)
		}
		if err := applyYAML(&cfg, f); err != nil {
			return Config{}, fmt.Errorf("invalid config file %s: %w", path, err)
		}
		log.Printf("info: loaded config from %s", path)
	} else if !os.IsNotExist(err) {
		return Config{}, fmt.Errorf("cannot read config file %s: %w", path, err)
	}

	if err := applyEnv(&cfg); err != nil {
		return Config{}, fmt.Errorf("invalid environment: %w", err)
	}

	if err := validate(cfg); err != nil {
		return Config{}, fmt.Errorf("invalid configuration: %w", err)
	}

	return cfg, nil
}

func defaults() Config {
	hostname, _ := os.Hostname()
	return Config{
		ServerID:  hostname,
		Transport: transport.ModeRedis,
		Debug:     false,
		Tags:      []string{},
		API: APIConfig{
			URL:             "",
			RegisterTimeout: 5 * time.Second,
		},
		Redis: RedisConfig{
			Addr:   "localhost:6379",
			Stream: "maestro:metrics",
		},
		NATS: NATSConfig{
			NKeyFile:       "/etc/maestro/nats.nk",
			PublishTimeout: 5 * time.Second,
			BufferDir:      "/var/lib/maestro/agent/buffer",
			BufferMaxMB:    256,
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

func applyYAML(cfg *Config, f yamlFile) error {
	if f.ServerID != "" {
		cfg.ServerID = f.ServerID
	}
	if f.Transport != "" {
		mode, err := transport.ParseMode(f.Transport)
		if err != nil {
			return err
		}
		cfg.Transport = mode
	}
	applyNATSYAML(&cfg.NATS, f)
	if f.Debug {
		cfg.Debug = true
	}
	if len(f.Tags) > 0 {
		cfg.Tags = f.Tags
	}
	if f.API.URL != "" {
		cfg.API.URL = f.API.URL
	}
	if d := parseDuration(f.API.RegisterTimeout, "api.register_timeout"); d > 0 {
		cfg.API.RegisterTimeout = d
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

	for _, entry := range f.DBMonitor {
		if entry.DBType == "" || entry.DSN == "" {
			continue
		}
		d := DBMonitorConfig{
			DBType:                      entry.DBType,
			DSN:                         entry.DSN,
			LongRunningThresholdSeconds: entry.LongRunningThresholdSeconds,
			AllowedUsers:                entry.AllowedUsers,
		}
		if v := parseDuration(entry.SamplingInterval, "db_monitor.sampling_interval"); v > 0 {
			d.SamplingInterval = v
		} else {
			d.SamplingInterval = 30 * time.Second
		}
		cfg.DBMonitor = append(cfg.DBMonitor, d)
	}
	return nil
}

func applyNATSYAML(n *NATSConfig, f yamlFile) {
	if f.NATS.URL != "" {
		n.URL = f.NATS.URL
	}
	if f.NATS.NKeyFile != "" {
		n.NKeyFile = f.NATS.NKeyFile
	}
	if f.NATS.CAFile != "" {
		n.CAFile = f.NATS.CAFile
	}
	if d := parseDuration(f.NATS.PublishTimeout, "nats.publish_timeout"); d > 0 {
		n.PublishTimeout = d
	}
	if f.NATS.Buffer.Dir != "" {
		n.BufferDir = f.NATS.Buffer.Dir
	}
	if f.NATS.Buffer.MaxMB != 0 {
		n.BufferMaxMB = f.NATS.Buffer.MaxMB
	}
}

func applyEnv(cfg *Config) error {
	if v := os.Getenv("MAESTRO_SERVER_ID"); v != "" {
		cfg.ServerID = v
	}
	if v := os.Getenv("MAESTRO_TRANSPORT"); v != "" {
		mode, err := transport.ParseMode(v)
		if err != nil {
			return fmt.Errorf("MAESTRO_TRANSPORT: %w", err)
		}
		cfg.Transport = mode
	}
	if v := os.Getenv("MAESTRO_NATS_URL"); v != "" {
		cfg.NATS.URL = v
	}
	if v := os.Getenv("MAESTRO_NATS_NKEY_FILE"); v != "" {
		cfg.NATS.NKeyFile = v
	}
	if v := os.Getenv("MAESTRO_NATS_CA_FILE"); v != "" {
		cfg.NATS.CAFile = v
	}
	if v := os.Getenv("MAESTRO_NATS_BUFFER_DIR"); v != "" {
		cfg.NATS.BufferDir = v
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
	if v := os.Getenv("MAESTRO_API_URL"); v != "" {
		cfg.API.URL = v
	}
	if d := parseDuration(os.Getenv("MAESTRO_SHUTDOWN_TIMEOUT"), "MAESTRO_SHUTDOWN_TIMEOUT"); d > 0 {
		cfg.Buffer.ShutdownTimeout = d
	}
	return nil
}

func validate(cfg Config) error {
	if cfg.ServerID == "" {
		return fmt.Errorf("server_id is required (set MAESTRO_SERVER_ID or server_id in config file)")
	}
	if cfg.Transport.UsesRedis() && cfg.Redis.Addr == "" {
		return fmt.Errorf("redis.addr is required with transport %s", cfg.Transport)
	}
	if cfg.Transport.UsesNATS() {
		if err := validateNATS(cfg); err != nil {
			return err
		}
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

func validateNATS(cfg Config) error {
	if !transport.ValidServerID(cfg.ServerID) {
		return fmt.Errorf("server_id %q must be lowercase letters, digits, - or _ to be a NATS subject token (ADR-015)", cfg.ServerID)
	}
	if cfg.NATS.URL == "" {
		return fmt.Errorf("nats.url is required with transport %s", cfg.Transport)
	}
	if cfg.NATS.NKeyFile == "" {
		return fmt.Errorf("nats.nkey_file is required with transport %s", cfg.Transport)
	}
	if cfg.NATS.BufferDir == "" {
		return fmt.Errorf("nats.buffer.dir is required with transport %s", cfg.Transport)
	}
	if cfg.NATS.BufferMaxMB < 1 {
		return fmt.Errorf("nats.buffer.max_mb must be >= 1, got %d", cfg.NATS.BufferMaxMB)
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
