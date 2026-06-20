"""Package manager state and operations for visync.

Tracks which distros are "installed" (wanted) on the Ventoy drive.
State file: .visync/installed.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.finder import (
    find_installed_isos,
    find_ventoy_drives,
    get_iso_volume_id,
    identify_distro,
    load_config,
)
from src.output import console, error, info, success, warn


def _state_path(drive_root: Path) -> Path:
    """Path to the installed.json state file."""
    return drive_root / ".visync" / "installed.json"


def load_installed(drive_root: Path) -> dict:
    """Load the installed distros state. Returns {entry_id: {installed_at, version}}."""
    path = _state_path(drive_root)
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_installed(drive_root: Path, installed: dict) -> None:
    """Save the installed distros state."""
    path = _state_path(drive_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(installed, f, indent=2)


def mark_installed(drive_root: Path, entry_id: str, version: str = "") -> None:
    """Mark a distro as installed."""
    installed = load_installed(drive_root)
    installed[entry_id] = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "version": version,
    }
    save_installed(drive_root, installed)


def mark_removed(drive_root: Path, entry_id: str) -> None:
    """Mark a distro as removed."""
    installed = load_installed(drive_root)
    installed.pop(entry_id, None)
    save_installed(drive_root, installed)


def get_installed_ids(drive_root: Path) -> list[str]:
    """Return list of installed distro entry IDs."""
    return list(load_installed(drive_root).keys())


def resolve_distro(query: str, config: dict) -> str | None:
    """Resolve a user query (name, keyword, partial match) to a distro entry_id.

    Returns the entry_id if found, None otherwise.
    """
    query_lower = query.lower().strip()
    distros = config.get("distros", {})

    # Exact match on entry_id
    if query_lower in {k.lower() for k in distros}:
        for key in distros:
            if key.lower() == query_lower:
                return key

    # Exact match on clean_name
    for entry_id, settings in distros.items():
        if settings.get("clean_name", "").lower() == query_lower:
            return entry_id

    # Partial match on clean_name or entry_id
    for entry_id, settings in distros.items():
        clean = settings.get("clean_name", "").lower()
        if query_lower in clean or query_lower in entry_id.lower():
            return entry_id

    return None
