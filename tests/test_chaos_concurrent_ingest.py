"""
Chaos matrix: concurrent local ingest must never collide or crash.

Found via Phase 5 chaos testing, not inspection: every ledger_service route
is a plain `def`, so FastAPI/Starlette dispatches it to a real OS thread
pool (anyio.to_thread.run_sync) — concurrent requests genuinely run on
different threads. Ledger.append_local's seq read-modify-write was not
locked, so concurrent POST /ingest calls could compute the same seq,
silently dropping one hazard to G-Set dedup — and on Windows, actually
crashed the server outright (os.replace raised PermissionError when two
threads collided on the same temp seq-file path).

This test hits the Ledger class directly with real threads (fast, no
server needed) so the regression is caught without spinning up uvicorn.
"""
import tempfile
import threading
from pathlib import Path

from src.ai_engine.ledger import Ledger
from src.ai_engine.schemas import HazardPayload


def _payload(i: int) -> HazardPayload:
    return HazardPayload(
        node_id="racer",
        timestamp="2026-01-01T00:00:00Z",
        hazard_type=f"hazard-{i}",
        severity="HIGH",
        coordinates={"lat": 1.0, "lng": 2.0},
    )


def test_concurrent_append_local_never_collides():
    n_threads = 100
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(node_id="racer", data_dir=Path(tmp))
        results = [None] * n_threads
        errors = []

        def worker(i):
            try:
                results[i] = ledger.append_local(_payload(i))
            except Exception as exc:  # noqa: BLE001 - want to see anything, not just one type
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"append_local raised under concurrency: {errors}"
        event_ids = [r.event_id for r in results]
        assert len(set(event_ids)) == n_threads, "seq collision: two threads got the same event_id"
        assert len(ledger) == n_threads
        assert ledger.vector() == {"racer": n_threads}


def test_concurrent_append_and_merge_together():
    """Local ingest and remote merge racing on the same ledger at once —
    the two entry points that mutate shared state must not corrupt each
    other regardless of which one is running when."""
    from src.ai_engine.schemas import EventEnvelope

    n_local = 50
    n_remote = 50
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Ledger(node_id="racer", data_dir=Path(tmp))
        errors = []

        def local_worker(i):
            try:
                ledger.append_local(_payload(i))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def remote_worker(i):
            try:
                envelope = EventEnvelope(
                    event_id=f"peer:{i + 1}",
                    node_id="peer",
                    seq=i + 1,
                    lamport=i + 1,
                    payload=_payload(i),
                )
                ledger.merge_remote(envelope)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = (
            [threading.Thread(target=local_worker, args=(i,)) for i in range(n_local)]
            + [threading.Thread(target=remote_worker, args=(i,)) for i in range(n_remote)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"raised under mixed local/remote concurrency: {errors}"
        assert len(ledger) == n_local + n_remote
        assert ledger.vector() == {"racer": n_local, "peer": n_remote}
