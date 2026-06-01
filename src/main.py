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
from src.verify import extract_version_from_filename, run_directory_verify

app = typer.Typer()


@app.command()
def sync(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
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

    sync_all_configured_distros(dry_run=dry_run, force=force)


@app.command()
def list(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
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
            typer.echo("[-] No Ventoy drives detected.", err=True)
            raise typer.Exit(1)
        iso_dir = drives[0]

    if not iso_dir.is_dir():
        typer.echo(f"[-] Not a directory: {iso_dir}", err=True)
        raise typer.Exit(1)

    iso_paths = find_installed_isos(iso_dir)
    if not iso_paths:
        typer.echo("[-] No ISO files found.")
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

    # Calculate column widths
    col_distro = max(len(r[0]) for r in rows)
    col_version = max(len(r[1]) for r in rows)
    col_size = max(len(r[2]) for r in rows)

    header = (
        f"  {'Distro':<{col_distro}}  "
        f"{'Version':<{col_version}}  "
        f"{'Size':<{col_size}}  "
        f"Filename"
    )
    typer.echo(f"\n  {header}")
    typer.echo(f"  {'─' * col_distro}  {'─' * col_version}  {'─' * col_size}  {'─' * 40}")

    for distro, version, size, filename in rows:
        typer.echo(
            f"  {distro:<{col_distro}}  "
            f"{version:<{col_version}}  "
            f"{size:<{col_size}}  "
            f"{filename}"
        )

    total_gb_val = sum(
        iso_path.stat().st_size / (1024**3) for iso_path in iso_paths
    )
    typer.echo(f"\n  {len(rows)} ISO(s) — {total_gb_val:.1f} GiB total")


@app.command()
def verify(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
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
            typer.echo("[-] No Ventoy drives detected.", err=True)
            raise typer.Exit(1)
        iso_dir = drives[0]

    if not iso_dir.is_dir():
        typer.echo(f"[-] Not a directory: {iso_dir}", err=True)
        raise typer.Exit(1)

    typer.echo(f"[*] Verifying ISOs in {iso_dir} ...")
    results = run_directory_verify(iso_dir, config_data)

    if not results:
        typer.echo("[-] No ISO files found.")
        return

    verified = failed = skipped = 0
    for iso_path, distro, result in results:
        label = f"{iso_path.name} ({distro})"
        if result is True:
            typer.echo(f"[✓] {label}")
            verified += 1
        elif result is False:
            typer.echo(f"[✗] {label} — checksum mismatch or fetch failed", err=True)
            failed += 1
        else:
            typer.echo(f"[-] {label} — no checksum config")
            skipped += 1

    typer.echo(
        f"\n[*] Done: {verified} verified, {failed} failed, {skipped} skipped (no config)."
    )
    if failed:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version of Visync."""
    from . import __version__

    typer.echo(f"Visync version: {__version__}")


if __name__ == "__main__":
    app()
