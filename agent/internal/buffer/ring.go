package buffer

import (
	"sync"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

// Ring is a thread-safe fixed-capacity circular buffer of metric batches.
// When full, writing evicts the oldest entry (FIFO). It never blocks.
type Ring struct {
	mu       sync.Mutex
	items    [][]collector.Metric
	head     int // index of the oldest item
	tail     int // index where the next item will be written
	count    int
	capacity int
}

// New creates a Ring with the given capacity. Panics if capacity < 1.
func New(capacity int) *Ring {
	if capacity < 1 {
		panic("buffer: capacity must be >= 1")
	}
	return &Ring{
		items:    make([][]collector.Metric, capacity),
		capacity: capacity,
	}
}

// Push adds a batch to the ring. If the buffer is full, the oldest batch
// is silently evicted to make room.
func (r *Ring) Push(batch []collector.Metric) {
	if len(batch) == 0 {
		return
	}
	// Copy the slice so the caller can reuse its underlying array safely.
	cp := make([]collector.Metric, len(batch))
	copy(cp, batch)

	r.mu.Lock()
	defer r.mu.Unlock()

	if r.count == r.capacity {
		// Evict oldest: advance head.
		r.head = (r.head + 1) % r.capacity
		r.count--
	}

	r.items[r.tail] = cp
	r.tail = (r.tail + 1) % r.capacity
	r.count++
}

// PopAll removes and returns all buffered batches in FIFO order.
// Returns nil if the buffer is empty.
func (r *Ring) PopAll() [][]collector.Metric {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.count == 0 {
		return nil
	}

	out := make([][]collector.Metric, r.count)
	for i := range out {
		out[i] = r.items[(r.head+i)%r.capacity]
	}

	// Reset.
	r.head = 0
	r.tail = 0
	r.count = 0

	return out
}

// Len returns the number of batches currently buffered.
func (r *Ring) Len() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.count
}
