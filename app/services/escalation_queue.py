from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _mask_user_handle(value: str | None) -> str:
    handle = (value or "").strip()
    if not handle:
        return ""
    if len(handle) <= 4:
        return f"{handle[:2]}***"
    return f"{handle[:3]}...{handle[-4:]}"


def append_review_artifact(
    app,
    *,
    correlation_id: str | None,
    reason: str,
    wa_id: str | None,
    message_id: str | None,
) -> tuple[bool, str | None]:
    path = Path(str(app.config.get("ESCALATION_QUEUE_PATH", "data/operator_review_queue.jsonl")))
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "correlation_id": correlation_id,
        "reason": reason,
        "masked_user_handle": _mask_user_handle(wa_id),
        "message_id": message_id,
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, separators=(",", ":")) + "\n")
        return True, None
    except OSError as exc:
        return False, str(exc)
