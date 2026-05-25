"""Discover Ventoy drives and locate ISO files."""

from pathlib import Path


def _distro_config_path() -> Path:
    """Resolve config.toml from cwd (runtime) or repo root (development)."""
    cwd_config = Path.cwd() / "config.toml"
    if cwd_config.is_file():
        return cwd_config
    repo_config = Path(__file__).resolve().parent.parent / "config.toml"
    if repo_config.is_file():
        return repo_config
    return cwd_config


def find_ventoy_drives() -> list[Path]:
    """
    Detect mounted Ventoy drives across different operating systems.
    Returns a list of Path objects pointing to the root of each detected Ventoy drive.
    To get drive path just index 0 of the returned list.
    Will be used for multi-drive support later.
    """
    import platform
    import subprocess

    system = platform.system()
    detected_paths = []

    if system == "Linux":
        import json

        cmd = ["lsblk", "-o", "NAME,LABEL,MOUNTPOINT", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            return []

        try:
            data = json.loads(result.stdout)

            for device in data.get("blockdevices", []):
                for partition in device.get("children", []):
                    # Match either Ventoy storage or Ventoy EFI partition
                    if partition.get("label") in [
                        "Ventoy",
                        "VTOYEFI",
                    ] and partition.get("mountpoint"):
                        detected_paths.append(Path(partition["mountpoint"]))
        except (json.JSONDecodeError, KeyError):
            return []

    elif system == "Darwin":  # macOS
        import plistlib

        # Query diskutil for a list of all connected disks in Plist (XML) format
        cmd = ["diskutil", "list", "-plist"]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode != 0:
            return []

        try:
            # Parse the XML output into a Python dictionary
            data = plistlib.loads(result.stdout)

            # Extract volume names and look for matches
            for pool in data.get("AllDisksAndPartitions", []):
                for partition in pool.get("Partitions", [pool]):
                    volume_name = partition.get("VolumeName")
                    mount_point = partition.get("MountPoint")

                    # Match either Ventoy storage or Ventoy EFI, ensuring it's actually mounted
                    if volume_name in ["Ventoy", "VTOYEFI"] and mount_point:
                        detected_paths.append(Path(mount_point))
        except Exception:
            return []

    elif system == "Windows":
        import json

        # Force a JSON array expression using @(...) and match Ventoy or VTOYEFI labels
        cmd = "@(Get-Volume | Where-Object {$_.FileSystemLabel -match 'Ventoy|VTOYEFI'} | Select-Object DriveLetter) | ConvertTo-Json"
        result = subprocess.run(
            ["powershell", "-Command", cmd], capture_output=True, text=True
        )

        if not result.stdout.strip():
            return []

        # Explicitly clear/initialize variable state prior to evaluation
        detected_paths = []
        try:
            drives_data = json.loads(result.stdout)
            # Ensure data is handled as a list even if only one drive is returned
            if isinstance(drives_data, dict):
                drives_data = [drives_data]

            # Add :\\ to get the true volume root path
            detected_paths = [
                Path(f"{drive['DriveLetter']}:\\")
                for drive in drives_data
                if drive.get("DriveLetter")
            ]
        except json.JSONDecodeError:
            return []

    else:
        raise NotImplementedError(f"Unsupported operating system: {system}")

    # Error handling for when multiple Ventoy targets are found
    if len(detected_paths) > 1:
        raise RuntimeError(
            f"Multiple Ventoy drives detected, this is not supported *yet*: {[str(p) for p in detected_paths]}. Please connect only one."
        )

    return detected_paths


def get_iso_volume_id(iso_path: Path) -> str:
    """Read the unchangeable internal Volume Identifier of an ISO file."""
    try:
        with open(iso_path, "rb") as f:
            # Skip directly to the ISO 9660 primary descriptor header
            f.seek(32808)
            volume_id = f.read(32)
            return volume_id.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def identify_distro(volume_id: str, file_name: str) -> str:
    """
    Match the OS distribution using a cascading hybrid approach:
    1. Strict internal Volume ID matches from config.toml
    2. Contextual filename overrides for forks sharing a base ID
    3. Smart filename regex parsing fallback
    """
    import re
    import tomllib

    vol_lower = volume_id.lower().strip()
    file_lower = file_name.lower().strip()

    config_path = _distro_config_path()
    try:
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
    except Exception:
        config = {}

    # Layer 1 & 2: Match Base Distros and check for Contextual Fork Overrides
    base_distros = config.get("base_distros", {})
    fork_overrides = config.get("fork_overrides", {})

    for base_key, base_name in base_distros.items():
        if base_key in vol_lower:
            # Look for specific structural overrides belonging to this base
            for override_key, clean_name in fork_overrides.items():
                parent, _, keyword = override_key.partition(".")
                if parent == base_key and keyword in file_lower:
                    return clean_name
            return base_name

    # Layer 3: Standalone match rules (text matching on volume ID or filename)
    standalone_matches = config.get("standalone_matches", {})
    for keyword, clean_name in standalone_matches.items():
        if keyword in vol_lower or keyword in file_lower:
            return clean_name

    # Layer 4: Final generic fallback — regex filename parsing (ISO files only)
    if not file_lower.endswith(".iso"):
        return "Unknown OS"

    name_match = re.match(r"^([a-zA-Z_\-]+?)(?:[-_]v?\d|\.)", file_name)
    if name_match:
        extracted_name = (
            name_match.group(1).replace("-", " ").replace("_", " ").title().strip()
        )
        return extracted_name

    return "Unknown OS"


def find_installed_isos(directory: Path) -> list[Path]:
    """Find all ISO files under the given directory."""
    return list(directory.rglob("*.iso"))


def find_installed_isos_formatted(directory: Path) -> list[str]:
    """Find all ISOs and return their verified distribution names."""
    detected_names = []

    for iso_path in find_installed_isos(directory):
        # Read the internal header label instead of trusting the filename
        volume_id = get_iso_volume_id(iso_path)
        distro = identify_distro(volume_id, iso_path.name)
        detected_names.append(distro)

    return detected_names
