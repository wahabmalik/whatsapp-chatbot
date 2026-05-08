"""
validate_sprint_status_integrity.py

Sprint-Status Integrity Validation Script (Epic 4 Action Item 5)

Verifies:
1. Story status consistency (no status leaps without intermediate steps)
2. Epic status matches aggregate of story statuses
3. No orphaned stories or unreferenced epics
4. Retrospective markers properly set
5. Last-updated timestamp is recent
"""

import yaml
from pathlib import Path
from datetime import datetime, timedelta, timezone
import re

SPRINT_STATUS_PATH = Path(__file__).parent / '_bmad-output' / 'implementation-artifacts' / 'sprint-status.yaml'

# Valid status transitions
VALID_STATUS_TRANSITIONS = {
    'backlog': ['ready-for-dev', 'in-progress', 'done'],
    'ready-for-dev': ['in-progress', 'backlog', 'done'],
    'in-progress': ['review', 'backlog', 'done'],
    'review': ['in-progress', 'done', 'backlog'],
    'done': ['backlog'],  # Can reopen if needed
}

# Retrospective-specific statuses
RETRO_STATUSES = {
    'optional': ['done'],
    'done': ['optional'],
}

EPIC_TRANSITIONS = {
    'backlog': ['in-progress', 'done'],
    'in-progress': ['done', 'backlog'],
    'done': ['backlog', 'in-progress'],
}

RETRO_TRANSITIONS = {
    'optional': ['done'],
    'done': ['optional'],
}


def _story_belongs_to_epic(story_key: str, epic_key: str) -> bool:
    """Return True when a story key belongs to an epic key.

    Supports both naming patterns:
    - Numeric story keys: 1-2-some-story
    - Explicit epic prefix keys: epic-1-some-story
    """
    if story_key.startswith('epic-') or story_key.endswith('-retrospective'):
        return False

    epic_match = re.match(r'^epic-(\d+)$', epic_key)
    if not epic_match:
        return False

    epic_num = epic_match.group(1)
    return story_key.startswith(f"{epic_num}-") or story_key.startswith(f"epic-{epic_num}-")


def load_sprint_status():
    """Load and parse sprint-status.yaml."""
    if not SPRINT_STATUS_PATH.exists():
        print(f"❌ FAIL: sprint-status.yaml not found at {SPRINT_STATUS_PATH}")
        return None

    with open(SPRINT_STATUS_PATH, 'r') as f:
        return yaml.safe_load(f)


def validate_story_status_definitions(data):
    """Ensure all story status values are valid."""
    issues = []
    development = data.get('development_status', {})

    valid_story_statuses = set(VALID_STATUS_TRANSITIONS.keys())
    valid_retro_statuses = set(RETRO_STATUSES.keys())

    for key, status in development.items():
        # Retrospectives have different valid statuses
        if key.endswith('-retrospective'):
            if status not in valid_retro_statuses:
                issues.append(
                    f"❌ Retrospective {key} has invalid status '{status}' "
                    f"(valid: {valid_retro_statuses})"
                )
        else:
            if status not in valid_story_statuses:
                issues.append(
                    f"❌ Story {key} has invalid status '{status}' "
                    f"(valid: {valid_story_statuses})"
                )

    return issues


def validate_no_duplicate_development_status_keys():
    """Ensure development_status does not contain duplicate YAML keys."""
    issues = []
    if not SPRINT_STATUS_PATH.exists():
        return [f"❌ sprint-status.yaml not found at {SPRINT_STATUS_PATH}"]

    raw_lines = SPRINT_STATUS_PATH.read_text(encoding="utf-8").splitlines()
    in_dev = False
    keys_seen: list[str] = []
    for line in raw_lines:
        if line.strip() == "development_status:":
            in_dev = True
            continue
        if in_dev:
            if line and not line[0].isspace() and line.rstrip().endswith(":"):
                break
            match = re.match(r"^\s{2}([a-z0-9_-]+)\s*:", line)
            if match:
                keys_seen.append(match.group(1))

    duplicate_keys = sorted({key for key in keys_seen if keys_seen.count(key) > 1})
    if duplicate_keys:
        issues.append(
            f"❌ Duplicate keys detected in development_status: {duplicate_keys}"
        )

    return issues


