"""Visync - Ventoy ISO Synchronization Tool.

Built with typer. Run `visync --help` for available commands.
"""

from pathlib import Path

import typer

from src.finder import (
    find_installed_isos,
    find_ventoy_drives,
    get_iso_volume_id,
    identify_distro,
    load_config,
    load_all_metadata,
)
from src.output import console, error, header, info, iso_table, success, warn
from src.verify import extract_version_from_filename, run_directory_verify

app = typer.Typer()


@app.command()
def sync(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be done without doing it"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force re-download even if version matches"
    ),
) -> None:
    """Sync ISO files to the Ventoy drive."""
    from src.download import sync_all_configured_distros

    sync_all_configured_distros(dry_run=dry_run, force=force, config_path=config)


@app.command()
def list(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
    drive: Path | None = typer.Option(
        None,
        "--drive",
        "-d",
        help="Directory to scan (defaults to detected Ventoy drive)",
    ),
) -> None:
    """List ISOs on the Ventoy drive with distro, version, and size."""
    if drive is not None:
        iso_dir = drive
    else:
        drives = find_ventoy_drives()
        if not drives:
            error("No Ventoy drives detected.")
            raise typer.Exit(1)
        iso_dir = drives[0]

    if not iso_dir.is_dir():
        error(f"Not a directory: {iso_dir}")
        raise typer.Exit(1)

    iso_paths = find_installed_isos(iso_dir)
    if not iso_paths:
        warn("No ISO files found.")
        return

    all_meta = load_all_metadata(iso_dir)

    rows = []
    for iso_path in sorted(iso_paths, key=lambda p: p.name):
        meta = all_meta.get(iso_path.name)
        if meta:
            distro = identify_distro(meta.get("variant_stem", ""), iso_path.name)
            version = meta.get("version") or "—"
        else:
            vid = get_iso_volume_id(iso_path)
            distro = identify_distro(vid, iso_path.name)
            version = extract_version_from_filename(iso_path.name) or "—"
        size_gb = iso_path.stat().st_size / (1024**3)
        rows.append((distro, version, f"{size_gb:.1f}G", iso_path.name))

    total_gb_val = sum(
        iso_path.stat().st_size / (1024**3) for iso_path in iso_paths
    )
    iso_table(rows, total_gb_val)


@app.command()
def verify(
    config: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config file"
    ),
    drive: Path | None = typer.Option(
        None,
        "--drive",
        "-d",
        help="Directory to scan (defaults to detected Ventoy drive)",
    ),
) -> None:
    """Verify integrity of ISOs on the Ventoy drive."""
    config_data = load_config(config)
    if drive is not None:
        iso_dir = drive
    else:
        drives = find_ventoy_drives()
        if not drives:
            error("No Ventoy drives detected.")
            raise typer.Exit(1)
        iso_dir = drives[0]

    if not iso_dir.is_dir():
        error(f"Not a directory: {iso_dir}")
        raise typer.Exit(1)

    info(f"Verifying ISOs in {iso_dir} ...")
    results = run_directory_verify(iso_dir, config_data)

    if not results:
        warn("No ISO files found.")
        return

    verified = failed = skipped = 0
    for iso_path, distro, result in results:
        label = f"{iso_path.name} ({distro})"
        if result is True:
            success(label)
            verified += 1
        elif result is False:
            error(f"{label} — checksum mismatch or fetch failed")
            failed += 1
        else:
            info(f"{label} — no checksum config")
            skipped += 1

    console.print()
    info(f"Done: {verified} verified, {failed} failed, {skipped} skipped (no config).")
    if failed:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version of Visync."""
    from . import __version__

    typer.echo(f"Visync version: {__version__}")


if __name__ == "__main__":
    app()
