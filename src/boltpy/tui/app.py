"""Polished interactive Textual application and inline permission adapter."""
from __future__ import annotations
import asyncio
import json
import time
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Footer, Header, Label, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option
from boltpy.agent.core import Agent
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionMode, PermissionRequest
from boltpy.config import Settings


def render_markdown(text: str) -> Markdown:
    """Render assistant content with Rich Markdown and fenced-code highlighting."""
    return Markdown(text, code_theme="monokai", hyperlinks=True)


class ConversationLog(RichLog):
    """Conversation log that stops forcing scroll when the user reads older content."""
    def on_scroll(self, event: object) -> None:
        self.auto_scroll = self.scroll_y >= self.max_scroll_y


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
                yield Button("", id="allow-permanent", variant="warning")
                yield Button("", id="deny", variant="error")
            yield Label("← → Select   Enter / Space Confirm   Esc Deny", id="permission-help")
    def _buttons(self) -> list[Button]:
        return [self.query_one(selector, Button) for selector in ("#allow-once", "#allow-session", "#allow-permanent", "#deny")]
    def _select(self, index: int) -> None:
        self._selected = index % 4
        labels = ("Allow Once", "Allow Session", "Allow Permanently", "Deny")
        for position, button in enumerate(self._buttons()):
            button.label = ("▶ " if position == self._selected else "") + labels[position]
        self._buttons()[self._selected].focus()
    def present(self, request: PermissionRequest) -> None:
        """Display a request and focus Allow Once."""
        self._request = request
        self.query_one("#permission-tool", Label).update(f"Tool: {request.tool_name}")
        if request.tool_name == "run_shell": argument = "$ " + str(request.arguments.get("command", ""))
        elif request.tool_name == "ssh": argument = f"Host: {request.arguments.get('user', '') + '@' if request.arguments.get('user') else ''}{request.arguments.get('host', '')}\nCommand: {request.arguments.get('command', '')}"
        elif len(request.arguments) == 1: argument = str(next(iter(request.arguments.values())))
        else: argument = json.dumps(request.arguments, ensure_ascii=False, separators=(", ", ": "))
        if len(argument) > 360: argument = argument[:357] + "…"
        self.query_one("#permission-details", Static).update(argument)
        self.display = True; self._select(0)
    def dismiss(self) -> None:
        self._request = None; self.display = False
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
            event.stop(); self._emit_decision((PermissionDecision.ALLOW_ONCE, PermissionDecision.ALLOW_SESSION, PermissionDecision.ALLOW_PERMANENT, PermissionDecision.DENY)[self._selected])
    def on_button_pressed(self, event: Button.Pressed) -> None:
        decisions = {"allow-once": PermissionDecision.ALLOW_ONCE, "allow-session": PermissionDecision.ALLOW_SESSION, "allow-permanent": PermissionDecision.ALLOW_PERMANENT, "deny": PermissionDecision.DENY}
        if event.button.id in decisions: self._emit_decision(decisions[event.button.id])


class ModelPrompt(Static):
    """Compact inline model selector using Textual's keyboard/mouse OptionList."""
    class Decision(Message):
        def __init__(self, prompt: "ModelPrompt", model: str | None) -> None:
            super().__init__(); self.prompt = prompt; self.model = model

    def __init__(self) -> None:
        super().__init__(id="model-prompt"); self._models: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="model-content"):
            yield Label("Select model", id="model-title")
            yield OptionList(id="model-options")
            yield Label("↑/↓ Select   Enter Confirm   Esc Cancel", id="model-help")

    def present(self, models: list[str], current: str) -> None:
        self._models = models
        options = self.query_one("#model-options", OptionList)
        options.clear_options()
        for model in models:
            options.add_option(Option(("✓ " if model == current else "  ") + model, id=model))
        options.highlighted = models.index(current) if current in models else 0
        self.display = True
        options.focus()

    def dismiss(self) -> None:
        self.display = False

    def on_key(self, event: events.Key) -> None:
        if self.display and event.key == "escape":
            event.stop(); self.post_message(self.Decision(self, None))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is not None:
            self.post_message(self.Decision(self, str(event.option.id)))


