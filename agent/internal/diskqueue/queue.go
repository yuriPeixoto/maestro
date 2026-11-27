// Package diskqueue is the agent's outgoing buffer: a FIFO of messages kept as one file each in a
// directory, capped in bytes. A message is written to disk before it is sent and removed only after the
// transport confirmed it, so a restart or a long outage of the transport delays data instead of losing it.
// When the cap is reached the oldest messages are dropped first: the newest data is what alerts need.
package diskqueue

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
)

const (
	fileSuffix = ".msg"
	tmpPrefix  = ".tmp-"
	nameDigits = 20
	dirMode    = 0o700
)

// ErrTooLarge is returned by Put for a message that alone is bigger than the queue's cap.
var ErrTooLarge = errors.New("diskqueue: message larger than the queue cap")

// Item is one stored message.
type Item struct {
	ID      string
	Subject string
	Payload []byte

	name string
}

type entry struct {
	name string
	size int64
}

// Queue is safe for concurrent use. One reader (Peek/Remove) and any number of writers (Put).
type Queue struct {
	dir      string
	maxBytes int64

	mu      sync.Mutex
	entries []entry
	total   int64
	nextSeq uint64

	notify chan struct{}
}

// Open loads the messages left in dir by a previous run (creating dir if needed) and removes
// half-written files.
func Open(dir string, maxBytes int64) (*Queue, error) {
	if maxBytes < 1 {
		return nil, fmt.Errorf("diskqueue: max bytes must be >= 1, got %d", maxBytes)
	}
	if err := os.MkdirAll(dir, dirMode); err != nil {
		return nil, fmt.Errorf("diskqueue: create %s: %w", dir, err)
	}

	q := &Queue{dir: dir, maxBytes: maxBytes, notify: make(chan struct{}, 1)}
	if err := q.load(); err != nil {
		return nil, err
	}
	return q, nil
}

func (q *Queue) load() error {
	files, err := os.ReadDir(q.dir)
	if err != nil {
		return fmt.Errorf("diskqueue: read %s: %w", q.dir, err)
	}

	for _, f := range files {
		name := f.Name()
		if strings.HasPrefix(name, tmpPrefix) {
			_ = os.Remove(filepath.Join(q.dir, name))
			continue
		}
		seq, ok := parseName(name)
		if !ok || f.IsDir() {
			continue
		}
		info, err := f.Info()
		if err != nil {
			continue
		}
		q.entries = append(q.entries, entry{name: name, size: info.Size()})
		q.total += info.Size()
		if seq >= q.nextSeq {
			q.nextSeq = seq + 1
		}
	}

	sort.Slice(q.entries, func(i, j int) bool { return q.entries[i].name < q.entries[j].name })
	return nil
}

// Put stores a message at the end of the queue. It returns how many old messages were dropped
// to stay under the cap.
func (q *Queue) Put(id, subject string, payload []byte) (dropped int, err error) {
	if id == "" || subject == "" || strings.ContainsAny(id+subject, "\n") {
		return 0, fmt.Errorf("diskqueue: invalid id %q or subject %q", id, subject)
	}
	content := encode(id, subject, payload)
	size := int64(len(content))
	if size > q.maxBytes {
		return 0, ErrTooLarge
	}

	q.mu.Lock()
	defer q.mu.Unlock()

	for q.total+size > q.maxBytes && len(q.entries) > 0 {
		q.dropOldestLocked()
		dropped++
	}

	name := fmt.Sprintf("%0*d%s", nameDigits, q.nextSeq, fileSuffix)
	if err := writeFile(q.dir, name, content); err != nil {
		return dropped, err
	}
	q.nextSeq++
	q.entries = append(q.entries, entry{name: name, size: size})
	q.total += size

	select {
	case q.notify <- struct{}{}:
	default:
	}
	return dropped, nil
}

