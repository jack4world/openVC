import sys
from contextlib import contextmanager
from typing import Generator

try:
    from rich.console import Console
    from rich.status import Status

    _console = Console(stderr=True)
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False

VERSION = "v1.0"


def _is_tty() -> bool:
    return sys.stdout.isatty() and sys.stderr.isatty()


def print_banner(json_output: bool = False) -> None:
    if json_output or not _is_tty() or not _RICH_AVAILABLE:
        return
    _console.print(f"[bold cyan]🐦 openVC[/bold cyan] [dim]{VERSION}[/dim]")
    _console.print("[dim]─── AI Video Captioning Pipeline[/dim]")


@contextmanager
def pipeline_status(message: str, json_output: bool = False) -> Generator[None, None, None]:
    if json_output or not _is_tty() or not _RICH_AVAILABLE:
        yield
        return
    with Status(f"[bold cyan]🐦 openVC[/bold cyan] [dim]{VERSION}[/dim]  {message}", console=_console) as status:
        status  # keep reference
        yield