class BoltpyApp(App[None]):
    """Streaming chat application with Markdown, themes, and inline approval."""
    CSS_PATH = "styles.tcss"
    TITLE = "Boltpy"
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+c", "cancel_operation", "Cancel operation"), ("ctrl+shift+m", "toggle_mouse", "Toggle mouse mode")]
    def __init__(self, settings: Settings) -> None:
        super().__init__(); self.settings = settings; self.busy = False; self.theme_name = "dark"; self.mouse_mode = "interactive"
        self._permission_future: asyncio.Future[PermissionDecision] | None = None
        self._model_prompt: ModelPrompt | None = None
        self._tool_started: dict[str, float] = {}
        self._tool_arguments: dict[str, dict[str, object]] = {}
        self._active_worker = None
        self.permissions = PermissionManager(mode=PermissionMode(settings.permission_mode), handler=self._request_permission)
        self.agent = Agent(settings, permissions=self.permissions)
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield ConversationLog(id="transcript", wrap=True, markup=True, highlight=True, auto_scroll=True)
            yield Static("", id="streaming", markup=False)
            yield PermissionPrompt()
            yield ModelPrompt()
            yield Static("", id="status")
            yield PromptTextArea(placeholder="Ask Boltpy anything… (Enter to send, Shift+Enter for newline)", id="prompt")
        yield Footer()
    def on_mount(self) -> None:
        self._apply_theme("dark")
        self.query_one("#prompt", PromptTextArea).focus(); self._set_status("Ready")
        self._write("[bold cyan]Boltpy[/bold cyan] — ready. Type /help for commands.")
    def _write(self, content: object) -> None:
        self.query_one("#transcript", ConversationLog).write(content)
    def _set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(f"Boltpy | Mode: {self.permissions.mode.upper()} | Model: {self.settings.model} | Mouse: {self.mouse_mode} | {text}")
    def _set_mouse_mode(self, mode: str) -> None:
        """Toggle terminal mouse reporting for native selection or widget interaction."""
        driver = getattr(self, "_driver", None)
        method = getattr(driver, "_disable_mouse_support" if mode == "select" else "_enable_mouse_support", None)
        if method is not None:
            method()
        self.mouse_mode = mode

    def action_cancel_operation(self) -> None:
        """Cancel the active model or tool worker."""
        if self._active_worker is not None and not self._active_worker.finished:
            self._set_status("Cancelling…")
            self._active_worker.cancel()

    def action_toggle_mouse(self) -> None:
        self._set_mouse_mode("select" if self.mouse_mode == "interactive" else "interactive")
        self._set_status("Ready")

    def _apply_theme(self, theme: str) -> None:
        self.screen.remove_class("light")
        if theme == "light": self.screen.add_class("light")
        self.theme_name = theme
    def _tool_text(self, name: str, arguments: dict[str, object]) -> str:
        if name == "run_shell": return f"$ {arguments.get('command', '')}"
        if name == "ssh": return f"{arguments.get('user', '') + '@' if arguments.get('user') else ''}{arguments.get('host', '')}: {arguments.get('command', '')}"
        return json.dumps(arguments, ensure_ascii=False, separators=(", ", ": "))
    def _write_tool_card(self, name: str, arguments: dict[str, object], status: str, result: str = "") -> None:
        elapsed = time.perf_counter() - self._tool_started.get(name, time.perf_counter())
        body = Text(self._tool_text(name, arguments) + "\n", style="bold")
        body.append(f"{status} · {elapsed:.2f}s", style="green" if status in {"✓ completed", "approved"} else "yellow" if "waiting" in status or status == "requested" else "red")
        if result:
            summary = result if len(result) <= 700 else result[:697] + "…"
            body.append("\n" + summary)
        self._write(Panel(body, title=f"Tool: {name}", border_style="cyan", padding=(0, 1)))
    async def _request_permission(self, request: PermissionRequest) -> PermissionDecision:
        """Await an inline widget decision without blocking Textual's UI."""
        if self._permission_future is not None and not self._permission_future.done(): return PermissionDecision.DENY
        future: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        self._permission_future = future; prompt = self.query_one(PermissionPrompt); prompt.present(request)
        try: return await future
        finally: prompt.dismiss(); self._permission_future = None
    def on_permission_prompt_decision(self, message: PermissionPrompt.Decision) -> None:
        if self._permission_future is not None and not self._permission_future.done(): self._permission_future.set_result(message.decision)
    def on_model_prompt_decision(self, message: ModelPrompt.Decision) -> None:
        prompt = self.query_one(ModelPrompt)
        prompt.dismiss()
        if message.model is not None:
            self.settings.model = message.model
            if hasattr(self.agent.provider, "model"):
                self.agent.provider.model = message.model
            self._write(f"Active model: [bold]{message.model}[/bold]")
            self._set_status("Ready")
        self.query_one("#prompt", PromptTextArea).focus()

    async def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None: await self._submit_prompt(event.text)
    async def _submit_prompt(self, value: str) -> None:
        if self.busy or not value.strip(): return
        prompt = value.strip(); self.query_one("#prompt", PromptTextArea).text = ""
        if prompt == "/quit": self.exit()
        elif prompt == "/new": self.agent.reset(); self._write("[dim]Started a new conversation.[/dim]")
        elif prompt == "/help":
            self._write("[bold]Commands[/bold]\n/help  show commands and controls\n/mode  inspect permission mode\n/mode ask|allow  change permission mode\n/theme dark|light  switch theme\n/model  choose the active configured model\n/permissions  list permanent approvals\n/permissions remove <command>  remove an exact approval\n/mouse select|interactive  native selection or widget mouse\n/new  start a new conversation\n/quit  exit\n\n[bold]Keys[/bold]\nEnter send · Shift+Enter newline · Ctrl+Q quit\nPermission: ←/→ or Tab select · Enter/Space confirm · Esc deny")
        elif prompt == "/model":
            self.query_one(ModelPrompt).present(self.settings.available_models(), self.settings.model)
        elif prompt == "/permissions":
            entries = self.permissions.permanent_entries()
            self._write("[bold]Permanent permissions[/bold]\n" + ("\n".join(f"✓ {section}: {scope}" for section, scope in entries) if entries else "(none)"))
        elif prompt.startswith("/permissions remove "):
            target = prompt.partition(" ")[2].partition(" ")[2].strip().strip("\"")
            removed = False
            for section, scope in self.permissions.permanent_entries():
                if target == scope or target == scope.split("|")[-1]:
                    removed = self.permissions.remove_permanent(section, scope) or removed
            self._write("Removed permanent permission." if removed else "No matching permanent permission found.")
        elif prompt == "/mode": self._write(f"Current permission mode: {self.permissions.mode.value}")
        elif prompt.startswith("/mode "):
            mode = prompt.partition(" ")[2].strip()
            if mode not in {"ask", "allow"}: self._write("[bold red]Usage:[/bold red] /mode ask|allow")
            else: self.settings.permission_mode = mode; self.permissions.mode = PermissionMode(mode); self._set_status("Ready")
        elif prompt == "/theme": self._write(f"Current theme: {self.theme_name}")
        elif prompt == "/mouse": self._write(f"Current mouse mode: {self.mouse_mode} (use /mouse select or /mouse interactive)")
        elif prompt.startswith("/mouse "):
            mouse_mode = prompt.partition(" ")[2].strip().lower()
            if mouse_mode not in {"select", "interactive"}:
                self._write("[bold red]Usage:[/bold red] /mouse select|interactive")
            else:
                self._set_mouse_mode(mouse_mode); self._set_status("Ready")

        elif prompt.startswith("/theme "):
            theme = prompt.partition(" ")[2].strip().lower()
            if theme not in {"dark", "light"}: self._write("[bold red]Usage:[/bold red] /theme dark|light")
            else: self._apply_theme(theme); self._set_status("Ready")
        else: self._active_worker = self._ask(prompt)
    @work(exclusive=True)
    async def _ask(self, prompt: str) -> None:
        transcript = self.query_one("#transcript", ConversationLog); streaming = self.query_one("#streaming", Static)
        self.busy = True; self._write(f"[bold green]You:[/bold green] {prompt}"); answer_parts: list[str] = []
        streaming.update("Boltpy: "); self._set_status("Thinking…")
        try:
            async for event in self.agent.stream_events(prompt):
                if event.kind == "text":
                    answer_parts.append(event.text); streaming.update(render_markdown("".join(answer_parts)))
                elif event.kind == "tool_call":
                    self._tool_started[event.name] = time.perf_counter(); self._tool_arguments[event.name] = event.arguments or {}; self._write_tool_card(event.name, event.arguments or {}, "requested")
                elif event.kind == "permission" and event.status == "waiting":
                    self._write_tool_card(event.name, event.arguments or {}, "waiting for permission"); self._set_status(f"Waiting for {event.name} approval…")
                elif event.kind == "permission" and event.status != "waiting":
                    self._write_tool_card(event.name, event.arguments or {}, "approved" if event.status in {"allow_once", "allow_session", "allow_permanent"} else "denied")
                elif event.kind == "tool_result":
                    result = event.result; summary = result.display() if result else "unknown error"
                    self._write_tool_card(event.name, self._tool_arguments.get(event.name, {}), "✓ completed" if result and result.ok else "✗ failed", summary)
            if answer_parts: transcript.write(Panel(render_markdown("".join(answer_parts)), title="Boltpy", border_style="magenta", padding=(0, 1)))
            streaming.update(""); self._set_status("Ready")
        except asyncio.CancelledError:
            streaming.update(""); self._write("[yellow]Operation cancelled.[/yellow]"); self._set_status("Cancelled — ready")
        except Exception as error:
            streaming.update(""); self._write(Panel(Text(str(error), style="red"), title="✗ Model error", border_style="red")); self._set_status("Error — ready")
        finally:
            self.busy = False
            self._active_worker = None
    async def on_unmount(self) -> None: await self.agent.close()
