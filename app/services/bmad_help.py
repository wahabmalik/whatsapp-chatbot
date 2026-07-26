"""BMAD Help catalog loader for the Closar operator UI.

Parses `_bmad/_config/bmad-help.csv` (installed module help manifest) and
surfaces menu codes / next-step recommendations. Skill *execution* still
happens in Cursor via the `bmad-help` skill — this service is the in-app guide.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELP_CSV = PROJECT_ROOT / "_bmad" / "_config" / "bmad-help.csv"
OUTPUT_ROOT = PROJECT_ROOT / "_bmad-output"

# Actual CSV columns are misaligned vs the skill docs; map by observed layout:
# module, skill, display_name, menu_code, description, action, args, phase,
# after, before, _, _, required_or_before_extra, output_location, outputs
_PHASE_TOKENS = {
    "anytime",
    "0-learning",
    "1-analysis",
    "2-planning",
    "3-solutioning",
    "4-implementation",
}


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "required"}


def _artifact_hits(output_location: str, outputs: str) -> list[str]:
    """Return matching artifact file names under _bmad-output for completion hints."""
    if not OUTPUT_ROOT.exists():
        return []

    needles: list[str] = []
    for part in (outputs or "").replace("|", ",").split(","):
        token = part.strip().lower()
        if token and token not in {"*", ""}:
            needles.append(token.replace(" ", "-"))

    search_roots = [OUTPUT_ROOT]
    loc = (output_location or "").strip()
    if loc and not loc.startswith("http"):
        # Resolve common tokens to folders under _bmad-output
        aliases = {
            "planning_artifacts": OUTPUT_ROOT / "planning-artifacts",
            "planning-artifacts": OUTPUT_ROOT / "planning-artifacts",
            "implementation_artifacts": OUTPUT_ROOT / "implementation-artifacts",
            "implementation-artifacts": OUTPUT_ROOT / "implementation-artifacts",
            "test_artifacts": OUTPUT_ROOT / "test-artifacts",
            "test-artifacts": OUTPUT_ROOT / "test-artifacts",
            "project_knowledge": OUTPUT_ROOT / "planning-artifacts",
            "project-knowledge": OUTPUT_ROOT / "planning-artifacts",
            "output_folder": OUTPUT_ROOT,
        }
        for key, path in aliases.items():
            if key in loc.replace("{", "").replace("}", "") and path.exists():
                search_roots.append(path)

    hits: list[str] = []
    seen: set[str] = set()
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            stem = path.stem.lower()
            for needle in needles:
                if needle in name or needle in stem or needle.replace("-", "") in stem.replace("-", ""):
                    rel = str(path.relative_to(PROJECT_ROOT))
                    if rel not in seen:
                        seen.add(rel)
                        hits.append(rel)
                    break
            if len(hits) >= 5:
                return hits
    return hits


def load_bmad_help_catalog() -> dict[str, Any]:
    """Load help entries + module docs meta from bmad-help.csv."""
    modules_docs: list[dict[str, str]] = []
    entries: list[dict[str, Any]] = []

    if not HELP_CSV.exists():
        return {
            "entries": [],
            "modules": [],
            "module_docs": [],
            "recommended": [],
            "catalog_path": str(HELP_CSV.relative_to(PROJECT_ROOT)),
            "available": False,
        }

    with HELP_CSV.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            module = str(raw.get("module") or "").strip()
            skill = str(raw.get("phase") or "").strip()  # CSV: skill lives in "phase"
            display_name = str(raw.get("name") or "").strip()
            menu_code = str(raw.get("code") or "").strip()
            description = str(raw.get("sequence") or "").strip()
            action = str(raw.get("workflow-file") or "").strip()
            args = str(raw.get("command") or "").strip()
            phase = str(raw.get("required") or "").strip()  # CSV: phase lives in "required"
            after = str(raw.get("agent-name") or "").strip()
            before = str(raw.get("agent-command") or "").strip()
            # Remaining columns vary; prefer options/description/output-location
            options = str(raw.get("options") or "").strip()
            output_location = str(raw.get("description") or "").strip()
            outputs = str(raw.get("output-location") or "").strip()
            trailing = str(raw.get("outputs") or "").strip()

            # Some rows put required flag in options; others shove a before-skill there.
            required = _truthy(options)
            if options and not required and ("bmad-" in options or ":" in options):
                if not before:
                    before = options
                # required may be in the misnamed description column when options held a skill
                required = _truthy(output_location)
                if required or output_location.lower() in {"true", "false"}:
                    output_location = outputs
                    outputs = trailing

            if skill == "_meta" or (not skill and module and output_location.startswith("http")):
                doc_url = output_location or outputs or trailing
                if module and doc_url.startswith("http"):
                    modules_docs.append({"module": module, "docs_url": doc_url})
                continue

            if not module or not skill or not display_name:
                continue
            if phase not in _PHASE_TOKENS and phase:
                # tolerate unknown phase labels
                pass
            if not phase:
                phase = "anytime"

            artifacts = _artifact_hits(output_location, outputs)
            completed = bool(artifacts)
            invoke = skill if not action else f"{skill}:{action}"
            entries.append(
                {
                    "module": module,
                    "skill": skill,
                    "display_name": display_name,
                    "menu_code": menu_code or "—",
                    "description": description,
                    "action": action,
                    "args": args,
                    "phase": phase,
                    "after": after,
                    "before": before,
                    "required": required,
                    "output_location": output_location,
                    "outputs": outputs,
                    "invoke": invoke,
                    "completed": completed,
                    "artifact_hits": artifacts,
                }
            )

    modules = sorted({row["module"] for row in entries})
    recommended = _recommend(entries)
    return {
        "entries": entries,
        "modules": modules,
        "module_docs": modules_docs,
        "recommended": recommended,
        "catalog_path": str(HELP_CSV.relative_to(PROJECT_ROOT)),
        "available": True,
        "how_to": {
            "cursor": "In Cursor chat, type bmad-help or a menu code like CP / BH.",
            "phone": "Browse this catalog on phone, then run the skill in Cursor on desktop.",
        },
    }


def _recommend(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pick a short next-step list: incomplete required first, then anytime helpers."""
    incomplete_required = [
        row
        for row in entries
        if row["required"] and not row["completed"] and row["phase"] != "anytime"
    ]
    # Prefer earliest phase order
    phase_rank = {
        "0-learning": 0,
        "1-analysis": 1,
        "2-planning": 2,
        "3-solutioning": 3,
        "4-implementation": 4,
        "anytime": 9,
    }
    incomplete_required.sort(key=lambda r: (phase_rank.get(r["phase"], 5), r["display_name"]))

    anytime = [
        row
        for row in entries
        if row["phase"] == "anytime" and row["skill"] in {"bmad-help", "bmad-party-mode", "bmad-brainstorming"}
    ]
    picks = anytime[:2] + incomplete_required[:4]
    # Always include BMad Help itself first if present
    help_row = next((r for r in entries if r["skill"] == "bmad-help"), None)
    if help_row and help_row not in picks:
        picks.insert(0, help_row)
    return picks[:6]


def filter_catalog(
    catalog: dict[str, Any],
    *,
    module: str | None = None,
    phase: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    rows = list(catalog.get("entries") or [])
    module = (module or "").strip()
    phase = (phase or "").strip()
    q = (q or "").strip().lower()

    if module and module.lower() != "all":
        rows = [r for r in rows if r["module"].lower() == module.lower()]
    if phase and phase.lower() != "all":
        rows = [r for r in rows if r["phase"].lower() == phase.lower()]
    if q:
        rows = [
            r
            for r in rows
            if q in r["display_name"].lower()
            or q in r["skill"].lower()
            or q in r["menu_code"].lower()
            or q in r["description"].lower()
            or q in r["module"].lower()
        ]
    return rows
