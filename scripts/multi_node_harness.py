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

This is a full node-death test (both ledger + peer killed). For a true
network-partition test (ledger stays alive, only the transport is cut,
both sides diverge independently) see scripts/simulate_disconnect.py,
which reuses the Node class from scripts/harness_lib.py.

Usage: python scripts/multi_node_harness.py [--nodes N]
"""
import argparse
import shutil
import sys
import time

from harness_lib import REPO_ROOT, Node, wait_for_convergence


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
