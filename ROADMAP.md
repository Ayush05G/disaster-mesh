# Project Aether — Roadmap (v3, master plan — final)

Seven phases, three demo milestones. All design decisions are **closed** — recorded below
as D1–D7. Execution phases run on cheap models by default; heavyweight models are pulled
in only on the pre-agreed escalation triggers, never for re-planning. Ideas that surface
mid-phase go to [BACKLOG.md](BACKLOG.md), not into the working tree.

## Closed decisions

**D1 — Transport language: Node.js** (js-libp2p). Already installed (v24); js-libp2p has
maintained mDNS + gossipsub modules; shares a language with the dashboard. Go's one real
advantage (single-binary Pi deploy) only matters in Phase 6, where Node on Pi OS 64-bit
is adequate — a Go rewrite of the transport is the recorded fallback if Pi RAM proves tight.

**D2 — Ledger ownership: Python owns all ledger state.** The Node transport is a
stateless relay; it never touches the JSONL. One writer, no file locking, no duplicated
merge logic across languages. All cross-process traffic goes through a localhost-only
FastAPI service.

**D3 — Per-node process topology (3 processes + dashboard):**
```
[ingest worker (py)] ──► [ledger service (py): G-Set + JSONL + FastAPI :8700]
                                   ▲ localhost REST          ▲
[transport peer (node): mDNS + gossipsub] ────────────────────┘
[dashboard (react/vite)] ──reads──► :8700
```

**D4 — Ledger service API** (frozen in Phase 1; every later phase codes against it):
| Endpoint | Purpose |
|---|---|
| `GET  /vector` | `{node_id: max_seq, ...}` — this node's view |
| `GET  /events?since=<vector>` | events the caller lacks (anti-entropy pull) |
| `POST /events` | batch merge of remote events — idempotent, G-Set union |
| `POST /ingest` | local hazard payload in → envelope assigned, appended, returned |
| `POST /peers/heartbeat` / `GET /peers` | transport reports peer status; dashboard reads |
| `GET  /health` | liveness |

**D5 — Event envelope.** The wire schema in CLAUDE.md is the *payload*; identity and
ordering live in the envelope, never in the payload:
```json
{"event_id": "nodeA:42", "node_id": "nodeA", "seq": 42, "lamport": 107, "payload": { ...hazard... }}
```

**D6 — Sync protocol:** live events over gossipsub topic `aether/hazards/v1`; on peer
connect and every 30 s, exchange vectors and pull only the gap (anti-entropy). A rejoining
node catches up without replaying the world.

**D7 — Extractor interface** (frozen in Phase 0; mock and real are interchangeable):
```python
class HazardExtractor(Protocol):
    async def extract(self, text: str) -> HazardPayload | None: ...
```

## Scope decisions

1. **V1 network = shared LAN segment** (phone hotspot or router). True AP-less ad-hoc
   Wi-Fi is a backlog item, not the critical path; libp2p doesn't care what layer 2 is.
2. **No wall-clock trust.** Offline devices have no NTP. `timestamp` is display metadata —
   never identity, never merge order. Identity = `(node_id, seq)`; causality = Lamport.
3. **Hazard reports are immutable events** → the core CRDT is a **G-Set** (trivially
   commutative/associative/idempotent). LWW machinery enters only if mutable status is
   ever added (backlog).
4. **Mock-first AI.** `AETHER_AI_BACKEND=mock` works in every phase; no test requires a
   2.3 GB model to be loaded.

## Model plan

| Phase | Model | Escalation trigger (pre-agreed — not a judgment call in the moment) |
|---|---|---|
| 0 | **Haiku 4.5** | none expected |
| 1 | **Sonnet 5** | → Opus 4.8 if property tests reveal a *design* flaw (not an impl bug) |
| 2 | **Sonnet 5** | → Opus 4.8 if extraction < 95% on eval after two prompt iterations |
| 3 | **Sonnet 5** | → Opus 4.8 the moment a convergence test flaps non-deterministically |
| 4 | **Sonnet 5** | → Fable 5 only if visual polish becomes an explicit goal |
| 5 | **Sonnet 5** | → Opus 4.8 for any chaos failure undiagnosed after one session |
| 6 | **Haiku 4.5 / Sonnet 5** | → Opus 4.8 only for Pi-specific performance mysteries |

