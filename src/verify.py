"""Verify ISO integrity using checksums."""

from pathlib import Path


def verify_checksum(iso_path: Path, checksum_path: Path) -> bool:
    """Check the ISO against its checksum file."""
    ...


def verify_all_isos(iso_dir: Path) -> list[tuple[Path, bool]]:
    """Verify all ISOs in a directory and return results."""
    ...
