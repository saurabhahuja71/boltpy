"""Interactive Textual application and inline permission adapter."""
from __future__ import annotations
import asyncio
import json
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Footer, Header, Label, RichLog, Static, TextArea
from boltpy.agent.core import Agent
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionMode, PermissionRequest
from boltpy.config import Settings

class PromptTextArea(TextArea):
    """Text area where Enter submits and Shift+Enter inserts a newline."""
    class Submitted(Message):
        def __init__(self, textarea: "PromptTextArea") -> None:
            super().__init__(); self.text = textarea.text
    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop(); event.prevent_default(); self.post_message(self.Submitted(self)); return
        if event.key == "shift+enter":
            event.stop(); event.prevent_default(); self.insert("\n"); return
        await super()._on_key(event)

class PermissionPrompt(Static):
    """Compact inline approval prompt that never leaves the conversation view."""
    class Decision(Message):
        def __init__(self, prompt: "PermissionPrompt", decision: PermissionDecision) -> None:
            super().__init__(); self.prompt = prompt; self.decision = decision
    def __init__(self) -> None:
        super().__init__(id="permission-prompt")
        self._request: PermissionRequest | None = None
        self._selected = 0
    def compose(self) -> ComposeResult:
        with Vertical(id="permission-content"):
            yield Label("⚠ Permission required", id="permission-title")
            yield Label("", id="permission-tool")
            yield Static("", id="permission-details", markup=False)
            with Horizontal(id="permission-buttons"):
                yield Button("", id="allow-once", variant="success")
                yield Button("", id="allow-session", variant="primary")
                yield Button("", id="deny", variant="error")
            yield Label("← → Select   Enter / Space Confirm   Esc Deny", id="permission-help")
    def _buttons(self) -> list[Button]:
        return [self.query_one(selector, Button) for selector in ("#allow-once", "#allow-session", "#deny")]
    def _select(self, index: int) -> None:
        self._selected = index % 3
        labels = ("Allow Once", "Allow Session", "Deny")
        for position, button in enumerate(self._buttons()):
            button.label = ("▶ " if position == self._selected else "") + labels[position]
        self._buttons()[self._selected].focus()
    def present(self, request: PermissionRequest) -> None:
        """Display a request and focus Allow Once."""
        self._request = request
        self.query_one("#permission-tool", Label).update(f"Tool: {request.tool_name}")
        if request.tool_name == "run_shell":
            argument = str(request.arguments.get("command", ""))
        elif len(request.arguments) == 1:
            argument = str(next(iter(request.arguments.values())))
        else:
            argument = json.dumps(request.arguments, ensure_ascii=False, separators=(", ", ": "))
        if len(argument) > 360: argument = argument[:357] + "…"
        self.query_one("#permission-details", Static).update(f"$ {argument}")
        self.display = True
        self._select(0)
    def dismiss(self) -> None:
        self._request = None
        self.display = False
    def _emit_decision(self, decision: PermissionDecision) -> None:
        if self._request is not None: self.post_message(self.Decision(self, decision))
    def on_key(self, event: events.Key) -> None:
        if self._request is None: return
        if event.key in {"left", "shift+tab"}:
            event.stop(); self._select(self._selected - 1)
        elif event.key in {"right", "tab"}:
            event.stop(); self._select(self._selected + 1)
        elif event.key == "escape":
            event.stop(); self._emit_decision(PermissionDecision.DENY)
        elif event.key in {"enter", "space"}:
            event.stop(); self._emit_decision((PermissionDecision.ALLOW_ONCE, PermissionDecision.ALLOW_SESSION, PermissionDecision.DENY)[self._selected])
    def on_button_pressed(self, event: Button.Pressed) -> None:
        decisions = {"allow-once": PermissionDecision.ALLOW_ONCE, "allow-session": PermissionDecision.ALLOW_SESSION, "deny": PermissionDecision.DENY}
        if event.button.id in decisions: self._emit_decision(decisions[event.button.id])

