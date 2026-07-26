"""
Extraction eval harness (ROADMAP Phase 2 exit check): run the ~20 fixtures
in tests/fixtures/hazard_eval_fixtures.json through a HazardExtractor and
report a pass rate.

A fixture passes when extraction succeeds, hazard_type contains one of the
fixture's acceptable keywords (hazard_type is free text, not an enum — an
exact-string match would be too strict for real model output), and severity
matches exactly (severity IS a constrained LOW/MEDIUM/HIGH field).

Usage:
  python scripts/run_eval.py            # mock backend (harness smoke test only —
                                          # see note below)
  python scripts/run_eval.py --backend ollama

NOTE: MockHazardExtractor ignores input text and returns a random hazard
deterministically from a seed. Running this harness against it proves the
harness itself works — it is NOT a measurement of extraction quality. The
real pass-rate number (the one the Phase 2 escalation trigger reads) only
exists once this is run with --backend ollama against phi3:mini.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_engine.extractor import (  # noqa: E402
    ExtractionError,
    HazardExtractor,
    MockHazardExtractor,
)

FIXTURES_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hazard_eval_fixtures.json"
)


def load_fixtures() -> list[dict]:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


def scores(payload, fixture: dict) -> tuple[bool, str]:
    hazard_type = payload.hazard_type.lower()
    keywords = fixture["hazard_type_keywords"]
    type_ok = any(kw.lower() in hazard_type for kw in keywords)
    severity_ok = payload.severity == fixture["expected_severity"]

    if type_ok and severity_ok:
        return True, "pass"
    reasons = []
    if not type_ok:
        reasons.append(f"hazard_type={hazard_type!r} not in {keywords}")
    if not severity_ok:
        reasons.append(f"severity={payload.severity!r} != {fixture['expected_severity']!r}")
    return False, "; ".join(reasons)


async def run(extractor: HazardExtractor, fixtures: list[dict]) -> None:
    passed = 0
    for i, fixture in enumerate(fixtures, 1):
        try:
            payload = await extractor.extract(fixture["text"])
        except ExtractionError as exc:
            print(f"[{i:2}] FAIL  extraction error: {exc}")
            continue

        if payload is None:
            print(f"[{i:2}] FAIL  no hazard extracted for: {fixture['text'][:50]}")
            continue

        ok, detail = scores(payload, fixture)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{i:2}] {status}  {detail if not ok else fixture['text'][:50]}")

    total = len(fixtures)
    print(f"\n{passed}/{total} passed ({passed / total * 100:.1f}%)")


def main() -> int:
    backend = "mock"
    if "--backend" in sys.argv:
        backend = sys.argv[sys.argv.index("--backend") + 1]

    fixtures = load_fixtures()

    if backend == "mock":
        print("NOTE: mock backend ignores input text - this is a harness smoke test,")
        print("      not a real extraction-quality measurement. Use --backend ollama.\n")
        extractor: HazardExtractor = MockHazardExtractor(seed=42)
    elif backend == "ollama":
        from ai_engine.extractor import OllamaHazardExtractor
        extractor = OllamaHazardExtractor()
    else:
        print(f"Unknown backend: {backend!r}")
        return 1

    asyncio.run(run(extractor, fixtures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
