package diskqueue

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func mustOpen(t *testing.T, dir string, maxBytes int64) *Queue {
	t.Helper()
	q, err := Open(dir, maxBytes)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	return q
}

func mustPut(t *testing.T, q *Queue, id string) {
	t.Helper()
	if _, err := q.Put(id, "maestro.ingest.a.metrics", []byte(`{"id":"`+id+`"}`)); err != nil {
		t.Fatalf("put %s: %v", id, err)
	}
}

func popAll(t *testing.T, q *Queue) []string {
	t.Helper()
	var ids []string
	for {
		item, ok, err := q.Peek()
		if err != nil {
			t.Fatalf("peek: %v", err)
		}
		if !ok {
			return ids
		}
		ids = append(ids, item.ID)
		q.Remove(item)
	}
}

func TestPeekOnEmptyQueue(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1024)
	if _, ok, err := q.Peek(); ok || err != nil {
		t.Fatalf("expected empty queue, got ok=%v err=%v", ok, err)
	}
}

func TestFIFOAndContent(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1<<20)
	mustPut(t, q, "a")
	mustPut(t, q, "b")
	mustPut(t, q, "c")

	item, ok, err := q.Peek()
	if err != nil || !ok {
		t.Fatalf("peek: ok=%v err=%v", ok, err)
	}
	if item.ID != "a" || item.Subject != "maestro.ingest.a.metrics" || string(item.Payload) != `{"id":"a"}` {
		t.Fatalf("unexpected item %+v", item)
	}
	if got := popAll(t, q); len(got) != 3 || got[0] != "a" || got[2] != "c" {
		t.Fatalf("expected a b c, got %v", got)
	}
	if q.Len() != 0 || q.Bytes() != 0 {
		t.Fatalf("expected empty queue, len=%d bytes=%d", q.Len(), q.Bytes())
	}
}

func TestPeekDoesNotRemove(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1<<20)
	mustPut(t, q, "a")
	first, _, _ := q.Peek()
	second, _, _ := q.Peek()
	if first.ID != "a" || second.ID != "a" || q.Len() != 1 {
		t.Fatalf("peek must not consume: %v %v len=%d", first.ID, second.ID, q.Len())
	}
}

func TestSurvivesRestartInOrder(t *testing.T) {
	dir := t.TempDir()
	q := mustOpen(t, dir, 1<<20)
	for _, id := range []string{"a", "b", "c"} {
		mustPut(t, q, id)
	}
	item, _, _ := q.Peek()
	q.Remove(item)

	reopened := mustOpen(t, dir, 1<<20)
	mustPut(t, reopened, "d")
	got := popAll(t, reopened)
	want := []string{"b", "c", "d"}
	if len(got) != len(want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("expected %v, got %v", want, got)
		}
	}
}

func TestCapDropsOldest(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1<<20)
	mustPut(t, q, "a")
	size := q.Bytes()

	capped := mustOpen(t, t.TempDir(), size*3)
	for _, id := range []string{"a", "b", "c"} {
		mustPut(t, capped, id)
	}
	dropped, err := capped.Put("d", "maestro.ingest.a.metrics", []byte(`{"id":"d"}`))
	if err != nil {
		t.Fatalf("put: %v", err)
	}
	if dropped != 1 {
		t.Fatalf("expected 1 dropped, got %d", dropped)
	}
	if capped.Bytes() > size*3 {
		t.Fatalf("queue over its cap: %d > %d", capped.Bytes(), size*3)
	}
	if got := popAll(t, capped); len(got) != 3 || got[0] != "b" || got[2] != "d" {
		t.Fatalf("expected b c d, got %v", got)
	}
}

func TestMessageLargerThanCap(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 16)
	_, err := q.Put("a", "maestro.ingest.a.logs", make([]byte, 64))
	if !errors.Is(err, ErrTooLarge) {
		t.Fatalf("expected ErrTooLarge, got %v", err)
	}
}

func TestRejectsInvalidHeader(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1024)
	for _, tc := range [][2]string{{"", "s"}, {"a", ""}, {"a\nb", "s"}} {
		if _, err := q.Put(tc[0], tc[1], nil); err == nil {
			t.Errorf("expected an error for id=%q subject=%q", tc[0], tc[1])
		}
	}
}

func TestUnreadableFileIsDroppedAndQueueMovesOn(t *testing.T) {
	dir := t.TempDir()
	q := mustOpen(t, dir, 1<<20)
	mustPut(t, q, "a")
	mustPut(t, q, "b")
	if err := os.WriteFile(filepath.Join(dir, q.entries[0].name), []byte("garbage"), 0o600); err != nil {
		t.Fatal(err)
	}

	reopened := mustOpen(t, dir, 1<<20)
	if _, ok, err := reopened.Peek(); ok || err == nil {
		t.Fatalf("expected the broken file to be reported, ok=%v err=%v", ok, err)
	}
	if got := popAll(t, reopened); len(got) != 1 || got[0] != "b" {
		t.Fatalf("expected b after the broken file, got %v", got)
	}
}

func TestOpenRemovesHalfWrittenFiles(t *testing.T) {
	dir := t.TempDir()
	stray := filepath.Join(dir, tmpPrefix+"123")
	if err := os.WriteFile(stray, []byte("half"), 0o600); err != nil {
		t.Fatal(err)
	}
	q := mustOpen(t, dir, 1024)
	if q.Len() != 0 {
		t.Fatalf("a temp file must not count as a message")
	}
	if _, err := os.Stat(stray); !os.IsNotExist(err) {
		t.Fatalf("expected the temp file to be removed, stat err=%v", err)
	}
}

func TestRemoveAfterEvictionIsNoop(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1<<20)
	mustPut(t, q, "a")
	size := q.Bytes()
	capped := mustOpen(t, t.TempDir(), size)
	mustPut(t, capped, "a")
	item, _, _ := capped.Peek()
	mustPut(t, capped, "b") // evicts a while it is being sent
	capped.Remove(item)
	if got := popAll(t, capped); len(got) != 1 || got[0] != "b" {
		t.Fatalf("expected b, got %v", got)
	}
}

func TestNotifyAfterPut(t *testing.T) {
	q := mustOpen(t, t.TempDir(), 1024)
	mustPut(t, q, "a")
	select {
	case <-q.Notify():
	default:
		t.Fatal("expected a notification after Put")
	}
}
