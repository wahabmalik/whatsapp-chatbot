"""
Sprint Status Integrity Tests — Epic 4 Carry-Forward Action #5

Verifies internal consistency of sprint-status.yaml:
  1. Every story key (non-epic, non-retrospective) has a matching .md file
     under _bmad-output/implementation-artifacts/
  2. Epic status is consistent with its child story statuses:
     - If an epic is 'done', all its stories must also be 'done'
     - If all stories are 'done', the epic should not still be 'backlog'
  3. Status values are within the allowed set
  4. No duplicate keys in development_status
"""
import pathlib
import re
import unittest

try:
    import yaml  # pyyaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_SPRINT_FILE = (
    _PROJECT_ROOT / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
)
_STORY_DIR = _PROJECT_ROOT / "_bmad-output" / "implementation-artifacts"

# Patterns that identify non-story keys
_EPIC_RE = re.compile(r"^epic-\d+$")
_RETRO_RE = re.compile(r"^epic-\d+-retrospective$")

# Valid status values per category (permissive — new statuses can be added)
_EPIC_STATUSES = {"backlog", "in-progress", "done"}
_STORY_STATUSES = {"backlog", "ready-for-dev", "in-progress", "review", "done"}
_RETRO_STATUSES = {"optional", "in-progress", "done"}


def _is_epic(key: str) -> bool:
    return bool(_EPIC_RE.match(key))


def _is_retro(key: str) -> bool:
    return bool(_RETRO_RE.match(key))


def _is_story(key: str) -> bool:
    return not _is_epic(key) and not _is_retro(key)


def _epic_number(key: str) -> str:
    """Return the numeric part of an epic key, e.g. 'epic-3' → '3'."""
    return key.replace("epic-", "").replace("-retrospective", "")


