"""Boltpy command-line interface."""
from __future__ import annotations
import asyncio
import sys
import typer
from boltpy.agent.core import Agent
from boltpy.config import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=False, help="A clean terminal coding agent.")

@app.callback(invoke_without_command=True)
def main_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from boltpy.tui.app import BoltpyApp
        BoltpyApp(load_settings()).run()

def _run_prompt(prompt: str, *, allow_tools: bool, debug: bool) -> None:
    async def run() -> None:
        settings = load_settings()
        if allow_tools: settings = settings.model_copy(update={"permission_mode": "allow"})
        agent = Agent(settings)
        try:
            if debug:
                async for event in agent.stream_events(prompt):
                    if event.kind == "text": print(event.text, end="", flush=True)
                    elif event.kind in {"tool_call", "permission"}: typer.echo(f"[debug] {event.kind}: {event.name} {event.arguments or event.status}", err=True)
                    elif event.kind == "tool_result": typer.echo(f"[debug] tool result: {event.name} {event.status}", err=True)
                print()
            else:
                async for token in agent.stream(prompt): print(token, end="", flush=True)
                print()
        finally: await agent.close()
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("boltpy: cancelled", err=True)
        raise typer.Exit(code=130)
    except Exception as error:
        typer.echo(f"boltpy: {error}", err=True)
        raise typer.Exit(code=1) from error

@app.command()
def ask(prompt: str = typer.Argument(..., help="Question to ask the agent."), debug: bool = typer.Option(False, "--debug", help="Show tool and loop diagnostics on stderr.")) -> None:
    """Ask one question and stream the answer to stdout."""
    _run_prompt(prompt, allow_tools=False, debug=debug)

@app.command(name="exec")
def exec_command(prompt: str = typer.Argument(..., help="Prompt to run headlessly with tools allowed."), debug: bool = typer.Option(False, "--debug", help="Show tool and loop diagnostics on stderr.")) -> None:
    """Ask the agent headlessly; tools and SSH run in allow mode."""
    _run_prompt(prompt, allow_tools=True, debug=debug)

def run() -> None:
    app()
