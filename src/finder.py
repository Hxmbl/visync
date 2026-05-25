"""Discover Ventoy drives and locate ISO files."""

import platform
from pathlib import Path


def find_ventoy_drives() -> list[Path]:
    """Detect mounted Ventoy USB drives on the system."""
    system = platform.system()
    if system == "Linux":
        # Linux-specific logic to find Ventoy drives
        ...
    elif system == "Darwin":  # macOS
        # macOS-specific logic to find Ventoy drives
        ...
    elif system == "Windows":
        # Windows-specific logic to find Ventoy drives
        ...

    else:
        raise NotImplementedError(f"Unsupported operating system: {system}")


def find_isos(directory: Path) -> list[Path]:
    """Find all ISO files under the given directory."""
    ...


def get_installed_isos(ventoy_mount: Path) -> list[Path]:
    """List ISO files already present on the Ventoy drive."""
    ...
