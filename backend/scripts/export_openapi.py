"""Write the API contract (OpenAPI document) to docs/api/openapi.json.

    python -m scripts.export_openapi

The contract test (tests/test_contract.py) fails whenever the API changes without this file
being regenerated, so every API change shows up in code review - record it in docs/api/CHANGELOG.md.
"""

import json
from pathlib import Path

from app.main import app

TARGET = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def contract() -> dict:
    return app.openapi()


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(contract(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {TARGET}")


if __name__ == "__main__":
    main()
