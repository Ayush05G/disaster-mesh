"""
Ingestion worker (ROADMAP Phase 2): extract -> POST /ingest against the
Phase 1 ledger service. Same code path regardless of AETHER_AI_BACKEND —
only the extractor differs between mock and real (Ollama) mode.

The ledger service is a separate process (D3 topology); this worker never
touches the JSONL directly, only the D4 REST API on localhost.
"""
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import httpx

from .extractor import ExtractionError, HazardExtractor, MockHazardExtractor

LOGGER = logging.getLogger("aether.ingest_worker")

DEMO_FEED = [
    "Flooding reported downtown, water rising fast near Main St bridge",
    "Fire spotted in the old warehouse district, heavy smoke visible",
    "Building showing cracks after the tremor, residents evacuating",
    "Strong gas smell reported near the school, evacuation underway",
    "Water contamination alert issued for the northern well supply",
]


class IngestWorker:
    """extract -> POST /ingest. Never raises out of process() — any failure
    (bad model output, unreachable model, unreachable ledger) is quarantined
    to disk and logged. A flaky dependency or one bad input must not kill
    the worker loop (CLAUDE.md 'fail loud and local')."""

    def __init__(
        self,
        extractor: HazardExtractor,
        ledger_client: httpx.AsyncClient,
        quarantine_dir: Path,
        node_id: str,
    ):
        self.extractor = extractor
        self.ledger_client = ledger_client
        self.quarantine_dir = Path(quarantine_dir)
        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        self.node_id = node_id

    async def process(self, text: str) -> Optional[dict]:
        try:
            payload = await self.extractor.extract(text)
        except ExtractionError as exc:
            self._quarantine(text, reason=f"extraction failed: {exc}")
            LOGGER.warning("[%s] quarantined (extraction failed): %s", self.node_id, exc)
            return None

        if payload is None:
            self._quarantine(text, reason="extractor found no hazard")
            return None

        try:
            resp = await self.ledger_client.post("/ingest", json=payload.model_dump())
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            self._quarantine(text, reason=f"ledger post failed: {exc}")
            LOGGER.error("[%s] quarantined (ledger unreachable): %s", self.node_id, exc)
            return None

        return resp.json()

    def _quarantine(self, text: str, reason: str) -> None:
        record = {"node_id": self.node_id, "text": text, "reason": reason}
        # uuid4 for filename uniqueness — not wall-clock-derived. Nothing in
        # this codebase uses time for identity or ordering (CLAUDE.md).
        path = self.quarantine_dir / f"{uuid.uuid4().hex}.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")


async def run_feed(worker: IngestWorker, feed: list[str]) -> list[Optional[dict]]:
    return [await worker.process(text) for text in feed]


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    backend = os.getenv("AETHER_AI_BACKEND", "mock")
    node_id = os.getenv("AETHER_NODE_ID", "node_local")
    ledger_url = os.getenv("AETHER_LEDGER_URL", "http://127.0.0.1:8700")
    quarantine_dir = Path(os.getenv("AETHER_DATA_DIR", f"data/{node_id}")) / "quarantine"

    extractor: HazardExtractor
    if backend == "mock":
        extractor = MockHazardExtractor(seed=42)
    elif backend == "ollama":
        from .extractor import OllamaHazardExtractor
        extractor = OllamaHazardExtractor()
    else:
        print(f"ERROR: unknown AETHER_AI_BACKEND={backend!r} (expected 'mock' or 'ollama')")
        return 1

    async with httpx.AsyncClient(base_url=ledger_url, timeout=5.0) as client:
        try:
            health = await client.get("/health")
            health.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"ERROR: ledger service unreachable at {ledger_url}: {exc}")
            print(
                "Start it first: uvicorn ai_engine.ledger_service:get_app "
                "--factory --host 127.0.0.1 --port 8700"
            )
            return 1

        worker = IngestWorker(extractor, client, quarantine_dir, node_id)
        results = await run_feed(worker, DEMO_FEED)

    succeeded = sum(1 for r in results if r is not None)
    quarantined = len(DEMO_FEED) - succeeded
    print(
        f"[ingest_worker:{backend}] processed {len(DEMO_FEED)} inputs, "
        f"{succeeded} hazards ingested, {quarantined} quarantined"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
