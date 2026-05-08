from __future__ import annotations

import pathlib
import re
import unittest

try:
    import yaml  # pyyaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_SPRINT_FILE = _PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
_STORY_DIR = _PROJECT_ROOT / "_bmad-output" / "implementation-artifacts"


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class Epic8StoryArtifactCompletionContractTests(unittest.TestCase):
    """Done Epic 8 story artifacts must include consistent closure evidence."""

    @classmethod
    def setUpClass(cls):
        if not HAS_YAML:
            raise unittest.SkipTest("pyyaml not available")
        with open(_SPRINT_FILE, encoding="utf-8") as handle:
            doc = yaml.safe_load(handle) or {}
        dev = doc.get("development_status", {})
        cls.done_epic8_story_keys = [
            key for key, status in dev.items()
            if key.startswith("8-") and status == "done"
        ]

    def test_epic8_done_stories_have_completion_state_and_dev_agent_record(self):
        missing = []
        for key in self.done_epic8_story_keys:
            story_file = _STORY_DIR / f"{key}.md"
            if not story_file.exists():
                missing.append(f"{key}: missing file")
                continue
            text = story_file.read_text(encoding="utf-8")
            if "## Completion State" not in text:
                missing.append(f"{key}: missing '## Completion State'")
            if "## Dev Agent Record" not in text:
                missing.append(f"{key}: missing '## Dev Agent Record'")

        self.assertEqual(missing, [], f"Epic 8 completion contract failures: {missing}")

    def test_epic8_done_stories_do_not_claim_ready_for_dev(self):
        stale = []
        for key in self.done_epic8_story_keys:
            story_file = _STORY_DIR / f"{key}.md"
            if not story_file.exists():
                continue
            text = story_file.read_text(encoding="utf-8")
            if re.search(r"ready-for-dev", text, flags=re.IGNORECASE):
                stale.append(key)

        self.assertEqual(
            stale,
            [],
            f"Done Epic 8 stories still contain 'ready-for-dev' text: {stale}",
        )


if __name__ == "__main__":
    unittest.main()
