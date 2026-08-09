"""Interactive Textual application."""
from __future__ import annotations
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Footer, Header, RichLog, Static, TextArea
from boltpy.agent.core import Agent
from boltpy.config import Settings


class PromptTextArea(TextArea):
    """Text area where Enter submits and Shift+Enter inserts a newline."""

    class Submitted(Message):
        """Message emitted when the user submits the prompt."""

        def __init__(self, textarea: "PromptTextArea") -> None:
            super().__init__()
            self.text = textarea.text

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self))
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


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
            yield PromptTextArea(placeholder="Ask Boltpy anything… (Enter to send, Shift+Enter for newline)", id="prompt")
        yield Footer()
    def on_mount(self) -> None:
        self.query_one("#prompt", PromptTextArea).focus()
        self._write("[bold cyan]Boltpy[/bold cyan] — ready. Type /help for commands.")
    def _write(self, text: str) -> None:
        self.query_one("#transcript", RichLog).write(text)
    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"Model: {self.settings.model} | {text}")
    async def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None:
        await self._submit_prompt(event.text)

    async def _submit_prompt(self, value: str) -> None:
        if self.busy or not value.strip():
            return
        prompt = value.strip()
        self.query_one("#prompt", PromptTextArea).text = ""
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
