"""Configuration audit trail and backup management.

Tracks all operator-initiated configuration changes (who, what, when) and maintains
versioned backups of critical configuration files for recovery purposes.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Thread-safe access to audit logs and backups
_AUDIT_LOCK = threading.Lock()

# Audit log file: tracks all configuration changes
AUDIT_LOG_FILE = Path(__file__).resolve().parents[2] / "data" / "config_audit.jsonl"

# Backup directory: maintains versioned backups of configuration files
BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "config_backups"

# Maximum number of backups to retain per configuration file
MAX_BACKUPS_PER_FILE = 20


def _ensure_directories() -> None:
    """Create audit and backup directories if they don't exist."""
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _timestamp_iso() -> str:
    """Return current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def record_config_change(
    config_file: str,
    key: str,
    old_value: str | None,
    new_value: str,
    operator_role: str = "operator",
) -> None:
    """Record a configuration change to the audit log.
    
    Args:
        config_file: Name of the configuration file (e.g., ".env", "agent_selection.json")
        key: Configuration key/property that was changed
        old_value: Previous value (None if new key)
        new_value: New value after change
        operator_role: Role of the operator making the change
    """
    _ensure_directories()
    
    entry = {
        "timestamp": _timestamp_iso(),
        "config_file": config_file,
        "key": key,
        "old_value": old_value,
        "new_value": new_value,
        "operator_role": operator_role,
    }
    
    with _AUDIT_LOCK:
        try:
            with AUDIT_LOG_FILE.open("a", encoding="utf-8") as fh:
                json.dump(entry, fh)
                fh.write("\n")
        except OSError as exc:
            logger.warning(f"Failed to write audit log entry: {exc}")


def backup_config_file(
    source_path: Path,
    config_name: str,
) -> None:
    """Create a timestamped backup of a configuration file.
    
    Args:
        source_path: Full path to the source configuration file
        config_name: Logical name for the configuration (e.g., "env", "agent_selection")
        
    Raises:
        OSError: If backup cannot be created
        TimeoutError: If unable to acquire lock within timeout
    """
    _ensure_directories()
    
    if not source_path.exists():
        return
    
    with _AUDIT_LOCK:
        # Create timestamped backup
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{config_name}_{timestamp}.bak"
        
        # Read and backup the file atomically
        try:
            content = source_path.read_text(encoding="utf-8")
            backup_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            logger.error(f"Failed to backup {config_name} to {backup_path}: {exc}")
            raise
        
        # Prune old backups to keep directory size manageable
        _prune_old_backups(config_name)


def _prune_old_backups(config_name: str) -> None:
    """Remove old backups beyond the retention limit.
    
    Keeps the most recent MAX_BACKUPS_PER_FILE backups for each config file.
    """
    try:
        pattern = f"{config_name}_*.bak"
        backups = sorted(BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        
        for old_backup in backups[MAX_BACKUPS_PER_FILE:]:
            try:
                old_backup.unlink()
            except OSError as exc:
                logger.warning(f"Failed to remove old backup {old_backup}: {exc}")
    except OSError as exc:
        logger.warning(f"Error during backup pruning: {exc}")


def get_config_change_history(config_file: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Retrieve configuration change history.
    
    Args:
        config_file: Filter by specific config file (None = all files)
        limit: Maximum number of entries to return
        
    Returns:
        List of change records, most recent first
    """
    _ensure_directories()
    
    if not AUDIT_LOG_FILE.exists():
        return []
    
    changes: list[dict[str, Any]] = []
    
    with _AUDIT_LOCK:
        try:
            with AUDIT_LOG_FILE.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                        if config_file is None or entry.get("config_file") == config_file:
                            changes.append(entry)
                    except json.JSONDecodeError:
                        logger.warning(f"Skipping malformed audit log entry: {line}")
        except OSError as exc:
            logger.warning(f"Failed to read audit log: {exc}")
    
    # Return most recent entries first, limited to requested count
    return sorted(changes, key=lambda e: e.get("timestamp", ""), reverse=True)[:limit]


def list_available_backups(config_name: str) -> list[dict[str, Any]]:
    """List all available backups for a configuration.
    
    Args:
        config_name: Logical name of the configuration (e.g., "env", "agent_selection")
        
    Returns:
        List of backup metadata, most recent first
    """
    _ensure_directories()
    
    backups: list[dict[str, Any]] = []
    
    try:
        pattern = f"{config_name}_*.bak"
        for backup_path in sorted(BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            stat = backup_path.stat()
            backups.append({
                "filename": backup_path.name,
                "timestamp": backup_path.name.replace(f"{config_name}_", "").replace(".bak", ""),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
    except OSError as exc:
        logger.warning(f"Failed to list backups for {config_name}: {exc}")
    
    return backups


def restore_config_from_backup(config_name: str, backup_filename: str, target_path: Path) -> None:
    """Restore a configuration file from a backup.
    
    Args:
        config_name: Logical name of the configuration
        backup_filename: Name of the backup file to restore from
        target_path: Path where the restored file should be written
        
    Raises:
        FileNotFoundError: If backup file does not exist
        OSError: If restore operation fails
    """
    _ensure_directories()
    
    backup_path = BACKUP_DIR / backup_filename
    
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup not found: {backup_filename}")
    
    # Verify backup path is within BACKUP_DIR to prevent traversal attacks
    try:
        backup_path.resolve().relative_to(BACKUP_DIR.resolve())
    except ValueError:
        raise ValueError(f"Invalid backup file path: {backup_filename}")
    
    with _AUDIT_LOCK:
        try:
            content = backup_path.read_text(encoding="utf-8")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
            logger.info(f"Restored {config_name} from backup: {backup_filename}")
        except OSError as exc:
            logger.error(f"Failed to restore {config_name} from {backup_filename}: {exc}")
            raise
