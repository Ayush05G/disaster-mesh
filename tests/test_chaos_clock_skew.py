"""
Chaos matrix: clock set backwards must be a non-event (ROADMAP Phase 5 /
CLAUDE.md "never use wall-clock time for ordering or identity").

Offline nodes have no NTP; a battery-dead RTC resetting on boot, a manual
clock change, or an NTP correction jumping backwards must never corrupt
ordering, identity, or merge behavior. Ordering is Lamport, identity is
(node_id, seq) — both are internal counters the Ledger increments itself
and never derives from wall-clock time.
"""
import tempfile
from pathlib import Path

from src.ai_engine.ledger import Ledger
from src.ai_engine.schemas import HazardPayload

LEDGER_SOURCE = Path(__file__).resolve().parent.parent / "src" / "ai_engine" / "ledger.py"


def test_ledger_source_never_reads_wall_clock():
    """Structural regression guard: if a future change adds a datetime/time
    read into the ledger's append or merge path, this must fail loudly."""
    source = LEDGER_SOURCE.read_text(encoding="utf-8")
    for forbidden in ("datetime", "time.time(", "time.monotonic("):
        assert forbidden not in source, (
            f"ledger.py now references {forbidden!r} — identity/ordering must "
            f"stay derived only from (node_id, seq) and the Lamport counter"
        )


def _payload(hazard_type: str, timestamp: str) -> HazardPayload:
    return HazardPayload(
        node_id="nodeA",
        timestamp=timestamp,
        hazard_type=hazard_type,
        severity="HIGH",
        coordinates={"lat": 1.0, "lng": 2.0},
    )


def test_append_local_unaffected_by_backwards_timestamps():
    """Three appends with the payload timestamp jumping backwards, forwards,
    then frozen — seq and lamport must still increment normally, in order,
    exactly as if the clock had behaved."""
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(node_id="nodeA", data_dir=Path(tmp))

        e1 = ledger.append_local(_payload("flood", "2026-06-01T00:00:00Z"))
        # Clock jumps backwards ten years (RTC reset on boot).
        e2 = ledger.append_local(_payload("fire", "2016-01-01T00:00:00Z"))
        # Clock frozen at the same backwards instant (dead battery).
        e3 = ledger.append_local(_payload("collapse", "2016-01-01T00:00:00Z"))

        assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
        assert (e1.lamport, e2.lamport, e3.lamport) == (1, 2, 3)
        assert (e1.event_id, e2.event_id, e3.event_id) == ("nodeA:1", "nodeA:2", "nodeA:3")
        assert len(ledger) == 3


def test_merge_order_identical_regardless_of_payload_timestamps():
    """Two ledgers merge the same three events — one set with normal
    increasing timestamps, one with the timestamps scrambled/backwards.
    The resulting ledger state (by event_id and vector) must be identical:
    the payload timestamp must have zero influence on merge outcome."""
    from src.ai_engine.schemas import EventEnvelope

    def envelope(seq: int, lamport: int, timestamp: str) -> EventEnvelope:
        return EventEnvelope(
            event_id=f"nodeA:{seq}",
            node_id="nodeA",
            seq=seq,
            lamport=lamport,
            payload=_payload("flood", timestamp),
        )

    normal_order = [
        envelope(1, 1, "2026-01-01T00:00:00Z"),
        envelope(2, 2, "2026-01-02T00:00:00Z"),
        envelope(3, 3, "2026-01-03T00:00:00Z"),
    ]
    scrambled_clock = [
        envelope(1, 1, "2026-01-01T00:00:00Z"),
        envelope(2, 2, "1999-12-31T23:59:59Z"),  # backwards
        envelope(3, 3, "2099-01-01T00:00:00Z"),  # wildly forwards
    ]

    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        ledger_normal = Ledger(node_id="n1", data_dir=Path(tmp_a))
        ledger_scrambled = Ledger(node_id="n2", data_dir=Path(tmp_b))

        ledger_normal.merge_batch(normal_order)
        ledger_scrambled.merge_batch(scrambled_clock)

        ids_normal = sorted(e.event_id for e in ledger_normal.all_events())
        ids_scrambled = sorted(e.event_id for e in ledger_scrambled.all_events())
        assert ids_normal == ids_scrambled
        assert ledger_normal.vector() == ledger_scrambled.vector()
