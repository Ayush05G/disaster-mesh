"""Unit tests for the eval harness's own scoring logic (scripts/run_eval.py),
independent of which extractor backend produced the payload."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_eval import load_fixtures, scores  # noqa: E402

from src.ai_engine.schemas import HazardPayload  # noqa: E402


def _payload(hazard_type: str, severity: str) -> HazardPayload:
    return HazardPayload(
        node_id="n1",
        timestamp="2026-01-01T00:00:00Z",
        hazard_type=hazard_type,
        severity=severity,
        coordinates={"lat": 0.0, "lng": 0.0},
    )


def test_fixtures_load_and_are_well_formed():
    fixtures = load_fixtures()
    assert len(fixtures) >= 20
    for f in fixtures:
        assert "text" in f and f["text"]
        assert "hazard_type_keywords" in f and len(f["hazard_type_keywords"]) >= 1
        assert f["expected_severity"] in ("LOW", "MEDIUM", "HIGH")


def test_scores_pass_on_keyword_and_severity_match():
    fixture = {"hazard_type_keywords": ["flood", "water"], "expected_severity": "HIGH"}
    ok, _ = scores(_payload("flooding", "HIGH"), fixture)
    assert ok


def test_scores_fail_on_wrong_hazard_type():
    fixture = {"hazard_type_keywords": ["flood", "water"], "expected_severity": "HIGH"}
    ok, detail = scores(_payload("fire", "HIGH"), fixture)
    assert not ok
    assert "hazard_type" in detail


def test_scores_fail_on_wrong_severity():
    fixture = {"hazard_type_keywords": ["flood", "water"], "expected_severity": "HIGH"}
    ok, detail = scores(_payload("flooding", "LOW"), fixture)
    assert not ok
    assert "severity" in detail


def test_scores_keyword_match_is_substring_case_insensitive():
    fixture = {"hazard_type_keywords": ["Flood"], "expected_severity": "MEDIUM"}
    ok, _ = scores(_payload("major_flooding_event", "MEDIUM"), fixture)
    assert ok
