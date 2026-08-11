"""Polished interactive Textual application and inline permission adapter."""
from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, Label, Markdown, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from boltpy.agent.core import Agent
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionMode, PermissionRequest
from boltpy.agent.todos import todo_store
from boltpy.config import Settings

_TODO_TOOLS = {"add_todo", "complete_todo", "update_todo", "list_todos"}
_TASK_ACTIONS = re.compile(r"\b(check|find|list|tell|show|run|stop|start|create|update|fix|deploy|verify|remove|delete|build|test)\b", re.IGNORECASE)

_HELP_TEXT = (
    "[bold]Commands[/bold]\n"
    "/help  show commands and controls\n"
    "/mode  inspect permission mode\n"
    "/mode ask|allow|plan  change permission mode\n"
    "/theme dark|light  switch theme\n"
    "/model  choose the active configured model\n"
    "/todo  toggle the todo panel\n"
    "/queue  list queued prompts\n"
    "/permissions  list permanent approvals\n"
    "/permissions remove <command>  remove an exact approval\n"
    "/mouse interactive|select  widget mouse (default) or native selection\n"
    "/new  start a new conversation\n"
    "/quit  exit\n\n"
    "[bold]Keys[/bold]\n"
    "Enter send · Shift+Enter newline · Ctrl+Shift+P commands · Ctrl+Shift+M mode · Ctrl+Shift+T todos · Ctrl+Shift+I interactive cursor · Ctrl+Q quit · Ctrl+C cancel\n"
    "Permission: ←/→ or Tab select · Enter/Space confirm · Esc deny\n\n"
    "Type while a task is running to queue it; Ctrl+C cancels the current task."
)


def render_markdown(text: str) -> Markdown:
    """Create a streaming-friendly Textual Markdown widget for assistant content."""
    return Markdown(text)


def _needs_task_todo(prompt: str) -> bool:
    """Return whether a submitted user task needs a visible parent item."""
    # The parent item is a UI task marker, distinct from model-created
    # subtasks. Tracking every submitted task prevents short prompts from
    # silently disappearing from the sidebar.
    return bool(prompt.strip())


class ConversationLog(VerticalScroll):
    """Conversation area that stops auto-scrolling when the user reads older content."""
    def on_scroll(self, event: events.Scroll) -> None:
        self._pinned = self.scroll_y < self.max_scroll_y

    def log(self, widget: Widget) -> object:
        """Mount a widget and scroll to the end unless the user is reading above."""
        result = self.mount(widget)
        self.scroll_to_end()
        return result

    def scroll_to_end(self) -> None:
        if not getattr(self, "_pinned", False):
            self.call_after_refresh(lambda: self.scroll_end(animate=False))


class PromptTextArea(TextArea):
    """Text area where Enter submits and Shift+Enter inserts a newline."""
    class CommandsRequested(Message):
        pass

    class Submitted(Message):
        def __init__(self, textarea: "PromptTextArea") -> None:
            super().__init__(); self.text = textarea.text
    async def _on_key(self, event: events.Key) -> None:
        # Some terminals encode Ctrl+Shift+P as the indistinguishable uppercase
        # ``P`` key instead of the ``ctrl+shift+p`` name used by Textual bindings.
        # Treat it as the command palette only when the prompt is empty; an
        # uppercase P in an active prompt remains ordinary text.
        if event.key == "ctrl+shift+p" and not self.text:
            event.stop(); event.prevent_default(); self.post_message(self.CommandsRequested()); return
        if event.key == "enter":
            event.stop(); event.prevent_default(); self.post_message(self.Submitted(self)); return
        if event.key == "shift+enter":
            event.stop(); event.prevent_default(); self.insert("\n"); return
        await super()._on_key(event)


class CustomAnswerInput(TextArea):
    """One-line input used by the options picker for a typed answer."""
    class Submitted(Message):
        def __init__(self, textarea: "CustomAnswerInput") -> None:
            super().__init__(); self.text = textarea.text
    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop(); event.prevent_default(); self.post_message(self.Submitted(self)); return
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
            yield Label("⚠ Permission", id="permission-title")
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
        labels = ("Once", "Session", "Always", "Deny")
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


