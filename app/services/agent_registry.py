from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"
AGENT_MANIFEST_FILE = PROJECT_ROOT / "_bmad" / "_config" / "agent-manifest.csv"
SELECTION_FILE = PROJECT_ROOT / "data" / "agent_selection.json"


def _read_customize_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _read_agent_manifest() -> list[dict[str, str]]:
    if not AGENT_MANIFEST_FILE.exists():
        return []

    try:
        with AGENT_MANIFEST_FILE.open("r", encoding="utf-8", newline="") as fh:
            rows = csv.DictReader(fh)
            return [
                {
                    "code": str(row.get("name", "")).strip(),
                    "name": str(row.get("displayName", "")).strip(),
                    "title": str(row.get("title", "")).strip(),
                    "description": str(row.get("identity", "")).strip(),
                }
                for row in rows
                if str(row.get("name", "")).strip()
            ]
    except OSError:
        return []


def list_bmad_agents() -> list[dict[str, str]]:
    deduped: dict[str, dict[str, str]] = {
        agent["code"]: agent for agent in _read_agent_manifest()
    }

    if SKILLS_DIR.exists():
        for entry in sorted(SKILLS_DIR.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("agent-"):
                continue

            raw = _read_customize_toml(entry / "customize.toml")
            agent = raw.get("agent", {})

            # Support both current [agent] and legacy/multi-agent [agents.<code>] layouts.
            candidate_agents: list[dict[str, Any]] = []
            if isinstance(agent, dict) and agent:
                candidate_agents.append(agent)

            agents_table = raw.get("agents")
            if isinstance(agents_table, dict):
                for nested_code, nested_agent in agents_table.items():
                    if not isinstance(nested_agent, dict):
                        continue
                    merged = dict(nested_agent)
                    if "code" not in merged:
                        merged["code"] = str(nested_code)
                    candidate_agents.append(merged)

            if not candidate_agents:
                candidate_agents.append({})

            for candidate in candidate_agents:
                code = str(candidate.get("code", entry.name)).strip() or entry.name
                name = str(candidate.get("name", "")).strip() or code
                title = str(candidate.get("title", "")).strip()
                description = str(candidate.get("description", "")).strip()

                deduped[code] = {
                    "code": code,
                    "name": name,
                    "title": title,
                    "description": description,
                }

    return sorted(deduped.values(), key=lambda item: item["code"].lower())


def get_selected_agent_code() -> str | None:
    if not SELECTION_FILE.exists():
        return None

    try:
        with SELECTION_FILE.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None

    code = data.get("selected_agent_code")
    return str(code).strip() if code else None


def set_selected_agent_code(code: str) -> None:
    SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SELECTION_FILE.open("w", encoding="utf-8") as fh:
        json.dump({"selected_agent_code": code}, fh, indent=2)


def get_selected_agent() -> dict[str, str] | None:
    agents = list_bmad_agents()
    if not agents:
        return None

    selected_code = get_selected_agent_code()
    if selected_code:
        for agent in agents:
            if agent["code"] == selected_code:
                return agent

    # Default to first discovered agent and persist fallback when selection is stale.
    fallback = agents[0]
    if selected_code != fallback["code"]:
        set_selected_agent_code(fallback["code"])
    return fallback
