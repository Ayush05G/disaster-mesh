import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Optional, Protocol

import ollama
from pydantic import ValidationError

from .schemas import HazardPayload


class HazardExtractor(Protocol):
    """D7: extractor interface — mock and real are interchangeable."""

    async def extract(self, text: str) -> HazardPayload | None:
        """Extract a hazard from text. Returns None if no hazard detected."""
        ...


class ExtractionError(Exception):
    """Non-fatal: model unreachable, timed out, or produced unparseable
    output after the retry budget is exhausted. The caller must catch this,
    quarantine the raw input, and keep running — a flaky model must never
    kill the ingestion worker (CLAUDE.md 'fail loud and local')."""


class MockHazardExtractor:
    """Deterministic, seedable mock. Emits exactly one hazard per input."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.call_count = 0

    async def extract(self, text: str) -> HazardPayload:
        """Generate a deterministic hazard from any input."""
        self.call_count += 1

        hazard_types = ["flooding", "fire", "collapse", "gas_leak", "contamination"]
        severities = ["LOW", "MEDIUM", "HIGH"]

        hazard_type = self.rng.choice(hazard_types)
        severity = self.rng.choice(severities)

        lat = self.rng.uniform(-90, 90)
        lng = self.rng.uniform(-180, 180)

        return HazardPayload(
            node_id="node_mock",
            timestamp=datetime.now(timezone.utc).isoformat(),
            hazard_type=hazard_type,
            severity=severity,
            coordinates={"lat": lat, "lng": lng}
        )


def _build_prompt(text: str) -> str:
    return (
        "Extract a single hazard report from this disaster-response field text. "
        "Respond with hazard_type, severity (LOW, MEDIUM, or HIGH), and "
        "coordinates (lat, lng — estimate if not stated explicitly).\n\n"
        f"Text: {text}"
    )


def _build_retry_prompt(text: str, error: Exception) -> str:
    return (
        f"{_build_prompt(text)}\n\n"
        f"Your previous response was invalid: {error}\n"
        "Return ONLY valid JSON matching the required schema."
    )


class OllamaHazardExtractor:
    """Real extractor: Ollama structured outputs (format=JSON schema) rather
    than prompt-and-pray. One bounded retry on validation failure, with the
    error fed back into the follow-up prompt. Any connectivity/timeout
    failure, or a second validation failure, raises ExtractionError — the
    ingestion worker is responsible for quarantining and continuing."""

    def __init__(
        self,
        model: str = "phi3:mini",
        host: str = "http://localhost:11434",
        timeout: float = 5.0,
    ):
        self.model = model
        self.timeout = timeout
        self._client = ollama.AsyncClient(host=host, timeout=timeout)

    async def extract(self, text: str) -> Optional[HazardPayload]:
        schema = HazardPayload.model_json_schema()

        try:
            raw = await self._generate(_build_prompt(text), schema)
        except (asyncio.TimeoutError, ollama.ResponseError, ConnectionError, OSError) as exc:
            raise ExtractionError(f"model unreachable or timed out: {exc}") from exc

        first_error: Exception
        try:
            return HazardPayload.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            # `except ... as name` auto-deletes `name` once the block ends,
            # so it must be reassigned to a variable that survives to the
            # retry prompt built below.
            first_error = exc

        try:
            raw_retry = await self._generate(_build_retry_prompt(text, first_error), schema)
        except (asyncio.TimeoutError, ollama.ResponseError, ConnectionError, OSError) as exc:
            raise ExtractionError(f"model unreachable or timed out on retry: {exc}") from exc

        try:
            return HazardPayload.model_validate(json.loads(raw_retry))
        except (json.JSONDecodeError, ValidationError) as second_error:
            raise ExtractionError(
                f"model output failed validation twice: {second_error}"
            ) from second_error

    async def _generate(self, prompt: str, schema: dict) -> str:
        response = await asyncio.wait_for(
            self._client.generate(model=self.model, prompt=prompt, format=schema, stream=False),
            timeout=self.timeout,
        )
        return response["response"]
