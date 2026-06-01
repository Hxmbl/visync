"""Visync - Ventoy ISO Synchronization Tool."""

from pathlib import Path

import typer

from src.finder import find_ventoy_drives, load_config
from src.verify import run_directory_verify

app = typer.Typer()


@app.command()
def sync(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
    ),
) -> None:
    """Sync ISO files to the Ventoy drive."""
    from src.download import sync_all_configured_distros

    sync_all_configured_distros()


@app.command()
def list(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
    ),
) -> None:
    """List ISOs on the Ventoy drive and available for download."""
    ...


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
def download(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
    ),
) -> None:
    """Download ISOs locally without syncing."""
    ...


@app.command()
def version() -> None:
    """Show the version of Visync."""
    from . import __version__

    typer.echo(f"Visync version: {__version__}")


if __name__ == "__main__":
    app()
