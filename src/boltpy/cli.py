"""Boltpy command-line interface."""
from __future__ import annotations
import asyncio
import typer
from boltpy.agent.core import Agent
from boltpy.config import load_settings
app = typer.Typer(add_completion=False, no_args_is_help=False, help="A clean terminal coding agent.")

@app.callback(invoke_without_command=True)
def main_command(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        from boltpy.tui.app import BoltpyApp
        BoltpyApp(load_settings()).run()

@app.command()
def ask(prompt: str = typer.Argument(..., help="Question to ask the agent.")) -> None:
    """Ask one question and stream the answer to stdout."""
    async def run() -> None:
        agent = Agent(load_settings())
        try:
            async for token in agent.stream(prompt):
                print(token, end="", flush=True)
            print()
        finally:
            await agent.close()
    try:
        asyncio.run(run())
    except Exception as error:
        typer.echo(f"boltpy: {error}", err=True)
        raise typer.Exit(code=1) from error

def run() -> None:
    app()
