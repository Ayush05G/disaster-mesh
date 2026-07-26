"""
Regenerate src/shared/schema.json from the pydantic source of truth.

CLAUDE.md Critical Rule 2: schemas.py is the source of truth; schema.json is a
mirror for the Node/React layers. Divergence is a bug — run this after any
change to HazardPayload and commit the result.

Usage: python scripts/generate_schema.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ai_engine.schemas import HazardPayload  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "src" / "shared" / "schema.json"


def generate() -> dict:
    return HazardPayload.model_json_schema()


def main() -> None:
    schema = generate()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
