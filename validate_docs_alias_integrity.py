"""
validate_docs_alias_integrity.py

Documentation Alias Integrity Linter (Epic 4 Action Item 6)

Enforces alias file policy:
1. Alias files must be in `docs/` directory
2. Alias files must contain ONLY redirect content (max ~10 lines)
3. Alias files must reference canonical documents
4. Canonical documents must not be empty placeholders
5. No circular references between aliases
"""

import re
from pathlib import Path

DOCS_PATH = Path(__file__).parent / 'docs'

# Alias files and their canonical targets
ALIAS_MAPPINGS = {
    'setup-guide.md': 'setup_guide.md',      # lowercase dash to underscore
    'runbook.md': 'operations_runbook.md',   # short name to full name
}

MAX_ALIAS_LINES = 15  # Aliases should be concise
MIN_CANONICAL_LINES = 30  # Canonical docs should have substance


def check_alias_file(alias_path):
    """Validate an alias file."""
    issues = []

    if not alias_path.exists():
        return [f"❌ Alias file not found: {alias_path}"]

    content = alias_path.read_text()
    lines = content.strip().split('\n')

    # Check line count (aliases should be short)
    if len(lines) > MAX_ALIAS_LINES:
        issues.append(
            f"❌ {alias_path.name} exceeds {MAX_ALIAS_LINES} lines "
            f"({len(lines)} lines). Aliases must be brief redirects only."
        )

    # Check that it's not empty
    if len(lines) < 2:
        issues.append(f"❌ {alias_path.name} is too short; must contain redirect info")

    # Check that content is redirect-only (no substantial documentation)
    if re.search(r'^#+ \d+\.', content, re.MULTILINE):
        issues.append(
            f"❌ {alias_path.name} contains numbered sections; "
            f"aliases must be redirect-only, not documentation"
        )

    # Check that it references the canonical document
    if 'canonical' not in content.lower() and 'refer' not in content.lower():
        issues.append(
            f"⚠️  {alias_path.name} should clearly reference canonical docs"
        )

    return issues


def check_canonical_file(canonical_path):
    """Validate a canonical file."""
    issues = []

    if not canonical_path.exists():
        return [f"❌ Canonical file not found: {canonical_path}"]

    content = canonical_path.read_text()
    lines = content.strip().split('\n')

    # Check that it has substance
    if len(lines) < MIN_CANONICAL_LINES:
        issues.append(
            f"⚠️  Canonical {canonical_path.name} is short ({len(lines)} lines); "
            f"expected >= {MIN_CANONICAL_LINES} lines of documentation"
        )

    # Check that first line is a header
    if not lines[0].startswith('#'):
        issues.append(
            f"⚠️  {canonical_path.name} should start with a markdown header"
        )

    return issues


def check_circular_references():
    """Ensure no circular alias chains."""
    issues = []

    for alias, canonical in ALIAS_MAPPINGS.items():
        canonical_path = DOCS_PATH / canonical

        if not canonical_path.exists():
            issues.append(
                f"❌ Canonical file referenced by {alias} does not exist: {canonical}"
            )
            continue

        # Canonical file should not be an alias itself
        if canonical in ALIAS_MAPPINGS:
            issues.append(
                f"❌ Circular reference: {alias} -> {canonical} -> {ALIAS_MAPPINGS[canonical]}"
            )

    return issues


def main():
    """Run all alias validation checks."""
    all_issues = []

    print("\n📋 Validating Documentation Alias Integrity...\n")

    # Check alias files
    for alias_name, canonical_name in ALIAS_MAPPINGS.items():
        alias_path = DOCS_PATH / alias_name
        canonical_path = DOCS_PATH / canonical_name

        print(f"Checking {alias_name} -> {canonical_name}...")

        # Validate alias
        issues = check_alias_file(alias_path)
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  {issue}")
        else:
            print(f"  ✅ Alias structure valid")

        # Validate canonical
        issues = check_canonical_file(canonical_path)
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  {issue}")
        else:
            print(f"  ✅ Canonical content valid")

    # Check for circular references
    print("\nChecking circular references...")
    issues = check_circular_references()
    if issues:
        all_issues.extend(issues)
        for issue in issues:
            print(f"  {issue}")
    else:
        print(f"  ✅ No circular references")

    print()

    if all_issues:
        errors = [i for i in all_issues if i.startswith("❌")]
        warnings = [i for i in all_issues if i.startswith("⚠️")]

        if errors:
            print(f"❌ FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
            return False
        else:
            print(f"⚠️  PASS WITH WARNINGS: {len(warnings)} warning(s)")
            return True
    else:
        print("✅ PASS: All documentation alias checks passed")
        return True


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
