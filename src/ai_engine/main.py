"""Entrypoint referenced by CLAUDE.md: `python src/ai_engine/main.py`.
Delegates to the Phase 2 ingestion worker — see ingest_worker.py."""
import asyncio
import sys

from .ingest_worker import main

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
