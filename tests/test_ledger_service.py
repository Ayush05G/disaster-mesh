import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.ai_engine.ledger_service import create_app

SAMPLE_PAYLOAD = {
    "node_id": "nodeA",
    "timestamp": "2026-01-01T00:00:00Z",
    "hazard_type": "flooding",
    "severity": "HIGH",
    "coordinates": {"lat": 1.0, "lng": 2.0},
}


@pytest.fixture
def client():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(node_id="nodeA", data_dir=Path(tmp))
        yield TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "node_id": "nodeA", "event_count": 0}


def test_ingest_and_vector(client):
    resp = client.post("/ingest", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200
    envelope = resp.json()
    assert envelope["event_id"] == "nodeA:1"
    assert envelope["payload"]["hazard_type"] == "flooding"

    resp = client.get("/vector")
    assert resp.json() == {"nodeA": 1}


def test_events_since(client):
    client.post("/ingest", json=SAMPLE_PAYLOAD)
    client.post("/ingest", json=SAMPLE_PAYLOAD)

    resp = client.get("/events", params={"since": '{"nodeA": 1}'})
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_id"] == "nodeA:2"

    resp = client.get("/events")
    assert len(resp.json()) == 2


def test_post_events_merges_remote_batch(client):
    remote_envelope = {
        "event_id": "nodeB:1",
        "node_id": "nodeB",
        "seq": 1,
        "lamport": 1,
        "payload": SAMPLE_PAYLOAD,
    }
    resp = client.post("/events", json=[remote_envelope])
    assert resp.json() == {"merged": 1, "total": 1}

    # Idempotent: merging the same event again merges 0 new
    resp = client.post("/events", json=[remote_envelope])
    assert resp.json() == {"merged": 0, "total": 1}


def test_peers_heartbeat_and_list(client):
    resp = client.post("/peers/heartbeat", json={"peer_id": "nodeB", "address": "192.168.1.5"})
    assert resp.status_code == 200

    resp = client.get("/peers")
    peers = resp.json()
    assert len(peers) == 1
    assert peers[0]["peer_id"] == "nodeB"
    assert peers[0]["address"] == "192.168.1.5"
    assert peers[0]["seconds_since_heartbeat"] >= 0