Fable 5: planning is done; never again unless the architecture itself must change.

## Dependency graph & milestones

```
Phase 0 ──► Phase 1 ──► Phase 2 ──► [M1: single node end-to-end, mock + real AI]
               │
               └──────► Phase 3 ──► [M2: 3 nodes converge on one machine]
                            │
Phase 2 ────────────────────┤
                            ▼
                        Phase 4 ──► Phase 5 ──► [M3: 3-device live demo with mid-demo partition]
                                        │
                                        ▼
                                    Phase 6 ──► [M3 rerun with a Raspberry Pi as node B]
```

Phase 3 depends only on Phase 1 (it syncs ledgers, not AI output): if Phase 2 stalls,
transport work proceeds in parallel.

---

## Phase 0 — Foundation *(Haiku 4.5)*

- `requirements.txt` (ollama, pydantic, fastapi, uvicorn, pytest, hypothesis, flake8) + venv
- `MockHazardExtractor` — deterministic, seedable, behind D7 (interface frozen here)
- Mock-mode entrypoint: `AETHER_AI_BACKEND=mock python src/ai_engine/main.py`
- `scripts/dev.ps1` (venv activate / lint / test helpers — daily driver is PowerShell)
- Ollama for Windows install + `ollama pull phi3:mini` (~2.3 GB, explicit OK first);
  confirm `localhost:11434`
- Firewall note documented: Python/Node need private-network inbound for Phase 3 mDNS
- First commit on `phase-0/foundation` — identity verified before committing

**Exit:** mock entrypoint emits N valid hazards and exits 0; `pytest` + `flake8 src/`
green; `git log -1 --format='%an <%ae>'` → `ayush05g <ayush2425.rk@gmail.com>`, no AI trailer.

## Phase 1 — Schema, Ledger Core & Ledger Service *(Sonnet 5)*

- `src/ai_engine/schemas.py` — pydantic v2: payload + D5 envelope
- `src/shared/schema.json` generated from `model_json_schema()`; committed; drift test
  asserts committed == generated
- G-Set ledger, append-only JSONL: fsync per append; torn-final-line detected and
  truncated on load; dedup on `event_id`; merge = set union + Lamport max
- Per-node `seq` persisted separately — restart never reuses an id
- FastAPI ledger service implementing **D4** on `:8700` (localhost only)
- Hypothesis property tests: merge commutative/associative/idempotent; random batch
  permutations converge; truncate-at-every-byte crash recovery loses no complete event
- Watch: OneDrive sync vs fsync — if it bites, move `data/` out of OneDrive scope

**Exit:** property tests green; 10k-event ledger load measured within a Pi-ish memory
budget (record the number).

**Measured (this laptop, Python 3.12.10):** 10k events cold-load in 0.2s, 41 MB RSS delta
(single Ledger instance, isolated process), 2.16 MB on disk. Comfortably inside a 2 GB Pi
budget even with headroom for the other two processes. Write throughput is ~157
events/sec (6.4 ms/event) — the cost of fsync-per-append, a deliberate crash-safety
tradeoff (see `_append_to_disk`). Fine for hazard-reporting cadence; would need revisiting
only if a single node's *local* ingest rate ever needed to sustain >100 events/sec, which
this project doesn't anticipate. Unbounded event growth over a long deployment remains a
backlog item (ledger compaction).

## Phase 2 — Edge AI Engine *(Sonnet 5)*

- Async Ollama client, `timeout=5.0`, **structured outputs** (`format` = payload JSON
  schema) — the biggest reliability lever, not prompt-and-pray
- Pipeline: extract → pydantic validate → one bounded retry with the validation error fed
  back → on second failure, quarantine raw input to `data/quarantine/` and keep running.
  A flaky model must never kill the worker.
