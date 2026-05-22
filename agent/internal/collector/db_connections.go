package collector

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	_ "github.com/go-sql-driver/mysql"
	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"
)

// DBConfig mirrors config.DBMonitorConfig to avoid a circular import.
type DBConfig struct {
	DBType                      string
	DSN                         string
	SamplingInterval            time.Duration
	LongRunningThresholdSeconds int
	AllowedUsers                []string
}

// DBConnection is a single connection entry in the snapshot published to Redis.
type DBConnection struct {
	User       string `json:"user"`
	Host       string `json:"host"`
	DBName     string `json:"db"`
	Command    string `json:"command"`
	State      string `json:"state"`
	ElapsedSec int    `json:"elapsed_sec"`
	Query      string `json:"query"`
	Client     string `json:"client,omitempty"`
}

const (
	dbSnapshotKey = "maestro:db_snapshots"
	maxQueryLen   = 500
)

// StartDBCollectors launches one goroutine per DBConfig entry.
// rdb is used to publish per-collection snapshots; out receives summary metrics.
func StartDBCollectors(ctx context.Context, serverID string, rdb *redis.Client, configs []DBConfig, out chan<- Metric) {
	for _, cfg := range configs {
		go runDBCollector(ctx, serverID, rdb, cfg, out)
	}
}

func runDBCollector(ctx context.Context, serverID string, rdb *redis.Client, cfg DBConfig, out chan<- Metric) {
	interval := cfg.SamplingInterval
	if interval <= 0 {
		interval = 30 * time.Second
	}

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	log.Printf("info [db_connections/%s]: monitoring started (interval=%s)", cfg.DBType, interval)

	for {
		select {
		case <-ctx.Done():
			return
		case t := <-ticker.C:
			collectDB(ctx, serverID, rdb, cfg, t, out)
		}
	}
}

func collectDB(ctx context.Context, serverID string, rdb *redis.Client, cfg DBConfig, t time.Time, out chan<- Metric) {
	var (
		conns  []DBConnection
		maxPct float64
		err    error
	)

	switch cfg.DBType {
	case "mysql", "mariadb":
		conns, maxPct, err = collectMySQL(ctx, cfg.DSN)
	case "postgres":
		conns, maxPct, err = collectPostgres(ctx, cfg.DSN)
	case "clickhouse":
		conns, err = collectClickHouseHTTP(ctx, cfg.DSN)
	default:
		log.Printf("warn [db_connections]: unsupported db_type %q — skipping", cfg.DBType)
		return
	}

	if err != nil {
		log.Printf("warn [db_connections/%s]: query failed: %v", cfg.DBType, err)
		return
	}

	// Publish snapshot to Redis for the current-state endpoint.
	if b, jerr := json.Marshal(conns); jerr == nil {
		field := serverID + ":" + cfg.DBType
		if rerr := rdb.HSet(ctx, dbSnapshotKey, field, string(b)).Err(); rerr != nil {
			log.Printf("warn [db_connections/%s]: redis hset failed: %v", cfg.DBType, rerr)
		}
	}

	emitDBMetrics(conns, serverID, cfg, maxPct, t, out)
}

func emitDBMetrics(conns []DBConnection, serverID string, cfg DBConfig, maxPct float64, t time.Time, out chan<- Metric) {
	dbType := cfg.DBType

	// Total connections (all + by state).
	out <- Metric{
		ServerID:  serverID,
		Name:      MetricDBConnectionsTotal,
		Value:     float64(len(conns)),
		Timestamp: t.UTC(),
		Tags:      map[string]string{"db_type": dbType, "state": "all"},
	}
	byState := map[string]int{}
	for _, c := range conns {
		s := c.State
		if s == "" {
			s = "unknown"
		}
		byState[s]++
	}
	for state, count := range byState {
		out <- Metric{
			ServerID:  serverID,
			Name:      MetricDBConnectionsTotal,
			Value:     float64(count),
			Timestamp: t.UTC(),
			Tags:      map[string]string{"db_type": dbType, "state": state},
		}
	}

	// Long-running connections.
	threshold := cfg.LongRunningThresholdSeconds
	if threshold <= 0 {
		threshold = 60
	}
	longRunning := 0
	for _, c := range conns {
		if c.ElapsedSec >= threshold {
			longRunning++
		}
	}
	out <- Metric{
		ServerID:  serverID,
		Name:      MetricDBConnectionsLongRunning,
		Value:     float64(longRunning),
		Timestamp: t.UTC(),
		Tags:      map[string]string{"db_type": dbType, "threshold_sec": fmt.Sprintf("%d", threshold)},
	}

	// Max connections usage percentage (MySQL / PostgreSQL).
	if maxPct > 0 {
		out <- Metric{
			ServerID:  serverID,
			Name:      MetricDBMaxConnectionsUsagePct,
			Value:     maxPct,
			Timestamp: t.UTC(),
			Tags:      map[string]string{"db_type": dbType},
		}
	}

	// Unexpected user access (allowlist-based anomaly detection).
	if len(cfg.AllowedUsers) > 0 {
		allowed := make(map[string]bool, len(cfg.AllowedUsers))
		for _, u := range cfg.AllowedUsers {
			allowed[u] = true
		}
		for _, c := range conns {
			if c.User != "" && !allowed[c.User] {
				out <- Metric{
					ServerID:  serverID,
					Name:      MetricDBUnexpectedUserAccess,
					Value:     1,
					Timestamp: t.UTC(),
					Tags:      map[string]string{"db_type": dbType, "user": c.User, "host": c.Host},
				}
			}
		}
	}
}

