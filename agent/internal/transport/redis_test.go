package transport

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

// The Redis backend writes what 0.3.x wrote. Run against a real Redis when MAESTRO_TEST_REDIS_ADDR is
// set (for example the compose one: localhost:16379); skipped otherwise.
func testRedis(t *testing.T) (*redisBackend, *redis.Client) {
	t.Helper()
	addr := os.Getenv("MAESTRO_TEST_REDIS_ADDR")
	if addr == "" {
		t.Skip("MAESTRO_TEST_REDIS_ADDR not set")
	}
	prefix := "maestro-test:" + NewID() + ":"
	b, err := newRedisBackend("srv-test", RedisOptions{
		Addr:            addr,
		MetricsStream:   prefix + "metrics",
		LogsStream:      prefix + "logs",
		HeartbeatStream: prefix + "heartbeat",
	})
	if err != nil {
		t.Fatal(err)
	}
	client := redis.NewClient(&redis.Options{Addr: addr})
	t.Cleanup(func() {
		ctx := context.Background()
		client.Del(ctx, prefix+"metrics", prefix+"logs", prefix+"heartbeat")
		client.HDel(ctx, redisPackagesKey, "srv-test")
		client.HDel(ctx, redisDBSnapshotKey, "srv-test:postgres")
		client.Close()
	})
	return b, client
}

func TestRedisWritesTheSameEntriesAsBeforeWithMsgID(t *testing.T) {
	b, client := testRedis(t)
	defer b.close()
	ctx := context.Background()

	metrics := newMessage(TypeMetrics, []collector.Metric{{Name: "a"}, {Name: "b"}})
	b.send(metrics)
	b.send(newMessage(TypeLogs, LogBatch{File: "syslog", Lines: []LogLine{{Timestamp: time.Now(), Line: "x"}}}))
	b.send(newMessage(TypeHeartbeat, map[string]string{"server_id": "srv-test"}))
	b.send(newMessage(EventPackages, map[string]string{"server_id": "srv-test"}))
	b.send(newMessage(EventDBConnections, DBSnapshot{DBType: "postgres", Connections: []collector.DBConnection{}}))
	b.send(newMessage(EventAgentRegistered, Registration{}))

	entries, err := client.XRange(ctx, b.opts.MetricsStream, "-", "+").Result()
	if err != nil || len(entries) != 2 {
		t.Fatalf("expected one entry per metric, got %d (%v)", len(entries), err)
	}
	if entries[0].Values["msg_id"] != metrics.ID || entries[0].Values["data"] == nil {
		t.Errorf("unexpected metric entry %v", entries[0].Values)
	}

	logs, _ := client.XRange(ctx, b.opts.LogsStream, "-", "+").Result()
	if len(logs) != 1 || logs[0].Values["log_file"] != "syslog" || logs[0].Values["server_id"] != "srv-test" {
		t.Errorf("unexpected log entries %v", logs)
	}
	if n, _ := client.XLen(ctx, b.opts.HeartbeatStream).Result(); n != 1 {
		t.Errorf("expected 1 heartbeat, got %d", n)
	}
	if ok, _ := client.HExists(ctx, redisPackagesKey, "srv-test").Result(); !ok {
		t.Error("package snapshot missing")
	}
	if ok, _ := client.HExists(ctx, redisDBSnapshotKey, "srv-test:postgres").Result(); !ok {
		t.Error("db snapshot missing")
	}
}
