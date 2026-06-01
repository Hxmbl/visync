"""
Discover Ventoy drives and locate ISO files.

What it does:
- Detects Ventoy volumes on Windows, macOS and Linux
- Reads ISO volume IDs straight from the file header
- Maps IDs/filenames to friendly distro names using config.toml or simple rules
- Lists .iso files under a directory and returns their detected names
"""

import tomllib
from pathlib import Path


def load_config(config_path: Path | None = None) -> dict:
    """Load configuration dictionary maps and distro settings from config.toml."""
    path = config_path or Path(__file__).parent.parent / "config.toml"
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        print(f"[-] Critical Error: Failed to parse config.toml database: {e}")
        return {}


def _mount_device(dev: str, detected: list[Path]) -> None:
    """Try to mount a device temporarily and add its path if successful."""
    import subprocess

    import tempfile

    mount_dir = Path(tempfile.mkdtemp(prefix="ventoy_"))
    try:
        subprocess.run(
            ["mount", dev, str(mount_dir)],
            capture_output=True, timeout=10,
        )
        if mount_dir.is_dir() and any(mount_dir.iterdir()):
            detected.append(mount_dir)
    except Exception:
        pass


def _try_mount_ventoy(partition: dict, detected: list[Path]) -> None:
    """When Ventoy data partition is unmounted, find the dm-exposed device and mount it."""
    for child in partition.get("children", []):
        if child.get("mountpoint"):
            continue
        child_name = child.get("name", "")
        child_type = child.get("type", "")
        if not child_name:
            continue
        # dm devices live under /dev/mapper/<name>
        if child_type == "dm":
            dev_path = f"/dev/mapper/{child_name}"
        else:
            dev_path = f"/dev/{child_name}"
        _mount_device(dev_path, detected)
        if detected:
            return


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

        cmd = ["lsblk", "-o", "NAME,TYPE,LABEL,MOUNTPOINT", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                for device in data.get("blockdevices", []):
                    for partition in device.get("children", []):
                        label = partition.get("label")
                        mount = partition.get("mountpoint")
                        if label in ("Ventoy", "VTOYEFI"):
                            if mount:
                                detected_paths.append(Path(mount))
                            elif label == "Ventoy":
                                _try_mount_ventoy(partition, detected_paths)
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: blkid + findmnt (covers systems without lsblk)
        if not detected_paths:
            for lbl in ("Ventoy", "VTOYEFI"):
                try:
                    blkid_proc = subprocess.run(
                        ["blkid", "-L", lbl], capture_output=True, text=True, timeout=10
                    )
                    if blkid_proc.returncode != 0 or not blkid_proc.stdout.strip():
                        continue
                    dev = blkid_proc.stdout.strip()
                    mnt_proc = subprocess.run(
                        ["findmnt", "-n", "-o", "TARGET", dev],
                        capture_output=True, text=True, timeout=10,
                    )
                    if mnt_proc.returncode == 0 and mnt_proc.stdout.strip():
                        detected_paths.append(Path(mnt_proc.stdout.strip()))
                    elif lbl == "Ventoy":
                        _mount_device(dev, detected_paths)
                except Exception:
                    continue

    elif (
        system == "Darwin"
    ):  # macOS <-- This will be able to be tested the most as it is my OS of choice
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

    elif (
        system == "Windows"
    ):  # ERROR: HASNT BEEN TESTED ON WINDOWS YET, BUT SHOULD WORK THEORETICALLY
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
        raise NotImplementedError(
            f"Unsupported operating system: {system}\nThis script currently supports Windows, macOS, and Linux.\nTo add support for your OS, please contribute to github.com/hxmbl/visync"
        )

    # When multiple Ventoy targets are found, warn and default to the first one
    if len(detected_paths) > 1:
        print(
            f"[!] Multiple Ventoy drives detected. Defaulting to: {detected_paths[0]}"
        )
        print(f"    Ignored: {[str(p) for p in detected_paths[1:]]}")

    return detected_paths


def get_iso_volume_id(iso_path: Path) -> str:
    """Read the unchangeable internal Volume Identifier of an ISO file."""
    try:
        with open(iso_path, "rb") as f:
            # Skip directly to the ISO 9660 primary descriptor header
            f.seek(32808)
            volume_id = f.read(32)
            return volume_id.decode("utf-8", errors="ignore").strip("\x00 ")
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

    vol_lower = volume_id.lower().strip()
    file_lower = file_name.lower().strip()

    config = load_config()

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
    """Find all ISO files under the given directory, ignoring macOS resource forks."""
    return [p for p in directory.rglob("*.iso") if not p.name.startswith("._")]


def find_installed_isos_formatted(directory: Path) -> list[str]:
    """Find all ISOs and return their verified distribution names."""
    detected_names = []

    for iso_path in find_installed_isos(directory):
        # Read the internal header label instead of trusting the filename
        volume_id = get_iso_volume_id(iso_path)
        distro = identify_distro(volume_id, iso_path.name)
        detected_names.append(distro)

    return detected_names
