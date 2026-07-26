import json
import os
import threading
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from .schemas import EventEnvelope, HazardPayload


class CorruptedLedgerError(Exception):
    """A non-recoverable parse failure — corruption in a line other than the
    last one. A torn write from a crash only ever affects the last line
    (appends are sequential); anything earlier failing to parse means the
    file was damaged some other way and must not be silently discarded."""


class Ledger:
    """G-Set CRDT of immutable hazard events. Merge = set union, keyed on
    event_id = f"{node_id}:{seq}". No wall-clock trust: ordering is Lamport,
    identity is (node_id, seq) — see CLAUDE.md Critical Rule 2 / ROADMAP D5.

    Thread-safe: FastAPI dispatches plain `def` route handlers to a real OS
    thread pool (Starlette's run_in_threadpool), so append_local/merge_remote
    genuinely run concurrently across threads for a single Ledger instance.
    Without a lock, concurrent append_local calls race on the seq
    read-modify-write — on Windows this crashes outright (os.replace raises
    PermissionError when two threads collide on the same temp path), and
    even where it doesn't crash, two events could be assigned the same seq,
    silently dropping one hazard to G-Set dedup. Found via Phase 5 chaos
    testing (concurrent POST /ingest), not by inspection."""

    def __init__(self, node_id: str, data_dir: Path):
        self.node_id = node_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self.data_dir / "ledger.jsonl"
        self._seq_path = self.data_dir / "seq.txt"
        self._lock = threading.Lock()

        self._events: dict[str, EventEnvelope] = {}
        self._lamport = 0
        self._local_seq = self._load_seq()
        self._load_ledger()

    # ---- persistence: per-node sequence counter ----

    def _load_seq(self) -> int:
        if self._seq_path.exists():
            text = self._seq_path.read_text(encoding="utf-8").strip()
            return int(text) if text else 0
        return 0

    def _persist_seq(self, seq: int) -> None:
        """Atomic write (temp + fsync + replace). Called BEFORE the event is
        appended, so a crash mid-write only ever skips a seq — never reuses
        one on restart."""
        tmp_path = self._seq_path.with_suffix(".tmp")
        tmp_path.write_text(str(seq), encoding="utf-8")
        fd = os.open(str(tmp_path), os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._seq_path)

    # ---- persistence: append-only JSONL ledger ----

    def _load_ledger(self) -> None:
        if not self._ledger_path.exists():
            return

        raw = self._ledger_path.read_bytes()
        lines = raw.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()  # trailing newline produces one empty split element

        valid_lines: list[bytes] = []
        for i, line in enumerate(lines):
            is_last = i == len(lines) - 1
            try:
                envelope = EventEnvelope.model_validate(json.loads(line.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
                if is_last:
                    # Torn final write from a crash — drop it and repair the file.
                    self._rewrite_ledger_file(valid_lines)
                    break
                raise CorruptedLedgerError(
                    f"Ledger corrupted at line {i} of {self._ledger_path}: {exc}"
                ) from exc
            else:
                valid_lines.append(line)
                self._apply(envelope)

    def _rewrite_ledger_file(self, valid_lines: list[bytes]) -> None:
        content = b"\n".join(valid_lines)
        if content:
            content += b"\n"
        tmp_path = self._ledger_path.with_suffix(".tmp")
        tmp_path.write_bytes(content)
        fd = os.open(str(tmp_path), os.O_RDWR)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._ledger_path)

    def _append_to_disk(self, envelope: EventEnvelope) -> None:
        line = envelope.model_dump_json() + "\n"
        with open(self._ledger_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    # ---- G-Set core ----

    def _apply(self, envelope: EventEnvelope) -> bool:
        """Add to the in-memory set if new. Returns True if it was new."""
        if envelope.event_id in self._events:
            return False
        self._events[envelope.event_id] = envelope
        self._lamport = max(self._lamport, envelope.lamport)
        return True

    def append_local(self, payload: HazardPayload) -> EventEnvelope:
        """Create and persist a new event authored by this node. Locked:
        the seq read-modify-write is not safe across concurrent callers."""
        with self._lock:
            next_seq = self._local_seq + 1
            self._persist_seq(next_seq)
            self._local_seq = next_seq
            self._lamport += 1

            envelope = EventEnvelope(
                event_id=f"{self.node_id}:{next_seq}",
                node_id=self.node_id,
                seq=next_seq,
                lamport=self._lamport,
                payload=payload,
            )
            self._apply(envelope)
            self._append_to_disk(envelope)
            return envelope

    def merge_remote(self, envelope: EventEnvelope) -> bool:
        """Merge one remote event. Idempotent — returns False if already
        known. Locked: check-then-insert on self._events is not atomic
        without it."""
        with self._lock:
            return self._apply_and_persist(envelope)

    def _apply_and_persist(self, envelope: EventEnvelope) -> bool:
        if not self._apply(envelope):
            return False
        self._append_to_disk(envelope)
        return True

    def merge_batch(self, envelopes: Iterable[EventEnvelope]) -> int:
        """Merge many remote events. Returns the count that were new."""
        return sum(1 for e in envelopes if self.merge_remote(e))

    # ---- anti-entropy (D6) ----

    def _snapshot(self) -> list[EventEnvelope]:
        """A brief lock hold to copy the current events out, so callers can
        iterate without racing a concurrent writer's dict mutation (which
        would otherwise risk 'dictionary changed size during iteration')."""
        with self._lock:
            return list(self._events.values())

    def vector(self) -> dict[str, int]:
        """Per-node-id max seq seen across the whole ledger."""
        vec: dict[str, int] = {}
        for envelope in self._snapshot():
            vec[envelope.node_id] = max(vec.get(envelope.node_id, 0), envelope.seq)
        return vec

    def events_since(self, since: dict[str, int]) -> list[EventEnvelope]:
        """Events the caller (whose view is `since`) is missing."""
        return [e for e in self._snapshot() if e.seq > since.get(e.node_id, 0)]

    def all_events(self) -> list[EventEnvelope]:
        return self._snapshot()

    def __len__(self) -> int:
        return len(self._snapshot())
