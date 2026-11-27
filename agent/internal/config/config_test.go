package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/yuriPeixoto/maestro/agent/internal/transport"
)

func writeConfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "agent.yaml")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestDefaultTransportIsRedis(t *testing.T) {
	cfg, err := load(writeConfig(t, "server_id: web-1\n"))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Transport != transport.ModeRedis {
		t.Fatalf("expected redis until 0.4.0, got %s", cfg.Transport)
	}
	if cfg.NATS.BufferMaxMB != 256 || cfg.NATS.NKeyFile != "/etc/maestro/nats.nk" {
		t.Errorf("unexpected NATS defaults %+v", cfg.NATS)
	}
}

func TestBothWithNATSSettings(t *testing.T) {
	cfg, err := load(writeConfig(t, `
server_id: web-1
transport: both
nats:
  url: tls://nats.example:4222
  nkey_file: /etc/maestro/nats.nk
  ca_file: /etc/maestro/nats-ca.crt
  publish_timeout: 3s
  buffer:
    dir: /tmp/buffer
    max_mb: 64
`))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Transport != transport.ModeBoth {
		t.Fatalf("expected both, got %s", cfg.Transport)
	}
	n := cfg.NATS
	if n.URL != "tls://nats.example:4222" || n.CAFile != "/etc/maestro/nats-ca.crt" ||
		n.PublishTimeout.Seconds() != 3 || n.BufferDir != "/tmp/buffer" || n.BufferMaxMB != 64 {
		t.Errorf("unexpected NATS config %+v", n)
	}
}

func TestEnvOverridesTransport(t *testing.T) {
	t.Setenv("MAESTRO_TRANSPORT", "nats")
	t.Setenv("MAESTRO_NATS_URL", "nats://localhost:14222")
	cfg, err := load(writeConfig(t, "server_id: web-1\ntransport: redis\n"))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.Transport != transport.ModeNATS || cfg.NATS.URL != "nats://localhost:14222" {
		t.Fatalf("env must win, got %s %s", cfg.Transport, cfg.NATS.URL)
	}
}

func TestInvalidConfigurations(t *testing.T) {
	cases := map[string]string{
		"unknown transport":          "server_id: web-1\ntransport: ambos\n",
		"nats without url":           "server_id: web-1\ntransport: nats\n",
		"server id not a NATS token": "server_id: Web.1\ntransport: both\nnats:\n  url: nats://x:4222\n",
		"negative buffer cap":        "server_id: web-1\ntransport: nats\nnats:\n  url: nats://x:4222\n  buffer:\n    max_mb: -1\n",
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := load(writeConfig(t, body)); err == nil {
				t.Fatal("expected an error")
			}
		})
	}
}

func TestNATSModeNeedsNoRedis(t *testing.T) {
	t.Setenv("MAESTRO_REDIS_ADDR", "")
	cfg := defaults()
	cfg.ServerID = "web-1"
	cfg.Transport = transport.ModeNATS
	cfg.Redis.Addr = ""
	cfg.NATS.URL = "nats://x:4222"
	if err := validate(cfg); err != nil {
		t.Fatalf("nats mode must not require redis: %v", err)
	}
	cfg.Transport = transport.ModeBoth
	if err := validate(cfg); err == nil || !strings.Contains(err.Error(), "redis.addr") {
		t.Fatalf("both needs redis.addr, got %v", err)
	}
}
