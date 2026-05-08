"""Template URL contract tests for operator-facing pages (Epic 7 Story 7.3)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_OPERATOR_TEMPLATES = (
    _PROJECT_ROOT / "app" / "templates" / "base.html",
    _PROJECT_ROOT / "app" / "templates" / "setup.html",
    _PROJECT_ROOT / "app" / "templates" / "metrics.html",
    _PROJECT_ROOT / "app" / "templates" / "logs.html",
    _PROJECT_ROOT / "app" / "templates" / "dashboard.html",
    _PROJECT_ROOT / "app" / "templates" / "agents.html",
    _PROJECT_ROOT / "app" / "templates" / "agents-enhanced.html",
)

_HARDCODED_PATH_RE = re.compile(
    r"(?:href|action|data-[a-z0-9_-]+)\s*=\s*\"/(?!/)[^\"]+\"",
    re.IGNORECASE,
)


class OperatorTemplateUrlContractTests(unittest.TestCase):
    """Operator-facing templates must use url_for for internal app paths."""

    def test_no_hardcoded_absolute_paths_in_operator_templates(self):
        violations: list[str] = []
        for template_path in _OPERATOR_TEMPLATES:
            self.assertTrue(template_path.exists(), f"Missing template under contract: {template_path}")
            content = template_path.read_text(encoding="utf-8")
            for match in _HARDCODED_PATH_RE.findall(content):
                violations.append(f"{template_path.relative_to(_PROJECT_ROOT)} => {match}")

        self.assertEqual(
            violations,
            [],
            "Hardcoded absolute paths found in operator-facing templates: " + "; ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
