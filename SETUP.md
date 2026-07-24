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

## Ollama (Phase 1+)

Phase 0 uses `AETHER_AI_BACKEND=mock` and does not require Ollama.

For Phase 1+:
1. Install Ollama for Windows from https://ollama.ai
2. Pull the model: `ollama pull phi3:mini` (~2.3 GB)
3. Verify it's running: `curl http://localhost:11434/api/status`
4. Run the worker: `python src/ai_engine/main.py`

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
