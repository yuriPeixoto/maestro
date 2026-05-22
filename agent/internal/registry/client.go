package registry

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"runtime"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/config"
	"github.com/yuriPeixoto/maestro/agent/internal/heartbeat"
)

type registerPayload struct {
	ServerID     string   `json:"server_id"`
	Hostname     string   `json:"hostname"`
	OS           string   `json:"os"`
	Tags         []string `json:"tags"`
	AgentVersion string   `json:"agent_version"`
}

// Register sends a registration request to the Maestro API.
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