class BoltpyApp(App[None]):
    """Streaming chat application with asynchronous inline tool approval."""
    CSS_PATH = "styles.tcss"
    TITLE = "Boltpy"
    BINDINGS = [("ctrl+c", "quit", "Quit")]
    def __init__(self, settings: Settings) -> None:
        super().__init__(); self.settings = settings; self.busy = False; self._permission_future: asyncio.Future[PermissionDecision] | None = None
        self.permissions = PermissionManager(mode=PermissionMode(settings.permission_mode), handler=self._request_permission)
        self.agent = Agent(settings, permissions=self.permissions)
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield RichLog(id="transcript", wrap=True, markup=True, highlight=True)
            yield Static("", id="streaming", markup=False)
            yield PermissionPrompt()
            yield Static("", id="status")
            yield PromptTextArea(placeholder="Ask Boltpy anything… (Enter to send, Shift+Enter for newline)", id="prompt")
        yield Footer()
    def on_mount(self) -> None:
        self.query_one("#prompt", PromptTextArea).focus(); self._set_status("Ready")
        self._write("[bold cyan]Boltpy[/bold cyan] — ready. Type /help for commands.")
    def _write(self, text: str) -> None: self.query_one("#transcript", RichLog).write(text)
    def _set_status(self, text: str) -> None: self.query_one("#status", Static).update(f"Boltpy | Mode: {self.permissions.mode.upper()} | Model: {self.settings.model} | {text}")
    async def _request_permission(self, request: PermissionRequest) -> PermissionDecision:
        """Await an inline widget decision without blocking Textual's UI."""
        if self._permission_future is not None and not self._permission_future.done():
            return PermissionDecision.DENY
        future: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        self._permission_future = future
        prompt = self.query_one(PermissionPrompt)
        prompt.present(request)
        try: return await future
        finally:
            prompt.dismiss()
            self._permission_future = None
    def on_permission_prompt_decision(self, message: PermissionPrompt.Decision) -> None:
        if self._permission_future is not None and not self._permission_future.done(): self._permission_future.set_result(message.decision)
    async def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None: await self._submit_prompt(event.text)
    async def _submit_prompt(self, value: str) -> None:
        if self.busy or not value.strip(): return
        prompt = value.strip(); self.query_one("#prompt", PromptTextArea).text = ""
        if prompt == "/quit": self.exit()
        elif prompt == "/new": self.agent.reset(); self._write("[dim]Started a new conversation.[/dim]")
        elif prompt == "/help": self._write("[bold]Commands:[/bold] /new, /mode, /mode ask|allow, /help, /quit")
        elif prompt == "/mode": self._write(f"Current permission mode: {self.permissions.mode.value}")
        elif prompt.startswith("/mode "):
            mode = prompt.partition(" ")[2].strip()
            if mode not in {"ask", "allow"}: self._write("[bold red]Usage:[/bold red] /mode ask|allow")
            else: self.settings.permission_mode = mode; self.permissions.mode = PermissionMode(mode); self._set_status("Ready")
        else: self._ask(prompt)
    @work(exclusive=True)
    async def _ask(self, prompt: str) -> None:
        transcript = self.query_one("#transcript", RichLog); streaming = self.query_one("#streaming", Static)
        self.busy = True; self._write(f"[bold green]You:[/bold green] {prompt}"); answer_parts: list[str] = []
        streaming.update("Boltpy: "); self._set_status("Thinking…")
        try:
            async for event in self.agent.stream_events(prompt):
                if event.kind == "text": answer_parts.append(event.text); streaming.update(f"Boltpy: {''.join(answer_parts)}")
                elif event.kind == "tool_call": self._write(f"[bold cyan]┌─ Tool: {event.name} ─[/bold cyan]\n  {json.dumps(event.arguments or {}, ensure_ascii=False)}\n  status: requested")
                elif event.kind == "permission" and event.status == "waiting": self._write(f"[yellow]  Waiting for permission: {event.name}[/yellow]"); self._set_status(f"Waiting for {event.name} approval…")
                elif event.kind == "permission" and event.status != "waiting": self._write("  status: " + ("approved" if event.status in {"allow_once", "allow_session"} else "denied"))
                elif event.kind == "tool_result":
                    result = event.result; summary = (result.output if result and result.ok else result.error if result else "unknown error")
                    if len(summary) > 1000: summary = summary[:1000] + "… (truncated)"
                    self._write(f"[dim]  {'✓ completed' if result and result.ok else '✗ failed'}[/dim]\n  {summary}\n[cyan]└────────────────────────[/cyan]")
            transcript.write(f"[bold magenta]Boltpy:[/bold magenta] {''.join(answer_parts)}"); streaming.update(""); self._set_status("Ready")
        except Exception as error:
            streaming.update(""); self._write(f"[bold red]Error:[/bold red] {error}"); self._set_status("Error — ready")
        finally: self.busy = False
    async def on_unmount(self) -> None: await self.agent.close()
