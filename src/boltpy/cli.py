"""Bolt command-line interface."""
from __future__ import annotations
import asyncio
import importlib.metadata
from pathlib import Path
import typer
from boltpy.agent.core import Agent
from boltpy.config import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=False, context_settings={"help_option_names": ["-h", "--help"]}, help="A terminal coding agent.")

@app.callback(invoke_without_command=True)
def main_command(
    ctx: typer.Context,
    project: Path = typer.Option(Path("."), "--project", "-p", help="Workspace directory."),
    models_flag: bool = typer.Option(False, "--models", help="List configured provider models."),
    model: str | None = typer.Option(None, "--model", help="Model for this session."),
    provider: str | None = typer.Option(None, "--provider", help="Provider for this session."),
    endpoint: str | None = typer.Option(None, "--endpoint", help="Provider endpoint for this session."),
    version: bool = typer.Option(False, "--version", "-V", help="Show Bolt version."),
) -> None:
    if version:
        try:
            value = importlib.metadata.version("bolt")
        except importlib.metadata.PackageNotFoundError:
            value = "development"
        typer.echo(f"Bolt {value}")
        raise typer.Exit()
    workspace = project.expanduser().resolve()
    if not workspace.is_dir():
        typer.echo(f"Bolt: workspace does not exist or is not a directory: {project}", err=True)
        raise typer.Exit(code=2)
    settings = load_settings().model_copy(update={"workspace": workspace})
    updates = {key: value for key, value in {"model": model, "provider": provider, "base_url": endpoint}.items() if value is not None}
    if updates:
        settings = settings.model_copy(update=updates)
    if models_flag:
        models(settings)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from boltpy.tui.app import BoltpyApp
        BoltpyApp(settings).run()

def _run_prompt(prompt: str, *, allow_tools: bool, debug: bool, model: str | None = None, provider: str | None = None) -> None:
    async def run_agent() -> None:
        settings = load_settings().model_copy(update={"workspace": Path.cwd().resolve()})
        updates = {"model": model} if model else {}
        if provider: updates["provider"] = provider
        if allow_tools: updates["permission_mode"] = "allow"
        if updates: settings = settings.model_copy(update=updates)
        agent = Agent(settings)
        try:
            async for event in agent.stream_events(prompt):
                if event.kind == "text": print(event.text, end="", flush=True)
                elif debug and event.kind in {"tool_call", "permission", "tool_result"}: typer.echo(f"[debug] {event.kind}: {event.name} {event.arguments or event.status}", err=True)
            print()
        finally:
            await agent.close()
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        typer.echo("bolt: cancelled", err=True); raise typer.Exit(code=130)
    except Exception as error:
        typer.echo(f"bolt: {error}", err=True); raise typer.Exit(code=1) from error

@app.command()
def ask(prompt: str = typer.Argument(...), debug: bool = typer.Option(False, "--debug"), model: str | None = typer.Option(None, "--model"), provider: str | None = typer.Option(None, "--provider")) -> None:
    """Ask one question and stream the answer."""
    _run_prompt(prompt, allow_tools=False, debug=debug, model=model, provider=provider)

@app.command(name="exec")
def exec_command(prompt: str = typer.Argument(...), debug: bool = typer.Option(False, "--debug"), model: str | None = typer.Option(None, "--model"), provider: str | None = typer.Option(None, "--provider")) -> None:
    """Run a prompt headlessly with tools allowed."""
    _run_prompt(prompt, allow_tools=True, debug=debug, model=model, provider=provider)

@app.command()
def doctor() -> None:
    """Check Bolt, workspace, provider connectivity, and active model."""
    settings = load_settings()
    typer.echo("Bolt Doctor")
    typer.echo(f"✓ Bolt {importlib.metadata.version('bolt')}")
    typer.echo(f"✓ Python {__import__('sys').version_info.major}.{__import__('sys').version_info.minor}")
    if settings.workspace.is_dir():
        typer.echo(f"✓ Workspace accessible: {settings.workspace}")
    else:
        typer.echo(f"✗ Workspace inaccessible: {settings.workspace}")
        raise typer.Exit(code=1)

    async def check_provider() -> tuple[bool, list[str], str]:
        from boltpy.agent.providers import build_provider
        provider = build_provider(settings)
        try:
            healthy, message = await provider.health_check()
            names = await provider.list_models() if healthy else []
            return healthy, names, message
        finally:
            await provider.close()

    try:
        healthy, names, message = asyncio.run(check_provider())
    except Exception as error:
        typer.echo(f"✗ Provider unavailable: {error}")
        raise typer.Exit(code=1) from error
    if not healthy:
        typer.echo(f"✗ Provider unavailable: {message}")
        raise typer.Exit(code=1)
    typer.echo(f"✓ Provider reachable: {settings.provider}")
    if settings.model in names:
        typer.echo(f"✓ Active model available: {settings.model}")
    else:
        typer.echo(f"✗ Active model unavailable: {settings.model}")
        typer.echo("  Use bolt models or set BOLT_MODEL to an installed model.")
        raise typer.Exit(code=1)


@app.command(name="models")
def models(settings=None) -> None:
    """List models exposed by the configured provider."""
    async def list_models() -> None:
        from boltpy.agent.providers import build_provider
        provider = build_provider(settings or load_settings())
        try:
            for name in await provider.list_models(): typer.echo(name)
        finally: await provider.close()
    try: asyncio.run(list_models())
    except Exception as error:
        typer.echo(f"bolt: {error}", err=True); raise typer.Exit(code=1) from error

def run() -> None:
    app()
