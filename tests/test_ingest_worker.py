"""
Ingestion worker tests (ROADMAP Phase 2 exit check): the worker must
survive model-off, model-slow, and garbage-output conditions without ever
raising out of process() or run_feed() — a flaky model or bad input is
quarantined, not fatal.

test_m1_* is the M1 milestone itself: sensor text in, valid hazard in
ledger, exercised against a real Ledger service via httpx's ASGI transport
(no real socket needed).
"""
import json
import tempfile
from pathlib import Path

import httpx
import pytest

from src.ai_engine.extractor import ExtractionError, HazardPayload, MockHazardExtractor
from src.ai_engine.ingest_worker import DEMO_FEED, IngestWorker, run_feed
from src.ai_engine.ledger_service import create_app


class AlwaysFailExtractor:
    """Simulates model-off: every call raises a connectivity ExtractionError."""

    async def extract(self, text: str):
        raise ExtractionError("model unreachable or timed out: connection refused")


class TimeoutExtractor:
    """Simulates model-slow: every call raises a timeout ExtractionError."""

    async def extract(self, text: str):
        raise ExtractionError("model unreachable or timed out: deadline exceeded (5.0s)")


class GarbageOutputExtractor:
    """Simulates a model that never produces valid, schema-matching JSON."""

    async def extract(self, text: str):
        raise ExtractionError("model output failed validation twice: not valid JSON")


class NoHazardExtractor:
    """A well-behaved extractor that legitimately finds nothing."""

    async def extract(self, text: str):
        return None


class FlakyExtractor:
    """Fails on odd calls, succeeds on even calls — proves a single bad
    input doesn't stop the worker from processing the rest of the batch."""

    def __init__(self):
        self.call_count = 0
        self._mock = MockHazardExtractor(seed=1)

    async def extract(self, text: str):
        self.call_count += 1
        if self.call_count % 2 == 1:
            raise ExtractionError("model unreachable or timed out: simulated flake")
        return await self._mock.extract(text)


@pytest.fixture
def quarantine_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def dead_ledger_client():
    """An httpx client pointed at a transport that always refuses connections."""
    def _refuse(request):
        raise httpx.ConnectError("refused")

    transport = httpx.MockTransport(_refuse)
    return httpx.AsyncClient(base_url="http://127.0.0.1:1", transport=transport, timeout=5.0)


@pytest.fixture
def live_ledger_client():
    """A real Ledger service reached over httpx's ASGI transport — no socket."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(node_id="test_node", data_dir=Path(tmp))
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0)
        yield client, app.state.ledger


@pytest.mark.anyio
async def test_worker_survives_model_off(quarantine_dir, live_ledger_client):
    client, ledger = live_ledger_client
    worker = IngestWorker(AlwaysFailExtractor(), client, quarantine_dir, "n1")

    result = await worker.process("flood downtown")

    assert result is None
    assert len(ledger) == 0
    quarantined = list(quarantine_dir.glob("*.json"))
    assert len(quarantined) == 1
    record = json.loads(quarantined[0].read_text())
    assert "unreachable" in record["reason"]


@pytest.mark.anyio
async def test_worker_survives_model_slow(quarantine_dir, live_ledger_client):
    client, ledger = live_ledger_client
    worker = IngestWorker(TimeoutExtractor(), client, quarantine_dir, "n1")

    result = await worker.process("fire warehouse")

    assert result is None
    assert len(ledger) == 0
    quarantined = list(quarantine_dir.glob("*.json"))
    assert len(quarantined) == 1
    assert "timed out" in quarantined[0].read_text()


@pytest.mark.anyio
async def test_worker_survives_garbage_output(quarantine_dir, live_ledger_client):
    client, ledger = live_ledger_client
    worker = IngestWorker(GarbageOutputExtractor(), client, quarantine_dir, "n1")

    result = await worker.process("gas leak reported")

    assert result is None
    assert len(ledger) == 0
    quarantined = list(quarantine_dir.glob("*.json"))
    assert len(quarantined) == 1
    assert "validation" in quarantined[0].read_text()


@pytest.mark.anyio
async def test_worker_quarantines_when_no_hazard_found(quarantine_dir, live_ledger_client):
    client, ledger = live_ledger_client
    worker = IngestWorker(NoHazardExtractor(), client, quarantine_dir, "n1")

    result = await worker.process("the weather is nice today")

    assert result is None
    assert len(ledger) == 0
    assert len(list(quarantine_dir.glob("*.json"))) == 1


@pytest.mark.anyio
async def test_worker_survives_ledger_unreachable(quarantine_dir, dead_ledger_client):
    worker = IngestWorker(MockHazardExtractor(seed=1), dead_ledger_client, quarantine_dir, "n1")

    result = await worker.process("flood downtown")

    assert result is None
    quarantined = list(quarantine_dir.glob("*.json"))
    assert len(quarantined) == 1
    assert "ledger post failed" in quarantined[0].read_text()
    await dead_ledger_client.aclose()


@pytest.mark.anyio
async def test_mixed_failures_do_not_stop_the_batch(quarantine_dir, live_ledger_client):
    client, ledger = live_ledger_client
    flaky = FlakyExtractor()
    worker = IngestWorker(flaky, client, quarantine_dir, "n1")

    feed = ["input one", "input two", "input three", "input four"]
    results = await run_feed(worker, feed)

    assert len(results) == 4  # every input was processed, none skipped
    assert results[0] is None and results[2] is None  # odd calls fail
    assert results[1] is not None and results[3] is not None  # even calls succeed
    assert len(ledger) == 2
    assert len(list(quarantine_dir.glob("*.json"))) == 2


@pytest.mark.anyio
async def test_m1_sensor_text_becomes_valid_ledger_hazard(quarantine_dir, live_ledger_client):
    """M1 milestone: sensor text in, valid hazard in ledger."""
    client, ledger = live_ledger_client
    worker = IngestWorker(MockHazardExtractor(seed=42), client, quarantine_dir, "m1_node")

    results = await run_feed(worker, DEMO_FEED)

    assert all(r is not None for r in results)
    assert len(ledger) == len(DEMO_FEED)
    for envelope in ledger.all_events():
        HazardPayload.model_validate(envelope.payload.model_dump())  # re-validates cleanly
    assert len(list(quarantine_dir.glob("*.json"))) == 0
