# Project Aether: Autonomous Edge-AI Mesh Network

## Project Overview
An internet-independent, decentralized network for disaster response. The system deploys quantized Small Language Models (SLMs) on edge devices (laptops, Raspberry Pis, mobile phones) to analyze local emergency data (images/text) offline and sync information across devices peer-to-peer (P2P) using a mesh routing architecture.

## Tech Stack
- **Edge AI Engine:** Python 3.11+ (3.12.10 installed), Ollama API — local execution of Phi-3 or Llama-3-8B quantized models.
- **Networking Layer:** **Node.js + js-libp2p** (decision D1, ROADMAP.md) for mDNS peer discovery and gossipsub routing. V1 targets a shared LAN segment (hotspot/router); AP-less ad-hoc Wi-Fi is backlog. A Go rewrite of the transport is the recorded fallback only if Raspberry Pi RAM proves tight in Phase 6.
- **Data Sync Layer:** **G-Set CRDT of immutable hazard events** (append-only, merge = set union — see ROADMAP scope decisions). Python owns all ledger state (D2); the Node transport is a stateless relay talking to the ledger service on `localhost:8700`.
- **Frontend / Visualizer:** React.js dashboard showing local mesh status and detected spatial map hazards.

## System Architecture Map

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

## Critical Rules & Technical Constraints

1. **Absolute Offline Operation.** Do NOT write code that fetches external CDN assets, cloud AI APIs (OpenAI/Anthropic), Google Fonts, remote map tiles, or any third-party web dependency at runtime. Everything resolves locally, from disk. A node with its radio pointed at nothing but other nodes must work identically.

2. **Deterministic Schemas.** All AI model extractions are typed and parsed strictly with `pydantic`. This is the canonical hazard contract:
   ```json
   {
     "node_id": "string",
     "timestamp": "ISO-8601 string",
     "hazard_type": "string",
     "severity": "LOW|MEDIUM|HIGH",
     "coordinates": {"lat": 0.0, "lng": 0.0}
   }
   ```
   Source of truth is `src/ai_engine/schemas.py` (pydantic), mirrored to `src/shared/schema.json` for the Node and React layers. **Divergence between the two is a bug, not a variation.** Never loosen a field to make a parse succeed — fix the extraction.

   This JSON is the *payload only*. In the ledger it is wrapped in the envelope defined in ROADMAP D5 — `{event_id: "node:seq", node_id, seq, lamport, payload}`. Identity is `(node_id, seq)` and ordering is the Lamport clock; the payload's `timestamp` is **display metadata only** — offline devices have no NTP, so wall-clock time is never identity and never merge order.

3. **No Central Database Engines.** File-based storage and in-memory CRDT state only. Do not spin up Docker containers for PostgreSQL, MongoDB, Redis, or a message broker. Synchronization happens directly over `libp2p` streaming pipes.

## Core Commands & Workflows

### AI Engine (Python)
```bash
python -m venv .venv                 # once
.venv\Scripts\activate               # PowerShell; use source .venv/bin/activate in Git Bash
pip install -r requirements.txt      # ollama, pydantic, fastapi, uvicorn, pytest
ollama pull phi3:mini                # once — model is cached on disk
python src/ai_engine/main.py         # start the local ingestion worker
```
Set `AETHER_AI_BACKEND=mock` to run the ingestion worker against `MockHazardExtractor` with no Ollama process at all. Every phase after 0 must stay runnable in mock mode.

### P2P Mesh Network (Node.js — decision D1)
```bash
npm install libp2p @libp2p/mdns @libp2p/tcp @chainsafe/libp2p-gossipsub
node src/network/peer.js
```

### Quality Assurance & Validation
```bash
flake8 src/                          # Python lint
npm run lint                         # Node lint
pytest tests/                        # Python tests
bash scripts/simulate_disconnect.sh  # partition test — needs Git Bash on Windows
```

## Git & Commit Rules

1. **Single identity, always.** Every commit in this repo is authored by `ayush05g <ayush2425.rk@gmail.com>`. The machine's global identity is a different (work) account, so this is pinned repo-locally:
   ```bash
   git config user.name  "ayush05g"
   git config user.email "ayush2425.rk@gmail.com"
   ```
   Verify with `git log -1 --format='%an <%ae>'` before any push. Never author a commit under any other name or address.
2. **No AI co-authorship.** Never append a `Co-Authored-By: Claude ...` trailer, never add "Generated with Claude Code", and no 🤖 markers in commit messages or PR bodies. Commit messages read as written by the human author of record, because that is who the author of record is.
3. **Never commit or push unless explicitly asked.** No auto-commit when a task finishes.
4. **Conventional commits, scoped by subsystem:** `feat(ai-engine):`, `fix(network):`, `chore(dashboard):`, `docs:`, `test:`.
5. **Never commit directly to `main`.** Branch as `phase-N/<short-slug>`.
6. **Never `--no-verify`.** Do not bypass hooks or signing. If a hook fails, fix the cause.

## Working Agreement (Claude)

1. **Phased delivery.** Work only within the current phase in `ROADMAP.md`. Good ideas that fall outside it get appended to `BACKLOG.md` — captured, not implemented.
2. **Model per phase is pre-agreed in ROADMAP.md.** State the phase's model before starting and wait for confirmation, but do not re-litigate it — planning was done once, exhaustively, on Fable 5. Switch to a heavier model **only** when that phase's listed escalation trigger fires, and say which trigger fired. This is a hard rule — it exists specifically to avoid token waste.
3. **Every phase ends runnable.** No phase may leave the repo in a state where the linters fail or an entrypoint won't start.
4. **Offline is testable, not aspirational.** Justify each new dependency against Rule 1. If it phones home at runtime, it is rejected — find a vendored alternative.
5. **Ask before scaffolding a new subsystem.** Do not invent directory structure or a module layout unilaterally.
6. **Edge hardware is the target, not the laptop.** A change that is fine at 32 GB RAM and fails on a Pi is a failed change.

## Code Guidelines & Standards

- Keep modules small and lightweight. Edge hardware has strict RAM/CPU throttling.
- **Explicit timeouts everywhere.** Every local socket bind, P2P stream, and model call carries an explicit timeout (`timeout=5.0` baseline). An un-timed await is a node that hangs forever in the field.
- **Never use wall-clock time for ordering or identity.** No NTP exists offline; clocks drift, reset, and lie. Ordering is Lamport, identity is `(node_id, seq)`. A clock set backwards must be a non-event.
- Favor asynchronous paradigms: Python `asyncio` for model querying, the JS event loop for `libp2p` connection hooks.
- Fail loud and local: log to disk with the `node_id`, never swallow an exception to keep a loop alive silently.
- No secrets, no API keys, no telemetry. There is nothing to authenticate to.
