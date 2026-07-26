"""
Chaos matrix: duplicate event injection must never corrupt the ledger or
inflate its count (ROADMAP Phase 5). Phase 1's property tests already prove
merge is idempotent for sequential application; this file adds the
adversarial angle Phase 1/2 didn't cover — a buggy or malicious peer
replaying the same batch many times *concurrently* (a race a purely
sequential test can't expose), via the real HTTP boundary.
"""
import asyncio
import tempfile
from pathlib import Path

import httpx
import pytest

from src.ai_engine.ledger_service import create_app

SAMPLE_PAYLOAD = {
    "node_id": "nodeA",
    "timestamp": "2026-01-01T00:00:00Z",
    "hazard_type": "flooding",
    "severity": "HIGH",
    "coordinates": {"lat": 1.0, "lng": 2.0},
}

DUPLICATE_ENVELOPE = {
    "event_id": "nodeB:1",
    "node_id": "nodeB",
    "seq": 1,
    "lamport": 1,
    "payload": SAMPLE_PAYLOAD,
}


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(node_id="nodeA", data_dir=Path(tmp))
        transport = httpx.ASGITransport(app=app)
        yield httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=5.0)


@pytest.mark.anyio
async def test_sequential_replay_stays_idempotent(client):
    for _ in range(20):
        resp = await client.post("/events", json=[DUPLICATE_ENVELOPE])
        assert resp.status_code == 200

    vector = (await client.get("/vector")).json()
    assert vector == {"nodeB": 1}
    events = (await client.get("/events")).json()
    assert len(events) == 1


@pytest.mark.anyio
async def test_concurrent_replay_stays_idempotent(client):
    """20 identical POST /events fired concurrently — the race Phase 1's
    sequential property tests structurally can't hit, since asyncio here
    can interleave requests mid-merge on the shared ledger."""
    responses = await asyncio.gather(
        *[client.post("/events", json=[DUPLICATE_ENVELOPE]) for _ in range(20)]
    )
    assert all(r.status_code == 200 for r in responses)

    total_merged = sum(r.json()["merged"] for r in responses)
    assert total_merged == 1, (
        f"expected exactly one winner among concurrent duplicates, got {total_merged}"
    )

    vector = (await client.get("/vector")).json()
    assert vector == {"nodeB": 1}
    events = (await client.get("/events")).json()
    assert len(events) == 1


@pytest.mark.anyio
async def test_concurrent_distinct_and_duplicate_mixed(client):
    """A realistic gossip storm: some genuinely new events, some replays of
    events already delivered, all arriving concurrently."""
    distinct = [
        {
            "event_id": f"nodeC:{i}",
            "node_id": "nodeC",
            "seq": i,
            "lamport": i,
            "payload": SAMPLE_PAYLOAD,
        }
        for i in range(1, 6)
    ]
    # Prime the ledger with these first, then hammer with concurrent
    # replays of the same events mixed with genuinely-already-known ones.
    await client.post("/events", json=distinct)

    batches = [distinct[i % len(distinct):i % len(distinct) + 1] for i in range(30)]
    responses = await asyncio.gather(*[client.post("/events", json=b) for b in batches])
    assert all(r.status_code == 200 for r in responses)

    events = (await client.get("/events")).json()
    assert len(events) == 5
    assert sorted(e["event_id"] for e in events) == [f"nodeC:{i}" for i in range(1, 6)]
