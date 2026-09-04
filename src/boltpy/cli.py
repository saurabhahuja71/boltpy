"""Bolt command-line interface."""
from __future__ import annotations
import asyncio
import importlib.metadata
from pathlib import Path
import subprocess
import typer
from boltpy.agent.core import Agent
from boltpy.config import load_settings, resolve_resume

app = typer.Typer(add_completion=False, no_args_is_help=False, context_settings={"help_option_names": ["-h", "--help"]}, help="A terminal coding agent.")

@app.callback(invoke_without_command=True)
def main_command(
    ctx: typer.Context,
    project: Path = typer.Option(Path("."), "--project", "-p", help="Workspace directory."),
    models_flag: bool = typer.Option(False, "--models", help="List configured provider models."),
    model: str | None = typer.Option(None, "--model", help="Model for this session."),
    provider: str | None = typer.Option(None, "--provider", help="Provider for this session."),
    endpoint: str | None = typer.Option(None, "--endpoint", help="Provider endpoint for this session."),
    resume: bool | None = typer.Option(None, "--resume/--no-resume", help="Resume the previous session; fresh by default. BOLT_RESUME=1 also enables resume."),
    version: bool = typer.Option(False, "--version", "-V", help="Show Bolt version."),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["resume"] = resume
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
    settings = resolve_resume(resume, settings)
    updates = {key: value for key, value in {"model": model, "provider": provider, "base_url": endpoint}.items() if value is not None}
    if updates:
        settings = settings.model_copy(update=updates)
    if models_flag:
        models(settings)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from boltpy.tui.app import BoltpyApp
        BoltpyApp(settings).run()

def _run_prompt(prompt: str, *, allow_tools: bool, debug: bool, model: str | None = None, provider: str | None = None, resume: bool | None = None) -> None:
    async def run_agent() -> None:
        settings = load_settings().model_copy(update={"workspace": Path.cwd().resolve()})
        settings = resolve_resume(resume, settings)
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
def ask(ctx: typer.Context, prompt: str = typer.Argument(...), debug: bool = typer.Option(False, "--debug"), model: str | None = typer.Option(None, "--model"), provider: str | None = typer.Option(None, "--provider"), resume: bool | None = typer.Option(None, "--resume/--no-resume", help="Resume the previous session; fresh by default.")) -> None:
    """Ask one question and stream the answer."""
    inherited_resume = ctx.parent.obj.get("resume") if ctx.parent and ctx.parent.obj else None
    _run_prompt(prompt, allow_tools=False, debug=debug, model=model, provider=provider, resume=resume if resume is not None else inherited_resume)

@app.command(name="exec")
def exec_command(ctx: typer.Context, prompt: str = typer.Argument(...), debug: bool = typer.Option(False, "--debug"), model: str | None = typer.Option(None, "--model"), provider: str | None = typer.Option(None, "--provider"), resume: bool | None = typer.Option(None, "--resume/--no-resume", help="Resume the previous session; fresh by default.")) -> None:
    """Run a prompt headlessly with tools allowed."""
    inherited_resume = ctx.parent.obj.get("resume") if ctx.parent and ctx.parent.obj else None
    _run_prompt(prompt, allow_tools=True, debug=debug, model=model, provider=provider, resume=resume if resume is not None else inherited_resume)

@app.command(name="eval")
def eval_command(
    task_id: str | None = typer.Option(None, "--task", help="Run one evaluation task by ID."),
    list_tasks: bool = typer.Option(False, "--list", help="List built-in evaluation tasks."),
    results: Path | None = typer.Option(None, "--results", help="Append JSONL results to this path."),
    model: str | None = typer.Option(None, "--model"),
    provider: str | None = typer.Option(None, "--provider"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
) -> None:
    """Run the isolated Bolt evaluation tasks with the configured provider."""
    from boltpy.evaluation import default_tasks, run_suite, summarize
    tasks = default_tasks()
    if list_tasks:
        for item in tasks:
            typer.echo(f"{item.task_id}\t{item.category}\t{item.prompt}")
        return
    selected = [item for item in tasks if task_id is None or item.task_id == task_id]
    if task_id is not None and not selected:
        typer.echo(f"bolt: unknown evaluation task: {task_id}", err=True)
        raise typer.Exit(code=2)
    settings = load_settings()
    updates = {key: value for key, value in {"model": model, "provider": provider, "base_url": endpoint}.items() if value is not None}
    if updates:
        settings = settings.model_copy(update=updates)
    output_path = results or (Path.cwd() / ".bolt" / "evaluations" / "results.jsonl")

    async def execute() -> list[object]:
        return await run_suite(selected, settings, output_path)

    try:
        evaluated = asyncio.run(execute())
    except Exception as error:
        typer.echo(f"bolt eval: {error}", err=True)
        raise typer.Exit(code=1) from error
    summary = summarize(evaluated)
    typer.echo(f"Tasks: {summary.total_tasks} | verified: {summary.verified} | partial: {summary.partially_verified} | not verified: {summary.not_verified} | blocked: {summary.blocked}")
    typer.echo(f"Average iterations: {summary.average_tool_iterations:.1f} | duration: {summary.average_elapsed_seconds:.2f}s")
    for name, metrics in summary.by_model.items():
        typer.echo(f"{name}: {metrics['tasks']} tasks, {metrics['verified']} verified, {metrics['partially_verified']} partial, {metrics['blocked']} blocked, ground truth {metrics['ground_truth_passed']}")
    typer.echo(f"Results: {output_path}")


@app.command()
def upgrade() -> None:
    """Upgrade Bolt to the latest version from GitHub."""
    installer_url = "https://raw.githubusercontent.com/saurabhahuja71/boltpy/main/install.sh"
    typer.echo("Bolt upgrade: downloading latest installer...", err=True)
    download = None
    try:
        download = subprocess.Popen(
            ["curl", "--fail", "--location", "--progress-bar", installer_url],
            stdout=subprocess.PIPE,
        )
        assert download.stdout is not None
        typer.echo("Bolt upgrade: running installer (live progress follows)...", err=True)
        result = subprocess.run(["bash"], stdin=download.stdout, check=False)
        download.stdout.close()
        download_status = download.wait()
    except Exception as error:
        if download is not None and download.poll() is None:
            download.kill()
        typer.echo(f"bolt: upgrade failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)
    if download_status != 0:
        typer.echo(f"bolt: installer download failed (exit {download_status})", err=True)
        raise typer.Exit(code=download_status)


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
