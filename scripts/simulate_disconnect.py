"""
Network partition simulation (ROADMAP Phase 5 exit check).

Different failure mode than Phase 3's multi_node_harness.py kill/restart
test: there, a node's *process* dies and comes back. Here, both nodes'
ledger services stay running the entire time — only the transport (peer.js)
is cut, simulating a real network partition (radio out of range, hotspot
down) rather than a crash. Both sides keep accepting local ingest while
partitioned, independently diverging, and must reconverge byte-for-byte
once the transport reconnects — the actual CRDT partition-tolerance
property, not just "did the file survive a restart."

Usage: python scripts/simulate_disconnect.py
"""
import shutil
import sys
import time

from harness_lib import REPO_ROOT, Node, wait_for_full_convergence


def main():
    if shutil.which("node") is None:
        print("ERROR: node not found on PATH")
        return 1

    harness_dir = REPO_ROOT / "data" / "disconnect_sim"
    if harness_dir.exists():
        shutil.rmtree(harness_dir)
    harness_dir.mkdir(parents=True)

    node_a = Node(0, harness_dir)
    node_b = Node(1, harness_dir)
    nodes = [node_a, node_b]

    try:
        print("--- starting both nodes, connected ---")
        for n in nodes:
            n.start_ledger()
        for n in nodes:
            n.wait_ledger_healthy()

        node_a.start_peer(bootstrap_peers=[])
        addr_a = node_a.wait_multiaddr()
        node_b.start_peer(bootstrap_peers=[addr_a])
        node_b.wait_multiaddr()
        print(f"{node_a.node_id} <-> {node_b.node_id} connected")

        print("--- baseline: one event, confirm they sync while connected ---")
        node_a.ingest("baseline-hazard")
        wait_for_full_convergence(nodes, expected_total_events=1, timeout_s=15)
        print("baseline synced")

        print("\n--- PARTITION: cutting transport on both sides ---")
        print("(ledger services stay alive - this is a network cut, not a crash)")
        node_a.kill_peer()
        node_b.kill_peer()

        print("--- concurrent divergent ingest while partitioned ---")
        env_a1 = node_a.ingest("hazard-during-partition-from-A-1")
        env_a2 = node_a.ingest("hazard-during-partition-from-A-2")
        env_b1 = node_b.ingest("hazard-during-partition-from-B-1")
        print(f"{node_a.node_id} ingested {env_a1['event_id']}, {env_a2['event_id']} (isolated)")
        print(f"{node_b.node_id} ingested {env_b1['event_id']} (isolated)")

        vec_a = node_a.vector()
        vec_b = node_b.vector()
        print(f"{node_a.node_id} vector during partition: {vec_a}")
        print(f"{node_b.node_id} vector during partition: {vec_b}")
        if vec_a == vec_b:
            raise RuntimeError(
                "nodes still agree after the partition — the transport cut didn't "
                "actually isolate them, this test proved nothing"
            )
        print("confirmed: ledgers have diverged (partition is real, not a no-op)")

        print("\n--- HEALING: restarting transport on both sides ---")
        node_a.start_peer(bootstrap_peers=[])
        addr_a = node_a.wait_multiaddr()
        node_b.start_peer(bootstrap_peers=[addr_a])
        node_b.wait_multiaddr()

        start = time.time()
        # baseline(1) + 2 from A + 1 from B = 4 total
        final = wait_for_full_convergence(nodes, expected_total_events=4, timeout_s=30)
        elapsed = time.time() - start
        print(f"RECONVERGED in {elapsed:.1f}s after healing")

        ids_a = sorted(e["event_id"] for e in final[node_a.node_id])
        ids_b = sorted(e["event_id"] for e in final[node_b.node_id])
        assert ids_a == ids_b, f"event sets differ after convergence: {ids_a} != {ids_b}"
        print(f"both nodes hold the identical 4-event set: {ids_a}")

        print("\n=== PARTITION TEST PASSED: diverged, then reconverged exactly after heal ===")
        return 0

    except Exception as exc:
        print(f"\n=== PARTITION TEST FAILED: {exc} ===")
        print(f"Logs preserved at: {harness_dir}")
        return 1

    finally:
        print("--- cleaning up processes ---")
        for n in nodes:
            n.kill()


if __name__ == "__main__":
    sys.exit(main())
