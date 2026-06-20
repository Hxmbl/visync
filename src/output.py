"""Rich-based output formatting for visync."""

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

console = Console()


def header(text: str) -> None:
    console.print(Panel(text, style="bold cyan", expand=False))


def success(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def info(msg: str) -> None:
    console.print(f"  [dim]{msg}[/dim]")


def warn(msg: str) -> None:
    console.print(f"  [yellow]⚠[/yellow] {msg}")


def error(msg: str) -> None:
    console.print(f"  [red]✗[/red] {msg}")


def removed(msg: str) -> None:
    console.print(f"  [yellow]–[/yellow] {msg}")


def section(title: str) -> None:
    console.print()
    console.rule(f"[bold]{title}[/bold]", style="cyan")
    console.print()


def iso_table(rows: list[tuple[str, str, str, str]], total_gb: float) -> None:
    """Render a rich table of ISO files."""
    table = Table(
        show_header=True,
        header_style="bold",
        pad_edge=False,
        show_lines=False,
    )
    table.add_column("Distro", style="cyan", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Size", justify="right", style="magenta")
    table.add_column("Filename", style="dim")

    for distro, version, size, filename in rows:
        table.add_row(distro, version, size, filename)

    console.print(table)
    console.print(
        f"\n  [dim]{len(rows)} ISO(s) — {total_gb:.1f} GiB total[/dim]"
    )


def make_download_progress() -> Progress:
    """Create a rich Progress bar for ISO downloads."""
    return Progress(
        TextColumn("[bold blue]{task.fields[filename]}[/bold blue]"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    )


def copy_progress(filename: str) -> None:
    console.print(f"  [cyan]⟳[/cyan] Copying {filename} to drive...")
