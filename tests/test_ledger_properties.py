"""
Property tests for the G-Set ledger core (ROADMAP Phase 1 exit check).

The CRDT contract: merge is commutative, associative, and idempotent —
any node applying any subset of events in any order converges to the same
state. These properties are what let the mesh sync without a coordinator.

Every append fsyncs to disk by design (crash safety), so these tests are
I/O-bound rather than CPU-bound — the hypothesis deadline is disabled
rather than tuned, since "real disk write per event" is the behavior under
test, not an accident to optimize away.
"""
import random
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from src.ai_engine.ledger import Ledger
from src.ai_engine.schemas import EventEnvelope, HazardPayload

NO_DEADLINE = settings(deadline=None)


@st.composite
def hazard_payloads(draw):
    return HazardPayload(
        node_id=draw(st.text(alphabet="abcdefgh", min_size=1, max_size=6)),
        timestamp="2026-01-01T00:00:00Z",
        hazard_type=draw(st.sampled_from(["flooding", "fire", "collapse", "gas_leak"])),
        severity=draw(st.sampled_from(["LOW", "MEDIUM", "HIGH"])),
        coordinates={
            "lat": draw(st.floats(min_value=-90, max_value=90, allow_nan=False)),
            "lng": draw(st.floats(min_value=-180, max_value=180, allow_nan=False)),
        },
    )


@st.composite
def event_envelopes(draw):
    node_id = draw(st.sampled_from(["nodeA", "nodeB", "nodeC"]))
    seq = draw(st.integers(min_value=1, max_value=200))
    lamport = draw(st.integers(min_value=1, max_value=200))
    payload = draw(hazard_payloads())
    return EventEnvelope(
        event_id=f"{node_id}:{seq}",
        node_id=node_id,
        seq=seq,
        lamport=lamport,
        payload=payload,
    )


# A given (node_id, seq) is authored exactly once in the real system — so any
# two batches that might overlap must draw from one shared "universe" of
# canonical envelopes. Independently-generated batches could otherwise
# produce the same event_id with two different payloads, which isn't a
# scenario the G-Set is meant to arbitrate (that would be a false failure,
# not a real bug).
event_universes = st.lists(
    event_envelopes(), min_size=0, max_size=15, unique_by=lambda e: e.event_id
)


@st.composite
def two_subsets(draw):
    universe = draw(event_universes)
    include_a = draw(st.lists(st.booleans(), min_size=len(universe), max_size=len(universe)))
    include_b = draw(st.lists(st.booleans(), min_size=len(universe), max_size=len(universe)))
    a = [e for e, keep in zip(universe, include_a) if keep]
    b = [e for e, keep in zip(universe, include_b) if keep]
    return a, b


@st.composite
def three_subsets(draw):
    universe = draw(event_universes)
    flags = [
        draw(st.lists(st.booleans(), min_size=len(universe), max_size=len(universe)))
        for _ in range(3)
    ]
    a, b, c = (
        [e for e, keep in zip(universe, f) if keep] for f in flags
    )
    return a, b, c


def _fresh_ledger(node_id: str = "test") -> tuple[Ledger, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    return Ledger(node_id=node_id, data_dir=Path(tmp.name)), tmp


def _snapshot(ledger: Ledger) -> dict:
    return {e.event_id: e.model_dump() for e in ledger.all_events()}


@given(pair=two_subsets())
@NO_DEADLINE
def test_merge_commutative(pair):
    a, b = pair
    ledger1, tmp1 = _fresh_ledger("n1")
    ledger2, tmp2 = _fresh_ledger("n2")
    try:
        ledger1.merge_batch(a)
        ledger1.merge_batch(b)

        ledger2.merge_batch(b)
        ledger2.merge_batch(a)

        assert _snapshot(ledger1) == _snapshot(ledger2)
    finally:
        tmp1.cleanup()
        tmp2.cleanup()


@given(triple=three_subsets())
@NO_DEADLINE
def test_merge_associative(triple):
    a, b, c = triple
    ledger1, tmp1 = _fresh_ledger("n1")
    ledger2, tmp2 = _fresh_ledger("n2")
    try:
        # (A ∪ B) ∪ C
        ledger1.merge_batch(a)
        ledger1.merge_batch(b)
        ledger1.merge_batch(c)

        # A ∪ (B ∪ C)
        merged_bc, tmp_bc = _fresh_ledger("bc")
        try:
            merged_bc.merge_batch(b)
            merged_bc.merge_batch(c)
            ledger2.merge_batch(a)
            ledger2.merge_batch(merged_bc.all_events())
        finally:
            tmp_bc.cleanup()

        assert _snapshot(ledger1) == _snapshot(ledger2)
    finally:
        tmp1.cleanup()
        tmp2.cleanup()


@given(events=event_universes)
@NO_DEADLINE
def test_merge_idempotent(events):
    ledger, tmp = _fresh_ledger()
    try:
        ledger.merge_batch(events)
        snapshot1 = _snapshot(ledger)

        ledger.merge_batch(events)  # merge the exact same batch again
        snapshot2 = _snapshot(ledger)

        assert snapshot1 == snapshot2
    finally:
        tmp.cleanup()


@given(events=event_universes, permutation_seed=st.integers(min_value=0, max_value=9))
@NO_DEADLINE
def test_random_permutation_converges(events, permutation_seed):
    """Any order of applying the same event set converges to the same state."""
    shuffled = list(events)
    random.Random(permutation_seed).shuffle(shuffled)

    ledger_ordered, tmp1 = _fresh_ledger("ordered")
    ledger_shuffled, tmp2 = _fresh_ledger("shuffled")
    try:
        ledger_ordered.merge_batch(events)
        ledger_shuffled.merge_batch(shuffled)
        assert _snapshot(ledger_ordered) == _snapshot(ledger_shuffled)
    finally:
        tmp1.cleanup()
        tmp2.cleanup()
