"""Discover Ventoy drives and locate ISO files."""


def find_ventoy_drives() -> list[Path]:
    """
    Detect mounted Ventoy drives across different operating systems.
    Returns a list of Path objects pointing to the root of each detected Ventoy drive.
    Will be used for multi-drive support later.
    """
    import platform
    import subprocess
    from pathlib import Path

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
            f"Multiple Ventoy drives detected: {[str(p) for p in detected_paths]}. Please connect only one."
        )

    return detected_paths


def find_isos(directory: Path) -> list[Path]:
    """Find all ISO files under the given directory."""
    ...


def get_installed_isos(ventoy_mount: Path) -> list[Path]:
    """List ISO files already present on the Ventoy drive."""
    ...
