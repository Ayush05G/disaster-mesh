"""
CLAUDE.md Critical Rule 2: schemas.py is the source of truth for the hazard
contract; schema.json mirrors it for Node/React. Divergence is a bug.

If this test fails, run: python scripts/generate_schema.py
"""
import json
from pathlib import Path

from src.ai_engine.schemas import HazardPayload

SCHEMA_JSON_PATH = Path(__file__).resolve().parent.parent / "src" / "shared" / "schema.json"


def test_schema_json_matches_generated():
    committed = json.loads(SCHEMA_JSON_PATH.read_text(encoding="utf-8"))
    generated = HazardPayload.model_json_schema()
    assert committed == generated, (
        "src/shared/schema.json has drifted from HazardPayload. "
        "Run: python scripts/generate_schema.py"
    )
