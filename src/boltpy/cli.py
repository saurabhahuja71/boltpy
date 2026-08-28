"""Bolt command-line interface."""
from __future__ import annotations
import asyncio
from pathlib import Path
import typer
from boltpy.agent.core import Agent
from boltpy.config import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=False, help="A terminal coding agent.")

@app.callback(invoke_without_command=True)
def main_command(ctx: typer.Context, project: Path = typer.Option(Path("."), "--project", "-p", help="Workspace directory."), models_flag: bool = typer.Option(False, "--models", help="List configured provider models.")) -> None:
    if models_flag:
        models()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from boltpy.tui.app import BoltpyApp
        BoltpyApp(load_settings().model_copy(update={"workspace": project.resolve()})).run()

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

@app.command(name="models")
def models() -> None:
    """List models exposed by the configured provider."""
    async def list_models() -> None:
        from boltpy.agent.providers import build_provider
        provider = build_provider(load_settings())
        try:
            for name in await provider.list_models(): typer.echo(name)
        finally: await provider.close()
    try: asyncio.run(list_models())
    except Exception as error:
        typer.echo(f"bolt: {error}", err=True); raise typer.Exit(code=1) from error

def run() -> None:
    app()
