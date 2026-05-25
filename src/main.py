"""Visync - Ventoy ISO Synchronization Tool."""

from pathlib import Path

import typer

app = typer.Typer()


@app.command()
def sync(
    config: Path = typer.Option(
        "config.toml", "--config", "-c", help="Path to config file"
    ),
) -> None:
    """Sync ISO files to the Ventoy drive."""
    ...


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
) -> None:
    """Verify integrity of ISOs on the Ventoy drive."""
    ...


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
