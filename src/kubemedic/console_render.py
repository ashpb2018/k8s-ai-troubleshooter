"""Render agent events to a Rich console for the CLI."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import events
from .agent.events import AgentEvent

_PREVIEW_LINES = 6


class ConsoleRenderer:
    """Turns the agent's event stream into terminal output."""

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, event: AgentEvent) -> None:
        match event:
            case events.Speak(text):
                self.console.print()
                self.console.print(Markdown(text))
                self.console.print()
            case events.ToolStarted(_, tool, arguments):
                self.console.print(f"  [cyan]›[/cyan] [bold]{tool}[/bold] [dim]{arguments}[/dim]")
            case events.ToolFinished(_, _, output):
                self._render_preview(output)
            case events.Notice(message):
                self.console.print(f"  [yellow]{message}[/yellow]")
            case events.Failed(message):
                self.console.print(f"  [red]{message}[/red]")
            case events.RunbookWritten(path, _):
                self.console.print(f"\n[green]Runbook saved:[/green] {path}")
            case events.Finished():
                pass

    def _render_preview(self, output: str) -> None:
        lines = output.splitlines()
        preview = "\n".join(f"    {line}" for line in lines[:_PREVIEW_LINES])
        if len(lines) > _PREVIEW_LINES:
            preview += f"\n    [dim]… {len(lines) - _PREVIEW_LINES} more line(s)[/dim]"
        self.console.print(preview or "    [dim](no output)[/dim]")

    def confirm(self, action: str) -> bool:
        self.console.print(
            Panel(action, title="[bold red]Confirm[/bold red]", border_style="red")
        )
        answer = self.console.input("[bold]Proceed? (yes/no): [/bold]").strip().lower()
        return answer in {"yes", "y"}
