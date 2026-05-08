"""Operational route inventory contract tests (Epic 7 Story 7.2).

Ensures operational endpoints documented in docs runbook artifacts are present
in the Flask url map with the documented HTTP methods.
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

REQUIRED_ENV = {
    "WHATSAPP_PROVIDER": "meta",
    "ACCESS_TOKEN": "token",
    "YOUR_PHONE_NUMBER": "15551234567",
    "APP_ID": "123456789",
    "APP_SECRET": "supersecret",
    "RECIPIENT_WAID": "15551234567",
    "VERSION": "v18.0",
    "PHONE_NUMBER_ID": "1234567890",
    "VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "sk-test",
}

_PROJECT_ROOT = Path(__file__).parent.parent
_DOC_FILES = (
    _PROJECT_ROOT / "docs" / "operations_runbook.md",
    _PROJECT_ROOT / "docs" / "runbook.md",
    _PROJECT_ROOT / "docs" / "release_smoke_checklist.md",
    _PROJECT_ROOT / "docs" / "setup_guide.md",
)

_METHOD_PATH_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+`(/[^`\s]+)`")


def _documented_routes() -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for doc_path in _DOC_FILES:
        if not doc_path.exists():
            continue
        content = doc_path.read_text(encoding="utf-8")
        for method, path in _METHOD_PATH_RE.findall(content):
            routes.add((method.upper(), path.strip()))
    return routes


class OperationalRouteInventoryTests(unittest.TestCase):
    """Documented operational routes must exist in runtime route map."""

    def setUp(self):
        with patch.dict(os.environ, REQUIRED_ENV, clear=False):
            from app import create_app

            self.app = create_app()

    def test_docs_expose_operational_routes(self):
        documented = _documented_routes()
        self.assertGreater(
            len(documented),
            0,
            "No documented HTTP routes found in docs runbook artifacts.",
        )

    def test_documented_operational_routes_exist_in_flask_map(self):
        documented = _documented_routes()
        route_map: dict[str, set[str]] = {}
        for rule in self.app.url_map.iter_rules():
            allowed = {method for method in rule.methods if method not in {"HEAD", "OPTIONS"}}
            route_map.setdefault(rule.rule, set()).update(allowed)

        missing: list[str] = []
        for method, path in sorted(documented):
            methods = route_map.get(path)
            if methods is None:
                missing.append(f"{method} {path} (missing path)")
                continue
            if method not in methods:
                missing.append(f"{method} {path} (available methods: {sorted(methods)})")

        self.assertEqual(
            missing,
            [],
            "Documented operational endpoints missing from Flask route map: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()
