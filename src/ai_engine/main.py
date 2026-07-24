import asyncio
import os
from .extractor import MockHazardExtractor


async def main():
    """Phase 0 entrypoint: mock-mode ingestion worker."""
    backend = os.getenv("AETHER_AI_BACKEND", "mock")

    if backend != "mock":
        print(f"ERROR: Phase 0 only supports mock mode; got {backend}")
        return 1

    print("[Phase 0 mock] Starting ingestion worker...")
    extractor = MockHazardExtractor(seed=42)

    # Emit 5 test hazards
    test_inputs = [
        "Flooding reported downtown",
        "Fire in the warehouse",
        "Building collapse risk",
        "Gas leak detected",
        "Water contamination alert"
    ]

    for text in test_inputs:
        hazard = await extractor.extract(text)
        print(f"  [OK] {text} -> {hazard.hazard_type} ({hazard.severity})")

    print(f"[Phase 0 mock] Generated {extractor.call_count} hazards. Exit 0.")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
