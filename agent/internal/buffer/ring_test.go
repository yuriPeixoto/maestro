package buffer_test

import (
	"testing"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/buffer"
	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

func metric(name string) collector.Metric {
	return collector.Metric{Name: name, Value: 1.0, Timestamp: time.Now()}
}

func batch(names ...string) []collector.Metric {
	out := make([]collector.Metric, len(names))
	for i, n := range names {
		out[i] = metric(n)
	}
	return out
}

func TestRing_EmptyPopAllReturnsNil(t *testing.T) {
	r := buffer.New(10)
	if got := r.PopAll(); got != nil {
		t.Fatalf("expected nil, got %v", got)
	}
}

func TestRing_PushAndPopAllFIFO(t *testing.T) {
	r := buffer.New(10)
	r.Push(batch("a", "b"))
	r.Push(batch("c"))
	r.Push(batch("d", "e", "f"))

	batches := r.PopAll()
	if len(batches) != 3 {
		t.Fatalf("expected 3 batches, got %d", len(batches))
	}
	if batches[0][0].Name != "a" {
		t.Errorf("expected first batch first metric 'a', got %q", batches[0][0].Name)
	}
	if batches[1][0].Name != "c" {
		t.Errorf("expected second batch first metric 'c', got %q", batches[1][0].Name)
	}
	if batches[2][0].Name != "d" {
		t.Errorf("expected third batch first metric 'd', got %q", batches[2][0].Name)
	}
}

func TestRing_PopAllClearsBuffer(t *testing.T) {
	r := buffer.New(10)
	r.Push(batch("x"))
	r.PopAll()

	if r.Len() != 0 {
		t.Fatalf("expected 0 after PopAll, got %d", r.Len())
	}
	if got := r.PopAll(); got != nil {
		t.Fatalf("expected nil on second PopAll, got %v", got)
	}
}

func TestRing_EvictsOldestWhenFull(t *testing.T) {
	cap := 3
	r := buffer.New(cap)

	// Fill to capacity.
	r.Push(batch("first"))
	r.Push(batch("second"))
	r.Push(batch("third"))

	// One more — "first" should be evicted.
	r.Push(batch("fourth"))

	if r.Len() != cap {
		t.Fatalf("expected len=%d after overflow, got %d", cap, r.Len())
	}

	batches := r.PopAll()
	if batches[0][0].Name != "second" {
		t.Errorf("expected 'second' after eviction of 'first', got %q", batches[0][0].Name)
	}
	if batches[cap-1][0].Name != "fourth" {
		t.Errorf("expected last batch to be 'fourth', got %q", batches[cap-1][0].Name)
	}
}

func TestRing_PushEmptyBatchIsNoop(t *testing.T) {
	r := buffer.New(5)
	r.Push(nil)
	r.Push([]collector.Metric{})

	if r.Len() != 0 {
		t.Fatalf("expected 0 after pushing empty batches, got %d", r.Len())
	}
}

func TestRing_PanicOnZeroCapacity(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic for capacity 0")
		}
	}()
	buffer.New(0)
}

func TestRing_IsolatesPushedSlice(t *testing.T) {
	r := buffer.New(5)
	original := batch("original")
	r.Push(original)

	// Mutate the original slice — the ring must not reflect this change.
	original[0].Name = "mutated"

	batches := r.PopAll()
	if batches[0][0].Name != "original" {
		t.Errorf("ring buffer must copy the batch on Push; got %q", batches[0][0].Name)
	}
}
