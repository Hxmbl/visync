"""Rich-based output formatting for visync."""

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TransferSpeedColumn,
)
from rich.status import Status
from rich.table import Table

console = Console()

_status: Status | None = None


def spin_start(msg: str) -> None:
    """Start a global spinner at the bottom of the console."""
    global _status
    _status = Status(msg, spinner="dots", console=console)
    _status.start()


def spin_update(msg: str) -> None:
    """Update the global spinner message."""
    if _status:
        _status.update(msg)


def spin_stop() -> None:
    """Stop the global spinner."""
    global _status
    if _status:
        _status.stop()
        _status = None


def header(text: str) -> None:
    console.print(f"\n[bold]{text}[/bold]\n")


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