// ── MySQL / MariaDB ───────────────────────────────────────────────────────────

func collectMySQL(ctx context.Context, dsn string) ([]DBConnection, float64, error) {
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, 0, fmt.Errorf("open: %w", err)
	}
	defer db.Close()
	db.SetConnMaxLifetime(10 * time.Second)
	db.SetMaxOpenConns(1)

	rows, err := db.QueryContext(ctx,
		"SELECT user, host, IFNULL(db,''), command, time, IFNULL(state,''), IFNULL(info,'') FROM information_schema.PROCESSLIST")
	if err != nil {
		return nil, 0, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	var conns []DBConnection
	for rows.Next() {
		var c DBConnection
		var elapsed int
		if err := rows.Scan(&c.User, &c.Host, &c.DBName, &c.Command, &elapsed, &c.State, &c.Query); err != nil {
			continue
		}
		c.ElapsedSec = elapsed
		c.Query = truncateStr(c.Query, maxQueryLen)
		conns = append(conns, c)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}

	var current, max int
	db.QueryRowContext(ctx,
		"SELECT COUNT(*), @@max_connections FROM information_schema.PROCESSLIST LIMIT 1",
	).Scan(&current, &max)
	var pct float64
	if max > 0 {
		pct = float64(current) / float64(max) * 100
	}
	return conns, pct, nil
}

// ── PostgreSQL ────────────────────────────────────────────────────────────────

func collectPostgres(ctx context.Context, dsn string) ([]DBConnection, float64, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, 0, fmt.Errorf("open: %w", err)
	}
	defer db.Close()
	db.SetConnMaxLifetime(10 * time.Second)
	db.SetMaxOpenConns(1)

	rows, err := db.QueryContext(ctx, `
		SELECT
			COALESCE(usename,''),
			COALESCE(application_name,''),
			COALESCE(client_addr::text,''),
			COALESCE(state,''),
			EXTRACT(EPOCH FROM COALESCE(now() - query_start, interval '0'))::int,
			COALESCE(query,'')
		FROM pg_stat_activity
		WHERE pid <> pg_backend_pid()`)
	if err != nil {
		return nil, 0, fmt.Errorf("query: %w", err)
	}
	defer rows.Close()

	var conns []DBConnection
	for rows.Next() {
		var c DBConnection
		var elapsed int
		if err := rows.Scan(&c.User, &c.Command, &c.Host, &c.State, &elapsed, &c.Query); err != nil {
			continue
		}
		c.ElapsedSec = elapsed
		c.Query = truncateStr(c.Query, maxQueryLen)
		conns = append(conns, c)
	}
	if err := rows.Err(); err != nil {
		return nil, 0, err
	}

	var current, max int
	db.QueryRowContext(ctx,
		"SELECT COUNT(*), current_setting('max_connections')::int FROM pg_stat_activity",
	).Scan(&current, &max)
	var pct float64
	if max > 0 {
		pct = float64(current) / float64(max) * 100
	}
	return conns, pct, nil
}

// ── ClickHouse (HTTP interface — no extra driver dependency) ──────────────────

type chProcessRow struct {
	User           string  `json:"user"`
	ClientHostname string  `json:"client_hostname"`
	ClientName     string  `json:"client_name"`
	Elapsed        float64 `json:"elapsed"`
	Query          string  `json:"query"`
}

func collectClickHouseHTTP(ctx context.Context, dsn string) ([]DBConnection, error) {
	// DSN format: http://user:pass@host:8123/database
	u, err := url.Parse(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse dsn: %w", err)
	}

	query := "SELECT user, client_hostname, client_name, elapsed, query FROM system.processes FORMAT JSONEachRow"
	reqURL := fmt.Sprintf("%s://%s/?database=%s&query=%s",
		u.Scheme, u.Host, strings.TrimPrefix(u.Path, "/"), url.QueryEscape(query))

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, reqURL, nil)
	if err != nil {
		return nil, err
	}
	if u.User != nil {
		pass, _ := u.User.Password()
		req.SetBasicAuth(u.User.Username(), pass)
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("clickhouse http %d: %s", resp.StatusCode, body)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var conns []DBConnection
	for _, line := range strings.Split(strings.TrimSpace(string(body)), "\n") {
		if line == "" {
			continue
		}
		var row chProcessRow
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			continue
		}
		conns = append(conns, DBConnection{
			User:       row.User,
			Host:       row.ClientHostname,
			Client:     row.ClientName,
			State:      "active",
			ElapsedSec: int(row.Elapsed),
			Query:      truncateStr(row.Query, maxQueryLen),
		})
	}
	return conns, nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func truncateStr(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	return string(r[:max]) + "…"
}
