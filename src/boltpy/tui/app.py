"""Interactive Textual application."""
from __future__ import annotations
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, RichLog, Static, TextArea
from boltpy.agent.core import Agent
from boltpy.config import Settings

class BoltpyApp(App[None]):
    """Dark, keyboard-friendly streaming chat application."""
    CSS_PATH = "styles.tcss"
    TITLE = "Boltpy"
    BINDINGS = [("ctrl+c", "quit", "Quit")]
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.agent = Agent(settings)
        self.busy = False
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield RichLog(id="transcript", wrap=True, markup=True, highlight=True)
            yield Static(f"Model: {self.settings.model} | Ready", id="status")
            yield TextArea(placeholder="Ask Boltpy anything… (Ctrl+Enter to send)", id="prompt")
        yield Footer()
    def on_mount(self) -> None:
        self.query_one("#prompt", TextArea).focus()
        self._write("[bold cyan]Boltpy[/bold cyan] — ready. Type /help for commands.")
    def _write(self, text: str) -> None:
        self.query_one("#transcript", RichLog).write(text)
    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"Model: {self.settings.model} | {text}")
    async def on_key(self, event: events.Key) -> None:
        if event.key == "ctrl+enter" and isinstance(self.focused, TextArea):
            event.stop()
            await self._submit_prompt(self.focused.text)

    async def _submit_prompt(self, value: str) -> None:
        if self.busy or not value.strip():
            return
        prompt = value.strip()
        self.query_one("#prompt", TextArea).text = ""
        if prompt == "/quit":
            self.exit()
        elif prompt == "/new":
            self.agent.reset()
            self._write("[dim]Started a new conversation.[/dim]")
        elif prompt == "/help":
            self._write("[bold]Commands:[/bold] /new clears history, /help shows this, /quit exits.")
        else:
            await self._ask(prompt)
    async def _ask(self, prompt: str) -> None:
        transcript = self.query_one("#transcript", RichLog)
        self.busy = True
        self._write(f"[bold green]You:[/bold green] {prompt}")
        transcript.write("[bold magenta]Boltpy:[/bold magenta] ", end="")
        self._set_status("Thinking…")
        try:
            async for token in self.agent.stream(prompt):
                transcript.write(token, end="")
            transcript.write("")
            self._set_status("Ready")
        except Exception as error:
            self._write(f"[bold red]Error:[/bold red] {error}")
            self._set_status("Error — ready")
        finally:
            self.busy = False
    async def on_unmount(self) -> None:
        await self.agent.close()
