"""
Ledger service — D4 contract (ROADMAP.md). Localhost-only FastAPI wrapper
around the Ledger G-Set. Python owns all ledger state (D2); the Node
transport is a stateless relay that talks to this service, never touching
the JSONL directly.

Every client of this API (ingestion worker, transport peer, dashboard) must
set an explicit request timeout — this service does not enforce one on
itself, per CLAUDE.md's "explicit timeouts everywhere" rule applying to the
caller side of a local socket.

Run: uvicorn ai_engine.ledger_service:get_app --factory --host 127.0.0.1 --port 8700
Env: AETHER_NODE_ID (default "node_local"), AETHER_DATA_DIR (default ./data/<node_id>)

`get_app` is a factory, not a module-level `app` object, deliberately: a
module-level app would construct a real Ledger (real disk I/O) as a side
effect of merely *importing* this file — which is exactly what happens when
tests import `create_app` for isolated instances. Import must stay side-effect-free.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .ledger import Ledger
from .schemas import EventEnvelope, HazardPayload


class HeartbeatRequest(BaseModel):
    peer_id: str
    address: Optional[str] = None


class PeerInfo(BaseModel):
    peer_id: str
    address: Optional[str]
    seconds_since_heartbeat: float


def create_app(node_id: str, data_dir: Path) -> FastAPI:
    ledger = Ledger(node_id=node_id, data_dir=data_dir)
    # Peer liveness bookkeeping is operational, not ledger state — time.monotonic()
    # here tracks "how long since we heard from X", never event ordering/identity.
    peers: dict[str, dict] = {}

    app = FastAPI(title="Aether Ledger Service")
    app.state.ledger = ledger
    app.state.peers = peers

    @app.get("/health")
    def health():
        return {"status": "ok", "node_id": ledger.node_id, "event_count": len(ledger)}

    @app.get("/vector")
    def get_vector():
        return ledger.vector()

    @app.get("/events", response_model=list[EventEnvelope])
    def get_events(since: Optional[str] = Query(default=None)):
        vec: dict[str, int] = {}
        if since:
            try:
                vec = json.loads(since)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="`since` must be JSON: {node_id: seq}")
        return ledger.events_since(vec)

    @app.post("/events")
    def post_events(envelopes: list[EventEnvelope]):
        merged = ledger.merge_batch(envelopes)
        return {"merged": merged, "total": len(ledger)}

    @app.post("/ingest", response_model=EventEnvelope)
    def post_ingest(payload: HazardPayload):
        return ledger.append_local(payload)

    @app.post("/peers/heartbeat")
    def post_heartbeat(hb: HeartbeatRequest):
        peers[hb.peer_id] = {"address": hb.address, "last_seen": time.monotonic()}
        return {"status": "ok"}

    @app.get("/peers", response_model=list[PeerInfo])
    def get_peers():
        now = time.monotonic()
        return [
            PeerInfo(
                peer_id=peer_id,
                address=info["address"],
                seconds_since_heartbeat=now - info["last_seen"],
            )
            for peer_id, info in peers.items()
        ]

    return app


def get_app() -> FastAPI:
    """Factory for `uvicorn ... --factory`. Reads config from env at call
    time, not import time — see module docstring."""
    node_id = os.getenv("AETHER_NODE_ID", "node_local")
    data_dir = Path(os.getenv("AETHER_DATA_DIR", f"data/{node_id}"))
    return create_app(node_id=node_id, data_dir=data_dir)
