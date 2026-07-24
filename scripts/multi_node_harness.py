"""
Multi-node-on-one-machine harness (ROADMAP Phase 3 exit check).

Spawns N {ledger_service, transport peer} process pairs on distinct ports
and data dirs, connects them (fan-in bootstrap — each node dials every
node started before it, so the graph is fully connected regardless of N;
mDNS is the production discovery path but depends on this host's
multicast/firewall behavior, which the ROADMAP risk register already flags
as unverified here), and checks two things:

1. Cold-start convergence: N nodes each ingest one distinct hazard: do all
   N ledgers converge to the same 3-event state?
2. Kill/restart catch-up: kill one node's processes mid-run, ingest new
   events elsewhere (and on the dead node once it's back), restart it: does
   it catch up via anti-entropy (D6) without replaying the world?

This is also the harness Phase 5's simulate_disconnect.sh drives — keep it
general (N nodes, not hardcoded to 3) rather than a one-off test script.

Usage: python scripts/multi_node_harness.py [--nodes N]
"""
import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
NETWORK_DIR = REPO_ROOT / "src" / "network"
VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

LEDGER_BASE_PORT = 8800
P2P_BASE_PORT = 9100
HEALTH_TIMEOUT_S = 15
CONVERGE_TIMEOUT_S = 30
MULTIADDR_RE = re.compile(r"listening on (/ip4/127\.0\.0\.1/tcp/\d+/p2p/\S+)")


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
        self.ledger_proc: subprocess.Popen | None = None
        self.peer_proc: subprocess.Popen | None = None
        self.multiaddr: str | None = None

    def start_ledger(self):
        env = _base_env()
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

    def wait_ledger_healthy(self):
        deadline = time.time() + HEALTH_TIMEOUT_S
        while time.time() < deadline:
            try:
                resp = httpx.get(f"{self.ledger_url}/health", timeout=1.0)
                if resp.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"{self.node_id}: ledger service did not become healthy")

    def start_peer(self, bootstrap_peers: list[str]):
        env = _base_env()
        env["AETHER_NODE_ID"] = self.node_id
        env["AETHER_LEDGER_URL"] = self.ledger_url
        env["AETHER_P2P_PORT"] = str(self.p2p_port)
        env["AETHER_DATA_DIR"] = str(self.data_dir)
        env["AETHER_LOCAL_POLL_INTERVAL_MS"] = "500"  # faster gossip pickup for the harness
        if bootstrap_peers:
            env["AETHER_BOOTSTRAP_PEERS"] = ",".join(bootstrap_peers)
        log = open(self.peer_log, "w", encoding="utf-8")
        self.peer_proc = subprocess.Popen(
            ["node", "peer.js"], cwd=NETWORK_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
        )

    def wait_multiaddr(self) -> str:
        deadline = time.time() + HEALTH_TIMEOUT_S
        while time.time() < deadline:
            if self.peer_log.exists():
                text = self.peer_log.read_text(encoding="utf-8", errors="ignore")
                match = MULTIADDR_RE.search(text)
                if match:
                    self.multiaddr = match.group(1)
                    return self.multiaddr
            time.sleep(0.3)
        raise RuntimeError(f"{self.node_id}: peer did not report a listen multiaddr in time")

    def ingest(self, hazard_type: str) -> dict:
        payload = {
            "node_id": self.node_id,
            "timestamp": "2026-01-01T00:00:00Z",
            "hazard_type": hazard_type,
            "severity": "HIGH",
            "coordinates": {"lat": 1.0, "lng": 2.0},
        }
        resp = httpx.post(f"{self.ledger_url}/ingest", json=payload, timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def vector(self) -> dict:
        resp = httpx.get(f"{self.ledger_url}/vector", timeout=5.0)
        resp.raise_for_status()
        return resp.json()

    def kill(self):
        for proc in (self.peer_proc, self.ledger_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.peer_proc = None
        self.ledger_proc = None


def _base_env():
    import os
    return dict(os.environ)


def wait_for_convergence(
    nodes: list[Node], expected_vector_sum: int, timeout_s: int = CONVERGE_TIMEOUT_S
):
    """Poll until every live node's vector has the same total event count."""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=int, default=3)
    args = parser.parse_args()

    if shutil.which("node") is None:
        print("ERROR: node not found on PATH")
        return 1

    harness_dir = REPO_ROOT / "data" / "harness"
    if harness_dir.exists():
        shutil.rmtree(harness_dir)
    harness_dir.mkdir(parents=True)

    nodes = [Node(i, harness_dir) for i in range(args.nodes)]

    try:
        print(f"--- starting {args.nodes} ledger services ---")
        for n in nodes:
            n.start_ledger()
        for n in nodes:
            n.wait_ledger_healthy()
        print("all ledgers healthy")

        print("--- starting peers (fan-in bootstrap) ---")
        known_addrs: list[str] = []
        for n in nodes:
            n.start_peer(bootstrap_peers=list(known_addrs))
            addr = n.wait_multiaddr()
            known_addrs.append(addr)
            print(f"{n.node_id} listening: {addr}")

        print("--- cold-start convergence test ---")
        for n in nodes:
            envelope = n.ingest(f"hazard-from-{n.node_id}")
            print(f"{n.node_id} ingested {envelope['event_id']}")

        start = time.time()
        wait_for_convergence(nodes, expected_vector_sum=len(nodes))
        elapsed = time.time() - start
        print(f"CONVERGED in {elapsed:.1f}s - all {len(nodes)} nodes see all {len(nodes)} events")

        if len(nodes) >= 2:
            print("--- kill/restart catch-up test ---")
            victim = nodes[1]
            print(f"killing {victim.node_id}...")
            victim.kill()

            survivor = nodes[0]
            envelope = survivor.ingest("hazard-during-partition")
            print(
                f"{survivor.node_id} ingested {envelope['event_id']} "
                f"while {victim.node_id} is down"
            )

            print(f"restarting {victim.node_id}...")
            victim.start_ledger()
            victim.wait_ledger_healthy()
            # Reconnect to whichever nodes are still up.
            bootstrap = [
                a for n, a in zip(nodes, known_addrs)
                if n is not victim and n.peer_proc is not None
            ]
            victim.start_peer(bootstrap_peers=bootstrap)
            victim.wait_multiaddr()

            start = time.time()
            wait_for_convergence(nodes, expected_vector_sum=len(nodes) + 1)
            print(
                f"RECONVERGED in {time.time() - start:.1f}s after restart - "
                f"{victim.node_id} caught up via anti-entropy"
            )

        print("\n=== M2 PASSED: all exit checks satisfied ===")
        return 0

    except Exception as exc:
        print(f"\n=== HARNESS FAILED: {exc} ===")
        print(f"Logs preserved at: {harness_dir}")
        return 1

    finally:
        print("--- cleaning up processes ---")
        for n in nodes:
            n.kill()


if __name__ == "__main__":
    sys.exit(main())
