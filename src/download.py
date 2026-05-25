"""Download ISO files from URLs or other sources."""

from pathlib import Path


def download_iso(url: str, dest: Path) -> Path:
    """Download an ISO from a URL to the destination directory."""
    ...


def download_checksums(url: str, dest: Path) -> Path:
    """Download checksum files associated with an ISO."""
    ...


def list_available_isos() -> list[dict]:
    """Return a list of available ISOs from configured sources."""
    ...
