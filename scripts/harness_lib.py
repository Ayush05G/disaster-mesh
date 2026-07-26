"""
Shared process-orchestration library for the Phase 3 multi-node harness and
the Phase 5 partition simulation. One `Node` abstraction (spawn ledger
service + transport peer, wait for readiness, ingest, inspect state, kill)
so the two scripts don't duplicate subprocess plumbing.
"""
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
NETWORK_DIR = REPO_ROOT / "src" / "network"
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

LEDGER_BASE_PORT = 8800
P2P_BASE_PORT = 9100
HEALTH_TIMEOUT_S = 15
CONVERGE_TIMEOUT_S = 30
MULTIADDR_RE = re.compile(r"listening on (/ip4/127\.0\.0\.1/tcp/\d+/p2p/\S+)")


def base_env() -> dict:
    return dict(os.environ)


class Node:
    def __init__(self, index: int, harness_dir: Path):
        self.index = index
        self.node_id = f"node{index}"
        self.data_dir = harness_dir / self.node_id
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_port = LEDGER_BASE_PORT + index
        self.p2p_port = P2P_BASE_PORT + index
        self.ledger_url = f"http://127.0.0.1:{self.ledger_port}"
        self.ledger_log = self.data_dir / "ledger.stdout.log"
        self.peer_log = self.data_dir / "peer.stdout.log"
        self.ledger_proc: Optional[subprocess.Popen] = None
        self.peer_proc: Optional[subprocess.Popen] = None
        self.multiaddr: Optional[str] = None

    def start_ledger(self):
        env = base_env()
        env["AETHER_NODE_ID"] = self.node_id
        env["AETHER_DATA_DIR"] = str(self.data_dir)
        log = open(self.ledger_log, "w", encoding="utf-8")
        self.ledger_proc = subprocess.Popen(
            [
                str(VENV_PYTHON), "-m", "uvicorn",
                "ai_engine.ledger_service:get_app", "--factory",
                "--host", "127.0.0.1", "--port", str(self.ledger_port),
                "--app-dir", str(REPO_ROOT / "src"),
            ],
            cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

    def wait_ledger_healthy(self, timeout_s: float = HEALTH_TIMEOUT_S):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                resp = httpx.get(f"{self.ledger_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"{self.node_id}: ledger service did not become healthy")

    def start_peer(self, bootstrap_peers: list[str], local_poll_ms: int = 500):
        env = base_env()
        env["AETHER_NODE_ID"] = self.node_id
        env["AETHER_LEDGER_URL"] = self.ledger_url
        env["AETHER_P2P_PORT"] = str(self.p2p_port)
        env["AETHER_DATA_DIR"] = str(self.data_dir)
        env["AETHER_LOCAL_POLL_INTERVAL_MS"] = str(local_poll_ms)
        if bootstrap_peers:
            env["AETHER_BOOTSTRAP_PEERS"] = ",".join(bootstrap_peers)
        log = open(self.peer_log, "w", encoding="utf-8")
        self.peer_proc = subprocess.Popen(
            ["node", "peer.js"], cwd=NETWORK_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

    def wait_multiaddr(self, timeout_s: float = HEALTH_TIMEOUT_S) -> str:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.peer_log.exists():
                text = self.peer_log.read_text(encoding="utf-8", errors="ignore")
                match = MULTIADDR_RE.search(text)
                if match:
                    self.multiaddr = match.group(1)
                    return self.multiaddr
            time.sleep(0.3)
        raise RuntimeError(f"{self.node_id}: peer did not report a listen multiaddr in time")

    def ingest(self, hazard_type: str, severity: str = "HIGH") -> dict:
        payload = {
            "node_id": self.node_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "hazard_type": hazard_type,
            "severity": severity,
            "coordinates": {"lat": 1.0, "lng": 2.0},
        }
        resp = httpx.post(f"{self.ledger_url}/ingest", json=payload, timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def vector(self) -> dict:
        resp = httpx.get(f"{self.ledger_url}/vector", timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def all_events(self) -> list[dict]:
        resp = httpx.get(f"{self.ledger_url}/events", timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def kill(self):
        """Kill both processes — simulates full node death (Phase 3)."""
        self.kill_peer()
        self.kill_ledger()

    def kill_peer(self):
        """Kill only the transport — simulates a network partition while
        the node keeps running and accepting local ingest (Phase 5)."""
        self._kill_proc(self.peer_proc)
        self.peer_proc = None

    def kill_ledger(self):
        self._kill_proc(self.ledger_proc)
        self.ledger_proc = None

    @staticmethod
    def _kill_proc(proc: Optional[subprocess.Popen], sig: str = "terminate"):
        if proc and proc.poll() is None:
            if sig == "kill":
                proc.kill()
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def wait_for_convergence(
    nodes: list[Node], expected_vector_sum: int, timeout_s: int = CONVERGE_TIMEOUT_S
):
    """Poll until every live node's vector has the same total event count
    AND identical per-node-id vectors (not just a matching sum)."""
    deadline = time.time() + timeout_s
    last_state = None
    while time.time() < deadline:
        vectors = {}
        for n in nodes:
            if n.ledger_proc is None:
                continue
            try:
                vectors[n.node_id] = n.vector()
            except httpx.HTTPError:
                vectors[n.node_id] = None
        last_state = vectors
        totals = [sum(v.values()) for v in vectors.values() if v is not None]
        if totals and all(t == expected_vector_sum for t in totals):
            snapshots = [v for v in vectors.values() if v is not None]
            if all(v == snapshots[0] for v in snapshots):
                return vectors
        time.sleep(0.5)
    raise RuntimeError(f"convergence timed out; last state: {last_state}")


def wait_for_full_convergence(
    nodes: list[Node], expected_total_events: int, timeout_s: int = CONVERGE_TIMEOUT_S
) -> dict:
    """Stronger check than wait_for_convergence: compares the full set of
    events (by event_id, ignoring order) across all live nodes for exact
    equality, not just vector sums. Returns {node_id: [events]} on success."""
    deadline = time.time() + timeout_s
    last_state = None
    while time.time() < deadline:
        snapshots = {}
        for n in nodes:
            if n.ledger_proc is None:
                continue
            try:
                snapshots[n.node_id] = n.all_events()
            except httpx.HTTPError:
                snapshots[n.node_id] = None
        last_state = snapshots
        live = [v for v in snapshots.values() if v is not None]
        if live and all(len(v) == expected_total_events for v in live):
            id_sets = [frozenset(e["event_id"] for e in v) for v in live]
            if all(s == id_sets[0] for s in id_sets):
                return snapshots
        time.sleep(0.5)
    raise RuntimeError(f"full convergence timed out; last state: {last_state}")