- Ingestion worker posts to `POST /ingest`; identical code path in mock and real mode
- Eval: ~20 fixture inputs with expected hazards; pass rate recorded

**Exit:** worker survives model-off / model-slow / garbage-output; **M1** — sensor text
in, valid hazard in ledger, mock *and* real.

## Phase 3 — P2P Mesh Transport *(Sonnet 5 — Node.js per D1)*

- js-libp2p peer: mDNS discovery, gossipsub `aether/hazards/v1`
- D6 anti-entropy against the D4 API; explicit timeouts on every stream and dial
- Multi-node-on-one-machine harness: N nodes, distinct ports + data dirs — this harness
  is what makes Phase 5 automatable

**Exit:** 3 local nodes converge from cold start; kill one mid-gossip → restart → catches
up via anti-entropy; mDNS verified against a second physical machine (the firewall check);
**M2**.

## Phase 4 — React Dashboard *(Sonnet 5)*

- Vite + React, every asset vendored; build audit script greps `dist/` for `https?://`
  and **fails the build** on any hit — Critical Rule 1 as a test, not a promise
- MapLibre GL + local PMTiles extract of the demo region (pick the region at phase start;
  the extract is a sized download)
- Peer status panel, hazard layer with severity filter, ledger event feed
- Reads only `localhost:8700`

**Exit:** fully functional with networking disabled; devtools shows zero non-localhost
requests; renders 1k hazards without jank.

## Phase 5 — Resilience & Validation *(Sonnet 5)*

- `scripts/simulate_disconnect.sh` driving the Phase 3 harness: partition → concurrent
  ingest on both sides → heal → assert identical converged ledgers
- Chaos matrix: node crash mid-write; clock set backwards (**must be a non-event**, per
  scope decision 2); duplicate event injection; slow peer
- RAM/CPU profile per component; numbers in the README
- README + scripted demo

**Exit:** chaos matrix green; **M3** — 3 devices on a hotspot, hazard reported on A
appears on C's map; B partitioned mid-demo with ingest on both sides, rejoins, converges —
reproducible from the README alone.

## Phase 6 — Edge Hardware Deployment *(Haiku 4.5 / Sonnet 5; optional but recommended)*

The phase that makes the project's premise true — until here, "edge device" meant a laptop.

- Raspberry Pi 4 (2 GB) bring-up: install script for Python + Node + Ollama ARM64
  (or mock-only if phi3 doesn't fit in 2 GB — measure, decide, record the decision here)
- systemd units for the three processes; boot-to-meshed with no keyboard
- Re-run the Phase 5 profile on real hardware; Go transport rewrite is the recorded
  fallback if Node RAM is tight

**Exit:** Pi joins the mesh from power-on unattended; M3 rerun with the Pi as node B.

---

## Risk register

| Risk | Phase | Mitigation |
|---|---|---|
| Windows Firewall silently drops mDNS multicast | 3 | Documented in Phase 0; second-physical-machine exit check in Phase 3 |
| phi3:mini extraction quality too low | 2 | Structured outputs first; eval fixtures; pre-agreed Opus escalation; llama3:8b fallback if RAM allows |
| OneDrive sync fights JSONL fsync / file locks | 1 | Crash tests surface it early; if it bites, move `data/` out of OneDrive scope and document |
| Clock skew corrupts ordering | 1 | Designed out: Lamport + `(node_id, seq)` identity; chaos-tested in Phase 5 |
| True ad-hoc Wi-Fi expectation creep | 3 | Scope decision 1; backlog, not critical path |
| Offline map tiles ambush Phase 4 | 4 | Region + PMTiles decided at phase start |
| phi3 doesn't fit Pi 4 2 GB | 6 | Mock-only Pi node is acceptable — Pi still meshes and displays; record the measurement |

## Explicitly not phases (backlog)

Mobile-phone nodes · BLE transport · AP-less ad-hoc Wi-Fi · image/vision input · signed
hazard reports · mutable hazard status (the LWW add-on) · severity-priority gossip ·
ledger compaction · CI runner. Each is additive; none changes D1–D7 — which is what makes
deferring them safe.
