"""API contract: the OpenAPI document must match the committed copy in docs/api/openapi.json.

A failure means the API changed. If that was intended, regenerate the file
(python -m scripts.export_openapi) and record the change in docs/api/CHANGELOG.md; removing or
renaming anything in /api/v1 is a breaking change and needs a new API version instead.
"""

import json

import pytest

from scripts.export_openapi import TARGET, contract


def test_openapi_contract_matches_the_published_one():
    if not TARGET.exists():
        pytest.skip("docs/api/openapi.json not present (backend-only checkout)")
    published = json.loads(TARGET.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(contract(), sort_keys=True))
    assert current == published, "API contract changed: run python -m scripts.export_openapi and update the changelog"


def test_v1_has_no_unversioned_business_endpoints():
    for path in contract()["paths"]:
        assert path.startswith("/api/v1/") or path.startswith("/health") or path == "/metrics", path