// Peek returns the oldest message without removing it. ok is false when the queue is empty.
// A file that cannot be parsed is removed and reported through err; the next call moves on.
func (q *Queue) Peek() (item Item, ok bool, err error) {
	q.mu.Lock()
	if len(q.entries) == 0 {
		q.mu.Unlock()
		return Item{}, false, nil
	}
	head := q.entries[0]
	q.mu.Unlock()

	data, err := os.ReadFile(filepath.Join(q.dir, head.name))
	if errors.Is(err, fs.ErrNotExist) {
		q.forget(head.name)
		return Item{}, false, fmt.Errorf("diskqueue: %s vanished", head.name)
	}
	if err != nil {
		return Item{}, false, fmt.Errorf("diskqueue: read %s: %w", head.name, err)
	}

	item, decodeErr := decode(data)
	if decodeErr != nil {
		q.removeFile(head.name)
		return Item{}, false, fmt.Errorf("diskqueue: dropped unreadable %s: %w", head.name, decodeErr)
	}
	item.name = head.name
	return item, true, nil
}

// Remove deletes a message returned by Peek. Removing one already dropped by the cap is a no-op.
func (q *Queue) Remove(item Item) {
	q.removeFile(item.name)
}

// Len is the number of stored messages.
func (q *Queue) Len() int {
	q.mu.Lock()
	defer q.mu.Unlock()
	return len(q.entries)
}

// Bytes is the size of the stored messages.
func (q *Queue) Bytes() int64 {
	q.mu.Lock()
	defer q.mu.Unlock()
	return q.total
}

// Notify receives a value after a Put, so a reader waiting on an empty queue wakes up.
func (q *Queue) Notify() <-chan struct{} {
	return q.notify
}

func (q *Queue) removeFile(name string) {
	if err := os.Remove(filepath.Join(q.dir, name)); err != nil && !errors.Is(err, fs.ErrNotExist) {
		// The entry is kept: the next Peek returns the same message and the send is retried, which
		// the message id makes harmless.
		return
	}
	q.forget(name)
}

func (q *Queue) forget(name string) {
	q.mu.Lock()
	defer q.mu.Unlock()
	for i, e := range q.entries {
		if e.name != name {
			continue
		}
		q.total -= e.size
		q.entries = append(q.entries[:i], q.entries[i+1:]...)
		return
	}
}

func (q *Queue) dropOldestLocked() {
	oldest := q.entries[0]
	_ = os.Remove(filepath.Join(q.dir, oldest.name))
	q.total -= oldest.size
	q.entries = q.entries[1:]
}

func writeFile(dir, name string, content []byte) error {
	tmp, err := os.CreateTemp(dir, tmpPrefix+"*")
	if err != nil {
		return fmt.Errorf("diskqueue: create temp file: %w", err)
	}
	tmpName := tmp.Name()
	cleanup := func(cause error) error {
		tmp.Close()
		os.Remove(tmpName)
		return fmt.Errorf("diskqueue: write %s: %w", name, cause)
	}

	// os.CreateTemp creates the file with mode 0600.
	if _, err := tmp.Write(content); err != nil {
		return cleanup(err)
	}
	if err := tmp.Sync(); err != nil {
		return cleanup(err)
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName)
		return fmt.Errorf("diskqueue: close %s: %w", name, err)
	}
	if err := os.Rename(tmpName, filepath.Join(dir, name)); err != nil {
		os.Remove(tmpName)
		return fmt.Errorf("diskqueue: rename %s: %w", name, err)
	}
	return nil
}

// File layout: the id, a newline, the subject, a newline, then the payload as is.
func encode(id, subject string, payload []byte) []byte {
	var b bytes.Buffer
	b.Grow(len(id) + len(subject) + len(payload) + 2)
	b.WriteString(id)
	b.WriteByte('\n')
	b.WriteString(subject)
	b.WriteByte('\n')
	b.Write(payload)
	return b.Bytes()
}

func decode(data []byte) (Item, error) {
	parts := bytes.SplitN(data, []byte{'\n'}, 3)
	if len(parts) != 3 || len(parts[0]) == 0 || len(parts[1]) == 0 {
		return Item{}, errors.New("missing id or subject")
	}
	return Item{ID: string(parts[0]), Subject: string(parts[1]), Payload: parts[2]}, nil
}

func parseName(name string) (uint64, bool) {
	digits, found := strings.CutSuffix(name, fileSuffix)
	if !found || len(digits) != nameDigits {
		return 0, false
	}
	seq, err := strconv.ParseUint(digits, 10, 64)
	return seq, err == nil
}
