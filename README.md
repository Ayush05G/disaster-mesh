# Project Aether

An internet-independent, decentralized network for disaster response. Quantized
Small Language Models on edge devices extract structured hazard reports from local
text/image input, offline; a G-Set CRDT ledger syncs those reports peer-to-peer over a
libp2p mesh; a local dashboard shows the merged result. No central server, no internet
dependency, no wall-clock trust.

Full design decisions, phase history, and the risk register live in
[ROADMAP.md](ROADMAP.md). Project rules and constraints live in [CLAUDE.md](CLAUDE.md).
Setup instructions per component live in [SETUP.md](SETUP.md). Deferred ideas live in
[BACKLOG.md](BACKLOG.md).

## Architecture

```
              [ Local Camera / Sensor Feed ]
                          │
                          ▼   (runs fully offline)
        [ Quantized Local SLM — Ollama Python Client ]
                          │
                          ├──────► emits structured hazard JSON
                          ▼   (P2P mDNS discovery / local Wi-Fi)
              [ libp2p Transport Layer ]
                          │
                          ├──────► broadcasts & syncs to nearby nodes
                          ▼   (no central server)
        [ CRDT-Merged Ledger  ──►  React Map Dashboard ]
```

Three processes per node, talking only over localhost REST (D4 API) and the P2P mesh:

```
[ingest worker (py)] ──► [ledger service (py): G-Set + JSONL + FastAPI :8700]
                                   ▲ localhost REST          ▲
[transport peer (node): mDNS + gossipsub] ────────────────────┘
[dashboard (react/vite)] ──reads──► :8700
```

## Quick start

See [SETUP.md](SETUP.md) for full details. Summary, one node:

```bash
# 1. Python side
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn ai_engine.ledger_service:get_app --factory --host 127.0.0.1 --port 8700 &
AETHER_AI_BACKEND=mock python src/ai_engine/main.py    # ingests a demo feed

# 2. Network side
cd src/network && npm install && node peer.js &

# 3. Dashboard
cd src/dashboard && npm install && npm run dev
```

## Demo: multi-node convergence and partition tolerance (single machine)

The real M3 milestone — three physical devices on a shared hotspot — needs hardware this
environment doesn't have (see "What's blocked" below). What *is* fully scripted and
verified is the same mesh logic running as multiple processes on one machine:

```bash
# Cold-start convergence + kill/restart catch-up (3 nodes)
python scripts/multi_node_harness.py --nodes 3

# True network partition: ledgers stay alive, only the transport is cut,
# both sides diverge independently, then heal and reconverge exactly
python scripts/simulate_disconnect.py
# or: bash scripts/simulate_disconnect.sh
```

Expected output (abbreviated):

```
--- cold-start convergence test ---
CONVERGED in ~2s - all 3 nodes see all 3 events
--- kill/restart catch-up test ---
RECONVERGED in ~2s after restart - node1 caught up via anti-entropy
=== M2 PASSED: all exit checks satisfied ===
```

```
--- PARTITION: cutting transport on both sides ---
--- concurrent divergent ingest while partitioned ---
confirmed: ledgers have diverged (partition is real, not a no-op)
--- HEALING: restarting transport on both sides ---
RECONVERGED in ~1s after healing
both nodes hold the identical 4-event set
=== PARTITION TEST PASSED: diverged, then reconverged exactly after heal ===
```

To see it visually: start one node's ledger service + a few `POST /ingest` calls (or run
the harness and point `AETHER_LEDGER_URL`/the dashboard's Vite proxy at one of its ports),
then `npm run dev` in `src/dashboard`. The map, peer panel, and event feed update live.

## Store-and-forward: how reports spread without a continuous network

Aether does **not** assume every device can reach every other device. In a real
disaster they can't: V1 connects nodes over a shared LAN segment (a hotspot or router),
so devices outside that segment have no IP path at all — and no gossip protocol can
invent a physical link that isn't there.

What makes the system still work is that the ledger is a **grow-only CRDT (G-Set)**, so
merge is commutative, associative, and idempotent. Two nodes reconcile correctly
whenever they happen to meet — in any order, after any gap, any number of times. That
turns a device that physically moves between disconnected clusters into a transport in
its own right: it carries everything it holds and hands it over on the next contact.
A report authored by node A can reach node D having never had an end-to-end path,
because a rescue worker's phone synced with A at one location and D at another.

The dashboard's **Store & Forward** panel makes this visible:

| Shown | Meaning |
|---|---|
| Authored here | Reports this device originated itself |
| Carried for others | Reports received from elsewhere in the mesh, retained for onward delivery |
| Peers in range | Peers currently heartbeating (live connections) |
| Posture line | Interprets the combination — e.g. *"Carrying 11 reports from 2 other nodes with no peer in range — will forward on next contact."* |

**What is tracked:** which node originally authored each report (`node_id`, `seq`) and
its causal order (`lamport`). **What is not:** the route a report travelled, which peer
relayed it, or when it arrived. The D5 envelope records origin and ordering only — the
dashboard deliberately does not claim a delivery path the system never observed.

The gap this leaves is bridging clusters *without* a human carrying the device. That
needs a transport that relays at short range on its own — BLE mesh or LoRa — both
tracked in [BACKLOG.md](BACKLOG.md), neither built.

## Chaos matrix

```bash
pytest tests/test_chaos_clock_skew.py tests/test_chaos_duplicate_injection.py tests/test_chaos_concurrent_ingest.py -v
python scripts/chaos_crash_mid_write.py --iterations 5
node src/network/chaos-slow-peer-test.mjs
```

Each proves a specific resilience property against the real code, not a mock:
- **Clock skew is a non-event** — backwards/scrambled wall-clock timestamps have zero
  effect on merge order or identity (Lamport + `(node_id, seq)` only).
- **Duplicate injection stays idempotent** — including under genuine concurrent replay.
- **Concurrent local ingest never collides** — this chaos run is what found and fixed a
  real thread-safety bug (see ROADMAP Phase 5 status).
- **A crashed node (`SIGKILL`) never loses an acknowledged write or invents a phantom
  one** — verified against a live process under real concurrent write pressure.
- **A hung/slow peer cannot block the caller past its timeout** — this chaos run is what
  found and fixed a real missing-timeout bug on the anti-entropy read path.

## Full test suite

```bash
pytest tests/                          # Python: 35 tests
flake8 src/ai_engine tests/ scripts/    # Python lint
cd src/network && npm run lint          # Node lint
cd src/dashboard && npm run lint        # Dashboard lint
cd src/dashboard && npm run build       # Build + offline audit (fails on any external URL)
```

## What's blocked pending real hardware or admin access

Recorded honestly rather than glossed over — each is a specific, resolvable blocker, not
a design gap:

| Item | Needs | Phase |
|---|---|---|
| Real `phi3:mini` extraction quality eval | Ollama install (admin rights) | 0/2 |
| mDNS peer discovery across a real LAN | A second physical machine | 3 |
| M3: 3 devices on a real hotspot, live partition mid-demo | 3 physical devices | 5 |
| Pi 4 profile numbers, boot-to-meshed | A Raspberry Pi | 6 |

Everything else in the roadmap is verified end-to-end in this environment.

## Git

Every commit is authored by `ayush05g <ayush2425.rk@gmail.com>` (repo-local git config —
see CLAUDE.md). No AI co-authorship trailers. Branches are `phase-N/<slug>`.
