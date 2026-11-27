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

	"github.com/yuriPeixoto/maestro/agent/internal/transport"
)

const pollInterval = time.Second

// Sink receives the new lines of each file (transport.Sink in the agent).
type Sink interface {
	Logs(file string, lines []transport.LogLine)
}

// Start launches one goroutine per log file and returns the list of paths that
// actually exist on disk. Files that do not exist are skipped silently.
func Start(ctx context.Context, paths []string, sink Sink) []string {
	var watching []string
	for _, path := range paths {
		if _, err := os.Stat(path); err != nil {
			continue // skip missing files silently
		}
		watching = append(watching, logName(path))
		go watch(ctx, sink, path)
	}

	if len(watching) > 0 {
		log.Printf("info [logwatcher]: watching %d file(s): %s", len(watching), strings.Join(watching, ", "))
	}
	return watching
}

// watch tails a single file and hands the lines read on each poll to the sink as one call.
// It handles log rotation by detecting when the file shrinks.
func watch(ctx context.Context, sink Sink, path string) {
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

			if batch := toLogLines(lines, time.Now().UTC()); len(batch) > 0 {
				sink.Logs(logName, batch)
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

// toLogLines drops empty lines and stamps the rest with the time they were read.
func toLogLines(lines []string, readAt time.Time) []transport.LogLine {
	var out []transport.LogLine
	for _, line := range lines {
		if line == "" {
			continue
		}
		out = append(out, transport.LogLine{Timestamp: readAt, Line: line})
	}
	return out
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