class OptionsPrompt(Static):
    """Numbered options picker with keyboard, mouse, and a typed answer."""
    class Decision(Message):
        def __init__(self, prompt: "OptionsPrompt", choice: str | None) -> None:
            super().__init__(); self.prompt = prompt; self.choice = choice

    def __init__(self) -> None:
        super().__init__(id="options-prompt"); self._options: list[str] = []; self._allow_custom = True

    def compose(self) -> ComposeResult:
        with Vertical(id="options-content"):
            yield Label("", id="options-title")
            yield OptionList(id="options-list")
            yield CustomAnswerInput(placeholder="Type your own answer… Enter to submit", id="options-custom")
            yield Label("↑/↓ Select · Enter Confirm · Esc Cancel", id="options-help")

    def present(self, title: str, options: list[str], allow_custom: bool = True) -> None:
        self._options = options; self._allow_custom = allow_custom
        self.query_one("#options-title", Label).update(title or "Choose an option")
        picker = self.query_one("#options-list", OptionList)
        picker.clear_options()
        for index, option in enumerate(options):
            picker.add_option(Option(f"{index + 1}. {option}", id=f"option-{index}"))
        if allow_custom:
            picker.add_option(Option("0. Type your own answer", id="option-custom"))
        picker.highlighted = 0
        self.display = True
        picker.focus()

    def dismiss(self) -> None:
        self.display = False
        custom = self.query_one("#options-custom", CustomAnswerInput)
        custom.styles.display = "none"; custom.text = ""

    def on_key(self, event: events.Key) -> None:
        if not self.display:
            return
        if event.key == "escape":
            event.stop(); self.post_message(self.Decision(self, None))
        elif event.key in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            index = int(event.key) - 1
            if index < len(self._options):
                event.stop(); self.post_message(self.Decision(self, self._options[index]))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id == "option-custom":
            custom = self.query_one("#options-custom", CustomAnswerInput)
            custom.styles.display = "block"
            custom.focus()
            return
        index = int(str(event.option.id).removeprefix("option-"))
        if 0 <= index < len(self._options):
            self.post_message(self.Decision(self, self._options[index]))

    def on_custom_answer_input_submitted(self, event: CustomAnswerInput.Submitted) -> None:
        if self.display:
            self.post_message(self.Decision(self, event.text.strip() or None))


class TodoPanel(Static):
    """Live todo side panel bound to the shared agent todo store."""
    def __init__(self) -> None:
        super().__init__(id="todo-panel", markup=False)

    def refresh_todos(self) -> None:
        todos = todo_store.items()
        open_count = todo_store.open_count()
        text = Text()
        text.append(f"Todos ({open_count} open)\n", style="bold")
        if not todos:
            text.append("(none)")
        for todo in todos:
            mark = "[x]" if todo.completed else "[ ]"
            style = "dim" if todo.completed else ""
            text.append(f"{mark} {todo.id}. {todo.description}\n", style=style)
        self.update(text)


