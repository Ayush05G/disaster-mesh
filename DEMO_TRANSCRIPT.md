# Demo Transcript — captured 2026-08-07

Rehearsed fallback in case the live run hiccups during the interview. Both scripts ran
clean, single machine, no hardware. Commands are exactly what's in README.md.

## 1. Cold-start convergence + kill/restart catch-up

```bash
python scripts/multi_node_harness.py --nodes 3
```

```
--- starting 3 ledger services ---
all ledgers healthy
--- starting peers (fan-in bootstrap) ---
node0 listening: /ip4/127.0.0.1/tcp/9100/p2p/12D3KooWBBwQMzQHz9PaDo5aGrF8dpshsrGuuZxmR2yva7ANJfie
node1 listening: /ip4/127.0.0.1/tcp/9101/p2p/12D3KooWBE41W3hLH99Y7inNDMCAQnsSF8BfmcWmMJi8StMkkZbm
node2 listening: /ip4/127.0.0.1/tcp/9102/p2p/12D3KooWBe6EDzoZJ353AK4nFnEnHS9zU8P939ptT6keQxEREUpz
--- cold-start convergence test ---
node0 ingested node0:1
node1 ingested node1:1
node2 ingested node2:1
CONVERGED in 1.4s - all 3 nodes see all 3 events
--- kill/restart catch-up test ---
killing node1...
node0 ingested node0:2 while node1 is down
restarting node1...
RECONVERGED in 1.4s after restart - node1 caught up via anti-entropy

=== M2 PASSED: all exit checks satisfied ===
--- cleaning up processes ---
```

**Talking points while it runs:**
- 3 independent OS processes, each its own ledger service + libp2p peer — this is the real
  code, not a simulation harness with mocked networking.
- Cold start to full convergence: 1.4s.
- Killing node1 mid-run and ingesting elsewhere proves the mesh tolerates a node dropping
  out; restart shows anti-entropy catch-up (pull-the-gap), not a full ledger replay.

## 2. True network partition, divergence, heal, reconverge

```bash
python scripts/simulate_disconnect.py
```

```
--- starting both nodes, connected ---
node0 <-> node1 connected
--- baseline: one event, confirm they sync while connected ---
baseline synced

--- PARTITION: cutting transport on both sides ---
(ledger services stay alive - this is a network cut, not a crash)
--- concurrent divergent ingest while partitioned ---
node0 ingested node0:2, node0:3 (isolated)
node1 ingested node1:1 (isolated)
node0 vector during partition: {'node0': 3}
node1 vector during partition: {'node0': 1, 'node1': 1}
confirmed: ledgers have diverged (partition is real, not a no-op)

--- HEALING: restarting transport on both sides ---
RECONVERGED in 1.0s after healing
both nodes hold the identical 4-event set: ['node0:1', 'node0:2', 'node0:3', 'node1:1']

=== PARTITION TEST PASSED: diverged, then reconverged exactly after heal ===
--- cleaning up processes ---
```

**Talking points while it runs:**
- This is the actual CRDT partition-tolerance property, not just "process survives a
  restart" — the *transport* is cut while both ledger services stay alive, both sides keep
  accepting local writes, and the vectors printed mid-partition prove they've genuinely
  diverged (`{'node0': 3}` vs `{'node0': 1, 'node1': 1'}`).
- Healing reconverges to a byte-identical 4-event set in ~1s — merge is commutative/
  associative/idempotent (G-Set), so order and timing of reconnection never matter.
- This is the mechanism that answers "how does this work without full mesh connectivity":
  a device carrying the ledger between disconnected clusters *is* the transport.

## If asked "what's not verified"

Say directly: mDNS across a real LAN, a real 3-device hotspot demo, and the real
`phi3:mini` extraction-quality number are blocked on hardware / admin rights, not a design
gap. Everything above is the real code path running as separate OS processes — mock mode
only replaces the AI extraction step (`AETHER_AI_BACKEND=mock`), never the ledger or
network layers.
