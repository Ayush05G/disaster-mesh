import random
from datetime import datetime, timezone
from typing import Protocol

from .schemas import HazardPayload


class HazardExtractor(Protocol):
    """D7: extractor interface — mock and real are interchangeable."""

    async def extract(self, text: str) -> HazardPayload | None:
        """Extract a hazard from text. Returns None if no hazard detected."""
        ...


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