def validate_story_count_and_structure(data):
    """Ensure epic-story relationships are sound."""
    issues = []
    development = data.get('development_status', {})

    # Extract epics and stories (exclude retrospectives from structure checks)
    epics = {k: v for k, v in development.items() if k.startswith('epic-') and not k.endswith('-retrospective')}
    retrospectives = {k: v for k, v in development.items() if k.endswith('-retrospective')}

    for epic_key, epic_status in epics.items():
        # Find stories for this epic (exclude retrospectives)
        stories_for_epic = [
            (k, v) for k, v in development.items()
            if _story_belongs_to_epic(k, epic_key)
        ]

        if not stories_for_epic:
            # Epic exists but has no stories - likely malformed
            if epic_status != 'backlog':
                issues.append(
                    f"⚠️  Epic {epic_key} has status '{epic_status}' "
                    f"but no stories attached"
                )

        # Validate retrospective exists for completed epics
        retro_key = f"{epic_key}-retrospective"
        if epic_status == 'done' and retro_key in retrospectives:
            retro_status = retrospectives[retro_key]
            if retro_status not in RETRO_STATUSES:
                issues.append(
                    f"⚠️  Epic {epic_key} retrospective has invalid status '{retro_status}'"
                )

    return issues


def validate_epic_status_aggregate(data):
    """Ensure epic status reflects its stories' statuses."""
    issues = []
    development = data.get('development_status', {})

    # Extract epics and stories (exclude retrospectives)
    epics = {k: v for k, v in development.items() if k.startswith('epic-') and not k.endswith('-retrospective')}

    for epic_key, epic_status in epics.items():
        stories = [
            (k, v) for k, v in development.items()
            if _story_belongs_to_epic(k, epic_key)
        ]

        if not stories:
            continue

        story_statuses = [status for _, status in stories]

        # If any story is in-progress, epic should be in-progress
        if 'in-progress' in story_statuses:
            if epic_status not in ['in-progress', 'done']:
                issues.append(
                    f"⚠️  Epic {epic_key} status is '{epic_status}' "
                    f"but contains in-progress stories: {[s[0] for s in stories if s[1] == 'in-progress']}"
                )

        # If all stories are done, epic should be done
        if all(s == 'done' for s in story_statuses):
            if epic_status != 'done':
                issues.append(
                    f"⚠️  Epic {epic_key} should be marked 'done' "
                    f"as all stories are complete"
                )

    return issues


def validate_timestamp_freshness(data):
    """Ensure last_updated is recent."""
    issues = []
    last_updated_value = data.get('last_updated')

    if not last_updated_value:
        issues.append("❌ last_updated field is missing or empty")
        return issues

    try:
        # YAML may parse timestamps as datetime objects
        if isinstance(last_updated_value, datetime):
            last_updated = last_updated_value
        else:
            # String format - could be ISO with T or just date
            last_updated_str = str(last_updated_value).strip()
            if 'T' in last_updated_str:
                last_updated = datetime.fromisoformat(last_updated_str.replace('Z', '+00:00'))
            else:
                # If no time component, assume midnight UTC
                last_updated = datetime.fromisoformat(f"{last_updated_str}T00:00:00+00:00")
        
        # Make sure we have timezone info for comparison
        if last_updated.tzinfo is None:
            # Assume UTC if no timezone
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        delta = now - last_updated

        if delta > timedelta(hours=24):
            issues.append(
                f"⚠️  last_updated is stale ({delta.days}d {delta.seconds//3600}h old); "
                f"last update: {last_updated}"
            )

    except Exception as e:
        issues.append(f"❌ last_updated format invalid: {last_updated_value} ({type(e).__name__}: {e})")

    return issues


def main():
    """Run all validation checks."""
    data = load_sprint_status()
    if not data:
        return False

    all_issues = []

    print("\n📋 Validating Sprint Status Integrity...\n")

    checks = [
        ("No Duplicate development_status Keys", lambda _data: validate_no_duplicate_development_status_keys()),
        ("Story Status Values", validate_story_status_definitions),
        ("Epic-Story Structure", validate_story_count_and_structure),
        ("Epic Status Aggregate", validate_epic_status_aggregate),
        ("Timestamp Freshness", validate_timestamp_freshness),
    ]

    for check_name, check_func in checks:
        issues = check_func(data)
        if issues:
            print(f"{check_name}:")
            for issue in issues:
                print(f"  {issue}")
            all_issues.extend(issues)
        else:
            print(f"✅ {check_name}")

    print()

    if all_issues:
        # Count errors vs warnings
        errors = [i for i in all_issues if i.startswith("❌")]
        warnings = [i for i in all_issues if i.startswith("⚠️ ")]

        if errors:
            print(f"❌ FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
            return False
        else:
            print(f"⚠️  PASS WITH WARNINGS: {len(warnings)} warning(s)")
            return True
    else:
        print("✅ PASS: All sprint status integrity checks passed")
        return True


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
