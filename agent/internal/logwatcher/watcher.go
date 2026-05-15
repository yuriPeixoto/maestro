package logwatcher

import (
	"bufio"
	"context"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

const pollInterval = time.Second

// Config holds parameters for the log watcher.
type Config struct {
	ServerID      string
	Stream        string
	Paths         []string
	RedisAddr     string
	RedisPassword string
	Debug         bool
}

// Start launches one goroutine per log file and returns the list of paths that
// actually exist on disk. Files that do not exist are skipped silently.
func Start(ctx context.Context, cfg Config) []string {
	var client *redis.Client
	if !cfg.Debug {
		client = redis.NewClient(&redis.Options{
			Addr:     cfg.RedisAddr,
			Password: cfg.RedisPassword,
		})
		pingCtx, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		if err := client.Ping(pingCtx).Err(); err != nil {
			log.Printf("warn [logwatcher]: redis connection failed: %v — log streaming disabled", err)
			return nil
		}
	}

	var watching []string
	for _, path := range cfg.Paths {
		if _, err := os.Stat(path); err != nil {
			continue // skip missing files silently
		}
		watching = append(watching, path)
		go watch(ctx, client, cfg, path)
	}

	if len(watching) > 0 {
		log.Printf("info [logwatcher]: watching %d file(s): %s", len(watching), strings.Join(watching, ", "))
	}
	return watching
}

// watch tails a single file, emitting new lines to Redis as they appear.
// It handles log rotation by detecting when the file shrinks.
func watch(ctx context.Context, client *redis.Client, cfg Config, path string) {
	logName := logName(path)

	f, offset, err := openAtEnd(path)
	if err != nil {
		log.Printf("warn [logwatcher]: cannot open %s: %v", path, err)
		return
	}
	defer f.Close()

	reader := bufio.NewReader(f)
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			fi, err := os.Stat(path)
			if err != nil {
				// File disappeared; wait and retry on the next tick.
				continue
			}

			// Detect rotation: file shrank below our last offset.
			if fi.Size() < offset {
				f.Close()
				f, err = os.Open(path)
				if err != nil {
					continue
				}
				reader.Reset(f)
				offset = 0
			}

			lines, newOffset := readNewLines(reader, offset)
			offset = newOffset

			for _, line := range lines {
				if line == "" {
					continue
				}
				emit(ctx, client, cfg, logName, line)
			}
		}
	}
}

// openAtEnd opens a file and seeks to the end so only future lines are tailed.
func openAtEnd(path string) (*os.File, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, 0, err
	}
	offset, err := f.Seek(0, io.SeekEnd)
	if err != nil {
		f.Close()
		return nil, 0, err
	}
	return f, offset, nil
}

// readNewLines reads all complete lines available from the reader and returns
// them along with the new absolute byte offset.
func readNewLines(reader *bufio.Reader, offset int64) ([]string, int64) {
	var lines []string
	for {
		line, err := reader.ReadString('\n')
		if len(line) > 0 {
			offset += int64(len(line))
			lines = append(lines, strings.TrimRight(line, "\n\r"))
		}
		if err != nil {
			break
		}
	}
	return lines, offset
}

// emit sends a single log line to Redis Streams (or stdout in debug mode).
func emit(ctx context.Context, client *redis.Client, cfg Config, logName, line string) {
	ts := time.Now().UTC().Format(time.RFC3339Nano)

	if cfg.Debug {
		log.Printf("debug [logwatcher] %s %s: %s", logName, ts, line)
		return
	}

	err := client.XAdd(ctx, &redis.XAddArgs{
		Stream: cfg.Stream,
		Values: map[string]any{
			"server_id": cfg.ServerID,
			"log_file":  logName,
			"timestamp": ts,
			"line":      line,
		},
	}).Err()
	if err != nil {
		log.Printf("warn [logwatcher]: XADD failed for %s: %v", logName, err)
	}
}

// logName derives a short, human-readable identifier from a full path.
// /var/log/nginx/access.log → nginx/access.log
// /var/log/syslog           → syslog
func logName(path string) string {
	const base = "/var/log/"
	if strings.HasPrefix(path, base) {
		return strings.TrimPrefix(path, base)
	}
	return filepath.Base(path)
}
