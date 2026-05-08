from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from threading import Lock

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills"
AGENT_MANIFEST_FILE = PROJECT_ROOT / "_bmad" / "_config" / "agent-manifest.csv"
SELECTION_FILE = PROJECT_ROOT / "data" / "agent_selection.json"
_SELECTION_LOCK = Lock()


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
    code, _ = _read_selected_agent_code()
    return code


def _read_selected_agent_code() -> tuple[str | None, str]:
    """Read selected agent code from persistent storage.

    Returns:
        (code, state) where state indicates:
        - "ok": Successfully read and parsed valid code.
        - "missing": Selection file does not exist.
        - "invalid_json": File exists but contains invalid JSON.
        - "empty": File valid but selected_agent_code key is empty/missing.
        - "read_error": Transient read error (OSError, permission denied, etc).
    """
    if not SELECTION_FILE.exists():
        return None, "missing"

    try:
        with _SELECTION_LOCK:
            with SELECTION_FILE.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
    except json.JSONDecodeError as exc:
        logging.warning("Selected agent file invalid JSON: %s", exc)
        return None, "invalid_json"
    except (OSError, PermissionError, IOError) as exc:
        logging.warning("Transient selection file read error: %s", exc)
        return None, "read_error"
    except Exception as exc:
        logging.error("Unexpected error reading selected agent: %s", exc)
        return None, "read_error"

    code = data.get("selected_agent_code")
    cleaned = str(code).strip() if code else ""
    if not cleaned:
        return None, "empty"
    return cleaned, "ok"


def set_selected_agent_code(code: str) -> None:
    SELECTION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"selected_agent_code": code}, indent=2)

    with _SELECTION_LOCK:
        # Create backup before writing
        try:
            from app.services.config_audit import backup_config_file
            backup_config_file(SELECTION_FILE, "agent_selection")
        except (ImportError, OSError):
            pass  # Continue with write even if backup fails
        
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=SELECTION_FILE.parent,
            delete=False,
            prefix="agent_selection_",
            suffix=".tmp",
        ) as temp_file:
            temp_file.write(payload)
            temp_path = Path(temp_file.name)

        try:
            os.replace(temp_path, SELECTION_FILE)
        finally:
            if temp_path.exists():
                temp_path.unlink()


def get_selected_agent() -> dict[str, str] | None:
    agents = list_bmad_agents()
    if not agents:
        return None

    selected_code, selection_state = _read_selected_agent_code()
    if selected_code:
        for agent in agents:
            if agent["code"] == selected_code:
                return agent

    # Default to first discovered agent and persist fallback when selection is stale
    # or structurally invalid. Do not overwrite selection on transient read errors.
    fallback = agents[0]
    if selection_state != "read_error":
        set_selected_agent_code(fallback["code"])
    return fallback