class BoltpyApp(App[None]):
    """Streaming chat application with Markdown, themes, tools, and inline approval."""
    CSS_PATH = "styles.tcss"
    TITLE = "Boltpy"
    BINDINGS = [
        ("ctrl+c", "cancel_operation", "Cancel operation"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+shift+p", "show_commands", "Show commands"),
        ("ctrl+shift+m", "toggle_mode", "Change permission mode"),
        ("ctrl+shift+t", "toggle_todo", "Toggle todos"),
        ("ctrl+shift+i", "toggle_mouse", "Toggle interactive cursor"),
    ]

    def __init__(self, settings: Settings) -> None:
        super().__init__(); self.settings = settings; self.busy = False; self.theme_name = "light"; self.mouse_mode = "interactive"
        self._prompt_queue: list[str] = []
        self._permission_future: asyncio.Future[PermissionDecision] | None = None
        self._options_future: asyncio.Future[str] | None = None
        self._model_prompt: ModelPrompt | None = None
        self._active_worker = None
        self.register_theme(Theme(
            "dark", primary="#58a6ff", secondary="#79c0ff", warning="#d29922", error="#f85149",
            success="#3fb950", accent="#58a6ff", foreground="#e6edf3", background="#101318",
            surface="#0d1117", panel="#161b22"))
        self.register_theme(Theme(
            "light", primary="#0969da", secondary="#1f6feb", warning="#9a6700", error="#cf222e",
            success="#1a7f37", accent="#0969da", foreground="#24292f", background="#ffffff",
            surface="#f6f8fa", panel="#ffffff"))
        self.permissions = PermissionManager(mode=PermissionMode(settings.permission_mode), handler=self._request_permission)
        self.agent = Agent(settings, permissions=self.permissions)
        self.agent.options_handler = self._request_options

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            yield Static(f"CWD: {Path.cwd()}", id="cwd")
            with Horizontal(id="content"):
                yield ConversationLog(id="transcript")
                yield TodoPanel()
            yield PermissionPrompt()
            yield ModelPrompt()
            yield OptionsPrompt()
            yield Static("", id="status")
            yield PromptTextArea(placeholder="Ask Boltpy anything… (Enter to send, Shift+Enter for newline)", id="prompt")
        # Keep the cancel action first and compact so it remains visible in
        # narrow terminals instead of scrolling off the footer.
        yield Footer(show_command_palette=False, compact=True)

    def on_mount(self) -> None:
        self._apply_theme(self.settings.theme if self.settings.theme in {"dark", "light"} else "light")
        # Widget interaction is the default; switch to native terminal selection
        # explicitly when dragging to select/copy text is needed.
        self._set_mouse_mode("interactive")
        self.query_one(TodoPanel).refresh_todos()
        self.query_one("#prompt", PromptTextArea).focus(); self._set_status("Ready")
        self._write("[bold cyan]Boltpy[/bold cyan] — ready. Type /help for commands.", markup=True)

    def _write(self, content: object, markup: bool = False) -> None:
        if isinstance(content, Widget):
            widget = content
        else:
            text = str(content)
            widget = Static(Text.from_markup(text) if markup else Text(text), classes="system-message")
        self.query_one("#transcript", ConversationLog).log(widget)

    def _user_message(self, text: str) -> Static:
        message = Text("You: ", style="bold green")
        message.append(text)
        return Static(message, classes="system-message")

    def _set_status(self, text: str) -> None:
        provider = getattr(getattr(self.agent, "provider", None), "provider_name", "openai")
        tokens = getattr(getattr(self.agent, "provider", None), "total_tokens", 0)
        status = Text()
        status.append(f"Boltpy | Mode: {self.permissions.mode.upper()} | Mouse: {self.mouse_mode.upper()} | Model: {provider}/{self.settings.model} | Tokens: {tokens}")
        if self.busy:
            status.append(" | ", style="dim")
            status.append("Processing…", style="blink bold")
            status.append(f"  {text}", style="dim")
        else:
            status.append(f" | {text}")
        self.query_one("#status", Static).update(status)

    def _set_mouse_mode(self, mode: str) -> None:
        """Toggle terminal mouse reporting for native selection or widget interaction."""
        driver = getattr(self, "_driver", None)
        method = getattr(driver, "_disable_mouse_support" if mode == "select" else "_enable_mouse_support", None)
        if method is not None:
            method()
        self.mouse_mode = mode

    def _apply_theme(self, theme: str) -> None:
        if theme in {"dark", "light"}:
            self.theme = theme
            self.theme_name = theme

    def action_cancel_operation(self) -> None:
        """Cancel the active model or tool worker."""
        if self._active_worker is not None and not self._active_worker.is_finished:
            self._set_status("Cancelling…")
            self._active_worker.cancel()

    def action_show_commands(self) -> None:
        """Show the complete command and keyboard reference."""
        self._write(_HELP_TEXT, markup=True)
        self.query_one("#prompt", PromptTextArea).focus()

    def on_prompt_text_area_commands_requested(self, event: PromptTextArea.CommandsRequested) -> None:
        self.action_show_commands()

    def action_toggle_mouse(self) -> None:
        self._set_mouse_mode("select" if self.mouse_mode == "interactive" else "interactive")
        self._set_status("Ready")

    def action_toggle_todo(self) -> None:
        panel = self.query_one(TodoPanel)
        panel.display = not panel.display
        self._set_status("Ready")

    def action_toggle_mode(self) -> None:
        """Cycle permission mode: ask, allow, plan."""
        modes = (PermissionMode.ASK, PermissionMode.ALLOW, PermissionMode.PLAN)
        current = self.permissions.mode
        self.agent.set_permission_mode(modes[(modes.index(current) + 1) % len(modes)])
        self._set_status(f"Mode: {self.permissions.mode.upper()}")

    async def _request_permission(self, request: PermissionRequest) -> PermissionDecision:
        """Await an inline widget decision without blocking Textual's UI."""
        if self._permission_future is not None and not self._permission_future.done(): return PermissionDecision.DENY
        future: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        self._permission_future = future; prompt = self.query_one(PermissionPrompt); prompt.present(request)
        try: return await future
        finally: prompt.dismiss(); self._permission_future = None

    def on_permission_prompt_decision(self, message: PermissionPrompt.Decision) -> None:
        if self._permission_future is not None and not self._permission_future.done(): self._permission_future.set_result(message.decision)

    async def _request_options(self, title: str, options: list[str], allow_custom: bool) -> str:
        """Show the options picker and await the user's choice."""
        if self._options_future is not None and not self._options_future.done():
            return options[0] if options else "(cancelled)"
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._options_future = future; prompt = self.query_one(OptionsPrompt); prompt.present(title, options, allow_custom)
        try: return await future
        finally: prompt.dismiss(); self._options_future = None

    def on_options_prompt_decision(self, message: OptionsPrompt.Decision) -> None:
        if self._options_future is not None and not self._options_future.done():
            self._options_future.set_result(message.choice if message.choice is not None else "(cancelled)")

    async def _available_models(self) -> list[str]:
        """Return configured models plus locally installed Ollama models.

        Discovery is best-effort and bounded so an unavailable Ollama daemon
        never blocks the TUI or changes headless behavior.
        """
        models = self.settings.available_models()
        try:
            process = await asyncio.create_subprocess_exec(
                "ollama", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=3)
        except (OSError, asyncio.TimeoutError):
            return models
        if process.returncode != 0:
            return models
        for line in stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            name = line.split(None, 1)[0] if line.split() else ""
            if name and name not in models:
                models.append(name)
        return models

    def on_model_prompt_decision(self, message: ModelPrompt.Decision) -> None:
        prompt = self.query_one(ModelPrompt)
        prompt.dismiss()
        if message.model is not None:
            self.settings.model = message.model
            if hasattr(self.agent.provider, "model"):
                self.agent.provider.model = message.model
            self._write(f"Active model: [bold]{message.model}[/bold]", markup=True)
            self._set_status("Ready")
        self.query_one("#prompt", PromptTextArea).focus()

    async def on_prompt_text_area_submitted(self, event: PromptTextArea.Submitted) -> None: await self._submit_prompt(event.text)

    async def _submit_prompt(self, value: str) -> None:
        prompt = value.strip()
        if not prompt: return
        if self.busy:
            if prompt.startswith("/"):
                return
            self._prompt_queue.append(prompt)
            self._write(f"[dim]Queued ({len(self._prompt_queue)} waiting): {prompt[:80]}{'…' if len(prompt) > 80 else ''}[/dim]", markup=True)
            self._set_status(f"Queued ({len(self._prompt_queue)} waiting)")
            return
        self.query_one("#prompt", PromptTextArea).text = ""
        if prompt == "/quit": self.exit()
        elif prompt == "/new": self.agent.reset(); self._write("[dim]Started a new conversation.[/dim]", markup=True)
        elif prompt == "/help":
            self.action_show_commands()
        elif prompt == "/model":
            self.query_one(ModelPrompt).present(await self._available_models(), self.settings.model)
        elif prompt == "/todo":
            self.action_toggle_todo()
        elif prompt == "/queue":
            if not self._prompt_queue:
                self._write("[dim]No prompts queued.[/dim]", markup=True)
            else:
                lines = [f"{index}. {item[:80]}{'…' if len(item) > 80 else ''}" for index, item in enumerate(self._prompt_queue, 1)]
                self._write("[bold]Queued prompts[/bold] (" + str(len(self._prompt_queue)) + " waiting)\n" + "\n".join(lines), markup=True)
        elif prompt == "/permissions":
            entries = self.permissions.permanent_entries()
            self._write("[bold]Permanent permissions[/bold]\n" + ("\n".join(f"✓ {section}: {scope}" for section, scope in entries) if entries else "(none)"), markup=True)
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
            if mode not in {"ask", "allow", "plan"}: self._write("[bold red]Usage:[/bold red] /mode ask|allow|plan", markup=True)
            else: self.agent.set_permission_mode(PermissionMode(mode)); self._set_status("Ready")
        elif prompt == "/theme": self._write(f"Current theme: {self.theme_name}")
        elif prompt == "/mouse": self._write(f"Current mouse mode: {self.mouse_mode} (interactive is the default; use /mouse select for native selection)")
        elif prompt.startswith("/mouse "):
            mouse_mode = prompt.partition(" ")[2].strip().lower()
            if mouse_mode not in {"select", "interactive"}:
                self._write("[bold red]Usage:[/bold red] /mouse select|interactive", markup=True)
            else:
                self._set_mouse_mode(mouse_mode); self._set_status("Ready")

        elif prompt.startswith("/theme "):
            theme = prompt.partition(" ")[2].strip().lower()
            if theme not in {"dark", "light"}: self._write("[bold red]Usage:[/bold red] /theme dark|light", markup=True)
            else: self._apply_theme(theme); self._set_status("Ready")
        else: self._active_worker = self._ask(prompt)

    @work(exclusive=True)
    async def _ask(self, prompt: str) -> None:
        transcript = self.query_one("#transcript", ConversationLog)
        self.busy = True
        try:
            while True:
                try:
                    await self._run_prompt(prompt, transcript)
                except asyncio.CancelledError:
                    self._write("[yellow]Operation cancelled.[/yellow]", markup=True)
                    self._set_status("Cancelled — running next queued prompt…" if self._prompt_queue else "Cancelled — ready")
                if not self._prompt_queue:
                    break
                prompt = self._prompt_queue.pop(0)
                self._set_status("Running next queued prompt…")
        except Exception as error:
            self._write(Static(Text(str(error), style="red"), classes="system-message")); self._set_status("Error — ready")
        finally:
            self.busy = False
            self._active_worker = None
            self.query_one("#prompt", PromptTextArea).focus()

    async def _run_prompt(self, prompt: str, transcript: ConversationLog) -> None:
        self._write(self._user_message(prompt)); answer_parts: list[str] = []
        parent_todo = todo_store.add(f"Task: {prompt[:160]}{'…' if len(prompt) > 160 else ''}")
        self.query_one(TodoPanel).refresh_todos()
        finished = False
        try:
            streaming = Markdown("", classes="assistant-streaming")
            await transcript.log(streaming)
            self._set_status("Thinking…")
            async for event in self.agent.stream_events(prompt):
                if event.kind == "text":
                    answer_parts.append(event.text); await streaming.update("".join(answer_parts)); transcript.scroll_to_end()
                elif event.kind == "tool_call":
                    self._set_status(f"Running {event.name}…")
                elif event.kind == "permission" and event.status == "waiting":
                    self._set_status(f"Waiting for {event.name} approval…")
                elif event.kind == "permission" and event.status != "waiting":
                    self._set_status(f"{event.name}: {event.status}")
                elif event.kind == "tool_result" and event.name in _TODO_TOOLS:
                    self.query_one(TodoPanel).refresh_todos()
            if not answer_parts:
                streaming.remove()
            finished = True
        finally:
            if finished:
                todo_store.complete(parent_todo.id)
            self.query_one(TodoPanel).refresh_todos()
        self._set_status("Ready")

    async def on_unmount(self) -> None: await self.agent.close()
