# Setup & Local Development

## Quick start

```powershell
.\scripts\dev.ps1 venv
.\scripts\dev.ps1 install
.\scripts\dev.ps1 run-mock
```

## Python virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ledger service (Phase 1)

The D4 API contract. Runs on `localhost:8700`, localhost only.

```powershell
uvicorn ai_engine.ledger_service:get_app --factory --host 127.0.0.1 --port 8700
```

`get_app` is a factory (not a module-level `app`) so importing the module never has a
disk side effect — see the docstring in `ledger_service.py` if that seems unusual.

Env vars: `AETHER_NODE_ID` (default `node_local`), `AETHER_DATA_DIR` (default `data/<node_id>`).

## Ollama (Phase 2+)

Phase 0 and Phase 1 use `AETHER_AI_BACKEND=mock` and do not require Ollama.

For Phase 2+:
1. Install Ollama for Windows from https://ollama.ai
2. Pull the model: `ollama pull phi3:mini` (~2.3 GB)
3. Verify it's running: `curl http://localhost:11434/api/status`
4. Run the worker: `python src/ai_engine/main.py`

## P2P mesh transport (Phase 3)

```powershell
cd src\network
npm install
node peer.js
```

Env vars: `AETHER_NODE_ID`, `AETHER_LEDGER_URL` (default `http://127.0.0.1:8700`),
`AETHER_P2P_PORT` (default `9000`), `AETHER_DATA_DIR`, `AETHER_BOOTSTRAP_PEERS`
(comma-separated multiaddrs — supplements mDNS, useful when multicast is blocked).

Dependency versions in `src/network/package.json` are pinned, not `^latest` — gossipsub
hasn't caught up to libp2p's latest major yet, and mixing them breaks gossip silently.
See ROADMAP Phase 3 status before changing any of them.

To exercise the whole transport locally (3-node convergence + kill/restart catch-up),
without needing a second physical machine:
```powershell
python scripts\multi_node_harness.py --nodes 3
```

## Windows Firewall

**Phase 3+ (P2P mesh networking):** Python and Node processes need private-network inbound
access for mDNS multicast. Windows Firewall may silently drop these packets.

To allow them:
1. Windows Defender Firewall → Advanced Settings
2. Inbound Rules → New Rule
3. Program: `python.exe` and `node.exe`
4. Action: Allow
5. Scope: Private networks only

Alternatively, allow both processes via PowerShell (as admin):
```powershell
New-NetFirewallRule -DisplayName "Project Aether Python" -Direction Inbound -Program "C:\Python312\python.exe" -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Project Aether Node" -Direction Inbound -Program "C:\Program Files\nodejs\node.exe" -Action Allow -Profile Private
```

## Linting & testing

```powershell
# Lint Python
flake8 src/ --max-line-length=100

# Run tests
pytest tests/ -v
```

## Git commit

Before committing, verify your local git identity:
```bash
git config user.email
# Must return: ayush2425.rk@gmail.com
```

Commit with conventional scope:
```bash
git commit -m "feat(ai-engine): add MockHazardExtractor"
```

Never add co-author trailers or "Generated with Claude" markers.
