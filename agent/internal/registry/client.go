package registry

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"runtime"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/heartbeat"
	"github.com/yuriPeixoto/maestro/agent/internal/transport"
)

// EventSink receives the registration events (transport.Sink in the agent).
type EventSink interface {
	Event(eventType string, payload any)
}

// Announce registers the agent over NATS: an agent_registered event on the server's own events subject.
// The server's NATS credential is the machine authentication, so no API token is involved. The event
// goes through the transport's disk queue and arrives even if NATS is down at startup.
func Announce(sink EventSink, cfg config.Config) {
	sink.Event(transport.EventAgentRegistered, registration(cfg))
	log.Printf("info [registry]: registration queued on NATS as server_id=%s (version=%s)", cfg.ServerID, heartbeat.Version)
}

// Retire is Announce's counterpart on a clean shutdown.
func Retire(sink EventSink, cfg config.Config) {
	sink.Event(transport.EventAgentDeregistered, registration(cfg))
}

func registration(cfg config.Config) transport.Registration {
	tags := cfg.Tags
	if tags == nil {
		tags = []string{}
	}
	host, err := os.Hostname()
	if err != nil || host == "" {
		host = cfg.ServerID
	}
	return transport.Registration{
		Hostname:     host,
		OS:           runtime.GOOS,
		Tags:         tags,
		AgentVersion: heartbeat.Version,
	}
}

type registerPayload struct {
	ServerID     string   `json:"server_id"`
	Hostname     string   `json:"hostname"`
	OS           string   `json:"os"`
	Tags         []string `json:"tags"`
	AgentVersion string   `json:"agent_version"`
}

// Register sends a registration request to the Maestro API (transport redis only; the route needs a
// user token the agent does not have, so it answers 401 until the agent moves to NATS, ADR-015).
// It is best-effort: failures are logged but never propagate to the caller.
// Designed to be called in a goroutine on agent startup.
func Register(cfg config.Config) {
	if cfg.API.URL == "" {
		log.Printf("info [registry]: API URL not configured — skipping registration")
		return
	}

	payload := registerPayload{
		ServerID:     cfg.ServerID,
		Hostname:     hostname(cfg),
		OS:           runtime.GOOS,
		Tags:         cfg.Tags,
		AgentVersion: heartbeat.Version,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		log.Printf("warn [registry]: marshal failed: %v", err)
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), cfg.API.RegisterTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodPost,
		cfg.API.URL+"/agents/register", bytes.NewReader(body))
	if err != nil {
		log.Printf("warn [registry]: failed to build request: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: cfg.API.RegisterTimeout + time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("warn [registry]: registration request failed: %v — agent will still run", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("warn [registry]: registration returned HTTP %d", resp.StatusCode)
		return
	}

	log.Printf("info [registry]: registered as server_id=%s (version=%s)", cfg.ServerID, heartbeat.Version)
}

// Deregister sends a deregistration request to the Maestro API on shutdown.
// Best-effort — the agent exits regardless of success.
func Deregister(cfg config.Config) {
	if cfg.API.URL == "" {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), cfg.API.RegisterTimeout)
	defer cancel()

	url := fmt.Sprintf("%s/agents/%s", cfg.API.URL, cfg.ServerID)
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, url, nil)
	if err != nil {
		log.Printf("warn [registry]: deregister request build failed: %v", err)
		return
	}

	client := &http.Client{Timeout: cfg.API.RegisterTimeout + time.Second}
	resp, err := client.Do(req)
	if err != nil {
		log.Printf("warn [registry]: deregister request failed: %v", err)
		return
	}
	defer resp.Body.Close()

	log.Printf("info [registry]: deregistered server_id=%s", cfg.ServerID)
}

func hostname(cfg config.Config) string {
	// ServerID may already be the hostname, but we want the real hostname separately.
	// config.Load() sets ServerID from hostname by default, so this is usually the same.
	return cfg.ServerID
}
