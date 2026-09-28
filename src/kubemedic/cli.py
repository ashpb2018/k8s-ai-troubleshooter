"""KubeMedic command-line interface."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .agent import Investigator
from .agent.events import RunbookWritten
from .agent.incident import Incident
from .assembly import Runtime, assemble
from .console_render import ConsoleRenderer
from .settings import Backend, Settings, load_settings

app = typer.Typer(
    name="kubemedic",
    help="An LLM-driven agent that diagnoses and repairs Kubernetes clusters.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


# --------------------------------------------------------------------- helpers


def _apply_overrides(
    settings: Settings,
    *,
    backend: str | None,
    model: str | None,
    context: str | None,
    auto_approve: bool,
) -> None:
    if backend:
        settings.backend = Backend(backend)
    if model:
        field = {
            Backend.OLLAMA: "ollama_model",
            Backend.OPENAI: "openai_model",
            Backend.BEDROCK: "bedrock_model_id",
        }[settings.backend]
        setattr(settings, field, model)
    if context:
        settings.k8s_context = context
    if auto_approve:
        settings.auto_approve = True


def _bootstrap(
    backend: str | None,
    model: str | None,
    context: str | None,
    auto_approve: bool,
) -> Runtime:
    settings = load_settings()
    _apply_overrides(
        settings, backend=backend, model=model, context=context, auto_approve=auto_approve
    )
    try:
        with console.status("[green]Connecting to the cluster and backend…"):
            runtime = assemble(settings)
    except Exception as exc:  # noqa: BLE001 - user-facing startup failure
        console.print(f"[red]Startup failed:[/red] {exc}")
        raise typer.Exit(1) from exc
    _print_banner(runtime)
    return runtime


def _print_banner(runtime: Runtime) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Backend", runtime.backend.describe())
    grid.add_row("Context", runtime.client.active_context())
    grid.add_row("K8s version", runtime.client.server_version())
    grid.add_row("Runbooks", str(runtime.settings.runbook_dir))
    grid.add_row(
        "Auto-approve",
        "[red]on[/red]" if runtime.settings.auto_approve else "[green]off[/green]",
    )
    console.print(grid)


def _new_investigator(runtime: Runtime, renderer: ConsoleRenderer) -> Investigator:
    return Investigator(
        runtime.backend,
        runtime.operations,
        emit=renderer,
        confirm=renderer.confirm,
        max_steps=runtime.settings.max_agent_steps,
    )


def _persist_runbook(runtime: Runtime, incident: Incident, renderer: ConsoleRenderer) -> None:
    path = runtime.runbooks.save(incident)
    runtime.runbooks.write_index()
    renderer(RunbookWritten(str(path), path.name))


# -------------------------------------------------------------------- commands


@app.command()
def chat(
    backend: str | None = typer.Option(None, "--backend", "-b", help="ollama | bedrock | openai"),
    model: str | None = typer.Option(None, "--model", "-m"),
    context: str | None = typer.Option(None, "--context", "-c"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
) -> None:
    """Open an interactive troubleshooting session."""
    runtime = _bootstrap(backend, model, context, auto_approve)
    renderer = ConsoleRenderer(console)
    agent = _new_investigator(runtime, renderer)

    console.print(
        "\n[bold]KubeMedic[/bold] ready. Describe an issue, type [bold]scan[/bold] "
        "for a full sweep, or [bold]exit[/bold] to quit.\n"
    )
    while True:
        try:
            message = console.input("[bold blue]you ›[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye.[/dim]")
            return
        if not message:
            continue
        if message.lower() in {"exit", "quit", "q"}:
            console.print("[dim]Bye.[/dim]")
            return
        if message.lower() == "scan":
            agent.scan()
        else:
            agent.investigate(message)


@app.command()
def scan(
    backend: str | None = typer.Option(None, "--backend", "-b"),
    model: str | None = typer.Option(None, "--model", "-m"),
    context: str | None = typer.Option(None, "--context", "-c"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
) -> None:
    """Run a one-shot cluster health sweep and write a runbook."""
    runtime = _bootstrap(backend, model, context, auto_approve)
    renderer = ConsoleRenderer(console)
    agent = _new_investigator(runtime, renderer)
    console.print("\n[bold]Scanning the cluster…[/bold]\n")
    incident = agent.scan()
    _persist_runbook(runtime, incident, renderer)


@app.command()
def fix(
    problem: str = typer.Argument(..., help="Describe the problem in plain language"),
    backend: str | None = typer.Option(None, "--backend", "-b"),
    model: str | None = typer.Option(None, "--model", "-m"),
    context: str | None = typer.Option(None, "--context", "-c"),
    namespace: str | None = typer.Option(None, "--namespace", "-n"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
) -> None:
    """Diagnose and repair a specific problem, then write a runbook."""
    runtime = _bootstrap(backend, model, context, auto_approve)
    renderer = ConsoleRenderer(console)
    agent = _new_investigator(runtime, renderer)

    request = f"[namespace: {namespace}] {problem}" if namespace else problem
    console.print(f"\n[bold]Problem:[/bold] {request}\n")
    incident = agent.investigate(request)
    _persist_runbook(runtime, incident, renderer)


@app.command()
def runbooks() -> None:
    """List runbooks written so far."""
    settings = load_settings()
    directory = settings.runbook_dir
    if not directory.exists():
        console.print("[yellow]No runbooks yet. Run a scan or fix first.[/yellow]")
        raise typer.Exit()

    files = [p for p in sorted(directory.glob("*.md"), reverse=True) if p.name != "index.md"]
    if not files:
        console.print("[yellow]No runbooks yet.[/yellow]")
        raise typer.Exit()

    table = Table(title="Runbooks", header_style="bold blue")
    table.add_column("#", style="dim", width=4)
    table.add_column("Runbook")
    table.add_column("Date", width=18)
    for i, path in enumerate(files, 1):
        table.add_row(str(i), _pretty_title(path), _pretty_date(path))
    console.print(table)


def _pretty_date(path: Path) -> str:
    try:
        return datetime.strptime(path.stem[:15], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "?"


def _pretty_title(path: Path) -> str:
    remainder = path.stem[16:]
    return remainder.replace("-", " ").title() if remainder else path.stem


if __name__ == "__main__":
    app()
