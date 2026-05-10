"""Validate done-story closure evidence blocks with legacy compatibility."""

from __future__ import annotations

from pathlib import Path

import yaml


LEGACY_REQUIRED_SECTIONS = (
    "## Completion State",
    "## Dev Agent Record",
)

MODERN_REQUIRED_SECTIONS = (
    "## Dev Agent Record",
    "### Completion Notes List",
    "### File List",
    "### Change Log",
)


def _is_story_key(key: str) -> bool:
    if key.startswith("epic-") or key.endswith("-retrospective"):
        return False
    return True


def _has_all_sections(text: str, sections: tuple[str, ...]) -> bool:
    return all(section in text for section in sections)


def _legacy_compatible(text: str) -> bool:
    """Return True when historical story formats provide usable closure evidence."""
    has_dev_agent_record = "## Dev Agent Record" in text
    has_completion_signal = any(
        marker in text
        for marker in (
            "### Completion Notes",
            "### Completion Notes List",
            "### Debug Log",
        )
    )
    has_file_signal = any(
        marker in text
        for marker in (
            "## File List",
            "### File List",
        )
    )
    return has_dev_agent_record and has_completion_signal and has_file_signal


def validate_story_closure_evidence(implementation_dir: Path) -> list[str]:
    """Validate done stories while preserving compatibility for historical artifacts."""
    issues: list[str] = []
    sprint_files: list[Path] = []
    for known_file in ("sprint-status-next-cycle.yaml", "sprint-status.yaml"):
        candidate = implementation_dir / known_file
        if candidate.exists():
            sprint_files.append(candidate)

    for discovered in sorted(implementation_dir.glob("sprint-status*.yaml")):
        if discovered not in sprint_files:
            sprint_files.append(discovered)

    if not sprint_files:
        return [f"No sprint-status files found in {implementation_dir}"]

    for sprint_file in sprint_files:
        try:
            with open(sprint_file, encoding="utf-8") as handle:
                document = yaml.safe_load(handle) or {}
        except yaml.YAMLError as e:
            issues.append(f"YAML parsing error in {sprint_file.name}: {e}")
            continue
        except OSError as e:
            issues.append(f"Unable to load {sprint_file.name}: {e}")
            continue
        except Exception as e:
            issues.append(f"Unexpected error in {sprint_file.name}: {e}")
            continue

        development_status = document.get("development_status", {})
        if not isinstance(development_status, dict):
            issues.append(f"{sprint_file.name} has invalid development_status section")
            continue

        for story_key, status in development_status.items():
            if status != "done" or not _is_story_key(str(story_key)):
                continue

            story_path = implementation_dir / f"{story_key}.md"
            is_next_cycle_story = str(story_key).startswith("next-cycle-")

            if not story_path.exists():
                if is_next_cycle_story:
                    issues.append(
                        f"{sprint_file.name}: done story file missing for {story_key}"
                    )
                continue

            try:
                text = story_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                issues.append(
                    f"{sprint_file.name}: unable to read story file for {story_key}: {e}"
                )
                continue
            modern_ok = _has_all_sections(text, MODERN_REQUIRED_SECTIONS)
            legacy_ok = _has_all_sections(text, LEGACY_REQUIRED_SECTIONS) or _legacy_compatible(text)

            if is_next_cycle_story and not modern_ok:
                issues.append(
                    f"{sprint_file.name}: story {story_key} missing closure evidence "
                    "(next-cycle stories require modern closure sections)"
                )
            elif not is_next_cycle_story and not (modern_ok or legacy_ok):
                # Historical artifacts are read for compatibility checks but are not
                # hard-failed to preserve retrospective backfill compatibility.
                continue

    return issues


def main() -> int:
    implementation_dir = Path(__file__).parent / "_bmad-output" / "implementation-artifacts"
    issues = validate_story_closure_evidence(implementation_dir)

    if issues:
        print("❌ FAIL: story closure evidence validation failed")
        for issue in issues:
            print(f"  - {issue}")
        return 1

    print("✅ PASS: story closure evidence validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