def _load_sprint_status() -> dict:
    if not HAS_YAML:
        raise ImportError(
            "pyyaml is required for sprint status integrity tests. "
            "Run: pip install pyyaml"
        )
    with open(_SPRINT_FILE, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class SprintStatusFileTests(unittest.TestCase):
    """sprint-status.yaml exists and has expected top-level structure."""

    @classmethod
    def setUpClass(cls):
        cls.doc = _load_sprint_status()
        cls.dev = cls.doc.get("development_status", {})

    def test_sprint_file_exists(self):
        """sprint-status.yaml must exist for integrity checks to run."""
        self.assertTrue(_SPRINT_FILE.exists())

    def test_development_status_is_dict(self):
        """development_status key is a dict."""
        self.assertIsInstance(self.dev, dict)

    def test_development_status_is_not_empty(self):
        """development_status has at least one entry."""
        self.assertGreater(len(self.dev), 0)


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class StoryFileExistenceTests(unittest.TestCase):
    """Every story key in development_status has a matching .md file."""

    @classmethod
    def setUpClass(cls):
        doc = _load_sprint_status()
        cls.dev = doc.get("development_status", {})
        cls.story_keys = [k for k in cls.dev if _is_story(k)]

    def test_story_keys_identified(self):
        """At least one story key must be identifiable."""
        self.assertGreater(
            len(self.story_keys), 0,
            "No story keys found in development_status.",
        )

    def test_all_story_keys_have_implementation_files(self):
        """Every story key has a corresponding .md file in implementation-artifacts/."""
        missing = []
        for key in self.story_keys:
            md_file = _STORY_DIR / f"{key}.md"
            if not md_file.exists():
                missing.append(f"{key}.md")
        self.assertEqual(
            missing,
            [],
            f"These story keys have no matching .md file in "
            f"_bmad-output/implementation-artifacts/: {missing}. "
            f"Either create the file or remove the key from sprint-status.yaml.",
        )


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class EpicStoryConsistencyTests(unittest.TestCase):
    """Epic status is consistent with the aggregate status of its stories."""

    @classmethod
    def setUpClass(cls):
        doc = _load_sprint_status()
        cls.dev = doc.get("development_status", {})
        # Build mapping: epic_number → {epic_status, story_statuses: []}
        cls.epic_map = {}
        for key, status in cls.dev.items():
            if _is_epic(key):
                num = _epic_number(key)
                cls.epic_map.setdefault(num, {})["epic_status"] = status
            elif _is_story(key):
                # Derive epic number from story prefix (e.g. "2-1-..." → epic "2")
                num = key.split("-")[0]
                entry = cls.epic_map.setdefault(num, {})
                entry.setdefault("story_statuses", []).append(status)

    def test_done_epic_has_all_done_stories(self):
        """If an epic is 'done', all its story entries must also be 'done'."""
        violations = []
        for num, data in self.epic_map.items():
            if data.get("epic_status") == "done":
                not_done = [
                    s for s in data.get("story_statuses", []) if s != "done"
                ]
                if not_done:
                    violations.append(
                        f"epic-{num} is 'done' but has {len(not_done)} "
                        f"non-done story statuses: {not_done}"
                    )
        self.assertEqual(
            violations,
            [],
            f"Epic/story consistency violations: {violations}",
        )

    def test_backlog_epic_has_no_done_stories(self):
        """An epic in 'backlog' should not have any stories marked 'done'."""
        violations = []
        for num, data in self.epic_map.items():
            if data.get("epic_status") == "backlog":
                done_stories = [
                    s for s in data.get("story_statuses", []) if s == "done"
                ]
                if done_stories:
                    violations.append(
                        f"epic-{num} is 'backlog' but has {len(done_stories)} "
                        f"'done' stories — epic should be at least 'in-progress'."
                    )
        self.assertEqual(violations, [], str(violations))

    def test_all_stories_done_means_epic_not_backlog(self):
        """If every story in an epic is 'done', the epic should not be 'backlog'."""
        violations = []
        for num, data in self.epic_map.items():
            statuses = data.get("story_statuses", [])
            if not statuses:
                continue
            if all(s == "done" for s in statuses) and data.get("epic_status") == "backlog":
                violations.append(
                    f"epic-{num}: all {len(statuses)} stories are 'done' but "
                    f"epic status is still 'backlog'."
                )
        self.assertEqual(violations, [], str(violations))


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class StatusValueValidationTests(unittest.TestCase):
    """All status values are within the documented allowed set."""

    @classmethod
    def setUpClass(cls):
        doc = _load_sprint_status()
        cls.dev = doc.get("development_status", {})

    def test_epic_status_values_are_valid(self):
        """Epic keys only use known epic status values."""
        bad = {
            k: v for k, v in self.dev.items()
            if _is_epic(k) and v not in _EPIC_STATUSES
        }
        self.assertEqual(
            bad,
            {},
            f"Invalid epic status values: {bad}. "
            f"Valid: {_EPIC_STATUSES}",
        )

    def test_story_status_values_are_valid(self):
        """Story keys only use known story status values."""
        bad = {
            k: v for k, v in self.dev.items()
            if _is_story(k) and v not in _STORY_STATUSES
        }
        self.assertEqual(
            bad,
            {},
            f"Invalid story status values: {bad}. "
            f"Valid: {_STORY_STATUSES}",
        )

    def test_retro_status_values_are_valid(self):
        """Retrospective keys only use known retro status values."""
        bad = {
            k: v for k, v in self.dev.items()
            if _is_retro(k) and v not in _RETRO_STATUSES
        }
        self.assertEqual(
            bad,
            {},
            f"Invalid retro status values: {bad}. "
            f"Valid: {_RETRO_STATUSES}",
        )


@unittest.skipUnless(_SPRINT_FILE.exists(), "sprint-status.yaml not found")
class NoDuplicateKeysTest(unittest.TestCase):
    """development_status must have no duplicate keys (YAML may silently merge dupes)."""

    def test_no_duplicate_development_status_keys(self):
        """Load YAML raw to check for duplicate keys."""
        if not HAS_YAML:
            self.skipTest("pyyaml not available")
        # Standard yaml.safe_load silently overwrites dupes; use a custom loader
        raw_lines = _SPRINT_FILE.read_text(encoding="utf-8").splitlines()
        in_dev = False
        keys_seen = []
        for line in raw_lines:
            if line.strip() == "development_status:":
                in_dev = True
                continue
            if in_dev:
                # Stop at the next top-level key (no indentation, ends with :)
                if line and not line[0].isspace() and line.rstrip().endswith(":"):
                    break
                m = re.match(r"^\s{2}([a-z0-9_-]+)\s*:", line)
                if m:
                    keys_seen.append(m.group(1))
        dupes = [k for k in keys_seen if keys_seen.count(k) > 1]
        dupes_unique = list(set(dupes))
        self.assertEqual(
            dupes_unique,
            [],
            f"Duplicate keys in development_status: {dupes_unique}",
        )


if __name__ == "__main__":
    unittest.main()
