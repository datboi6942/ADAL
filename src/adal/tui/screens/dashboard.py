import asyncio
import time

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, RichLog, Static

from adal.config import settings
from adal.tui.screens.full_report import FullReportScreen
from adal.tui.widgets.chat_history import ChatHistory, IterationCard
from adal.tui.widgets.commands import COMMAND_REGISTRY
from adal.tui.widgets.debug_panel import (
    VERBOSITY_HIGH,
    VERBOSITY_LOW,
    VERBOSITY_MED,
    DebugLine,
    DebugPanel,
)
from adal.tui.widgets.query_input import CommandInput, CommandSubmit, QuerySubmit
from adal.tui.widgets.status_animatable import StatusAnimatableMixin
from adal.tui.widgets.suggestion_list import SuggestionList
from adal.tui.worker import OrcWorker, ReasoningUpdate, ResultReady, StatusUpdate, ToolCallUpdate


class DashboardScreen(Screen, StatusAnimatableMixin):
    COMPONENT_CLASSES = {"input"}

    BINDINGS = [
        Binding("ctrl+c", "copy_all", "Copy All", priority=True),
        Binding("f6", "debug_cycle", "Debug", priority=True),
        Binding("f7", "copy_debug", "Copy Debug", priority=True),
        Binding("f8", "debug_tier", "Debug Tier", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self._worker: OrcWorker | None = None
        self._last_result: dict | None = None
        self._query_running = False
        self._start_time: float = 0
        self._cards: dict[str, list] = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent: str | None = None
        self._continuation_context: str | None = None
        self._max_iters = 10
        self._status_timer = None
        self._ticking = False
        self._iter = 0
        self._tick_count = 0
        self._verbose = False
        self._debug = False

    def compose(self):
        yield ChatHistory(id="chat-history")
        with Vertical(id="query-area"):
            yield CommandInput(id="query-input")
            yield SuggestionList(id="suggestion-list")
        with Horizontal(id="status-line"):
            yield Static(" ", id="status-text")
            yield Button("Verbose OFF", id="verbose-btn", classes="status-btn")
            yield Button("\u2699", id="settings-btn", classes="status-btn")
        yield DebugPanel(classes="debug-panel")
        yield Footer()

    def on_mount(self):
        self.query_one("#query-input", CommandInput).focus()
        self._set_status_state("idle")
        self._update_status("Ready — type a research question and press Enter  (Shift+Enter for newline, / for commands)")

    def _set_status_state(self, state: str):
        line = self.query_one("#status-line")
        line.remove_class("idle", "running", "done", "error-state")
        line.add_class(state)

    _status_label_fallback = "Initializing"

    def _on_status_animation_started(self):
        self._set_status_state("running")

    def on_query_submit(self, event: QuerySubmit):
        query = event.query
        if not query or self._query_running:
            return

        self._query_running = True
        self._start_time = time.time()
        self._iter = 0
        self._cards = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent = None

        history = self.query_one(ChatHistory)
        history.add_markdown(f"## Query\n{query}")
        qi = self.query_one("#query-input", CommandInput)
        qi.clear_query()
        qi.read_only = True
        self._start_status_animation()
        self._status_tick()

        asyncio.create_task(self._run_query(query))

    def on_command_submit(self, event: CommandSubmit):
        if self._query_running:
            return
        self._dispatch_command(event.command)
        qi = self.query_one("#query-input", CommandInput)
        qi.clear_query()

    async def _run_query(self, query: str):
        try:
            self._worker = OrcWorker(self.app)
            self._worker._debug = self._debug
            if self._continuation_context:
                enriched = self._build_continuation_query(query)
                self._continuation_context = None
                await self._worker.run_query(enriched)
            else:
                await self._worker.run_query(query)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            try:
                self.query_one(ChatHistory).add_result(f"[red]Error: {e}[/red]")
                self._on_query_end()
            except Exception:
                pass

    def _build_continuation_query(self, new_query: str) -> str:
        prev = self._last_result or {}
        parts = ["[CONTINUATION — building on prior session]"]

        original_query = prev.get("query", "")
        if original_query:
            parts.append(f"Original question: {original_query}")

        status = prev.get("status", "")
        iterations = prev.get("iterations", 0)
        validated = prev.get("validated_count", 0)
        failed = prev.get("failed_count", 0)
        parts.append(f"Session status: {status.upper()} | {iterations} iterations | {validated} validated | {failed} failed")

        domain = prev.get("domain", "")
        if domain:
            parts.append(f"Domain: {domain.upper()}")

        fa = prev.get("final_answer", "")
        if fa:
            if isinstance(fa, dict):
                fa_summary = str(fa)[:800]
            else:
                fa_summary = str(fa)[:800]
            if fa_summary.strip():
                parts.append(f"Previous result: {fa_summary}")

        parts.append(f"\nNow answer this follow-up, building on those findings:\n{new_query}")
        return "\n\n".join(parts)

    def _on_query_end(self):
        self._query_running = False
        self._stop_status_animation()
        qi = self.query_one("#query-input", CommandInput)
        qi.read_only = False
        qi.focus()

    def on_status_update(self, event: StatusUpdate):
        agent = event.name.lower()
        chat = self.query_one(ChatHistory)

        if agent == "proposer" and event.status == "thinking":
            self._iter += 1

        if event.status == "thinking":
            card = chat.add_card(agent, self._iter, "", "Thinking \u2026")
            if self._verbose:
                card.set_verbose(True)
                card.toggle()
            self._cards[agent].append(card)
            self._current_agent = agent
        elif event.status == "done":
            cards = self._cards.get(agent, [])
            if cards:
                cards[-1].set_status("", event.detail or "")
                if agent == "verifier":
                    detail_lower = (event.detail or "").lower()
                    if "pass" in detail_lower and "fail" not in detail_lower:
                        cards[-1].celebrate()
        elif event.status == "error":
            cards = self._cards.get(agent, [])
            if cards:
                cards[-1].set_status("[red]Failed[/red]", event.detail or "")
                cards[-1].shake()

    def on_reasoning_update(self, event: ReasoningUpdate):
        agent = event.name.lower()
        cards = self._cards.get(agent, [])
        if cards:
            cards[-1].set_reasoning_preview(event.text)
            if not cards[-1]._collapsed:
                if self._verbose:
                    cards[-1]._detail = (cards[-1]._detail or "") + "\n" + event.text[:500]
                cards[-1]._write()

    def on_tool_call_update(self, event: ToolCallUpdate):
        agent = event.agent.lower()
        cards = self._cards.get(agent, [])
        if cards:
            cards[-1].add_tool_call(event.tool_name, f"{event.args_preview} → {event.result_preview}")

    def on_debug_line(self, event: DebugLine):
        if self._debug:
            self.query_one(DebugPanel).write(
                event.category, event.event, event.detail,
                verbosity=event.verbosity,
            )

    def on_result_ready(self, event: ResultReady):
        self._query_running = False
        self._stop_status_animation()
        qi = self.query_one("#query-input", CommandInput)
        qi.read_only = False
        qi.focus()

        result = event.result
        self._last_result = result
        self._continuation_context = result.get("session_id", "")
        elapsed = time.time() - self._start_time

        status = result.get("status", "unknown")
        iterations = result.get("iterations", 0)
        validated = result.get("validated_count", 0)
        cost = result.get("cost", {}).get("total_cost", 0)

        if status == "converged" or (validated > 0):
            self._set_status_state("done")
        elif status == "failed":
            self._set_status_state("error-state")
        else:
            self._set_status_state("idle")

        self._update_status(
            f"\u2713 {status.upper()} | {iterations} iter | "
            f"{validated} validated | {int(elapsed//60)}m{int(elapsed%60):02d}s | ${cost:.5f}"
        )

        history = self.query_one(ChatHistory)
        if status == "failed":
            fa = result.get("final_answer", "")
            history.add_result(f"[red]## Failed[/red]\n{str(fa)[:1000]}")
            return

        fa = result.get("final_answer", "")
        if isinstance(fa, str) and fa.strip():
            history.add_markdown(f"## Final Answer\n{fa}")
        elif isinstance(fa, dict):
            for k, v in fa.items():
                title = k.replace("_", " ").title()
                history.add_markdown(f"### {title}\n{str(v)}")

        actions = VerticalScroll(classes="result-actions")
        history.mount(actions)
        actions.mount(Button("\U0001f504 Continue Research", id="continue-research", variant="primary"))
        actions.mount(Button("View Full Report \u2192", id="view-full-result"))
        actions.mount(Button("Export Markdown \u2193", id="export-result"))

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "continue-research" and self._last_result:
            qi = self.query_one("#query-input", CommandInput)
            qi.clear()
            qi.focus()
            self._continuation_context = self._last_result.get("session_id", "")
        elif bid == "view-full-result" and self._last_result:
            self.app.push_screen(FullReportScreen(self._last_result))
        elif bid == "export-result" and self._last_result:
            self._export()
        elif bid == "settings-btn":
            from adal.tui.screens.settings.hub import SettingsHubScreen
            self.app.push_screen(SettingsHubScreen())
        elif bid == "verbose-btn":
            self._toggle_verbose()

    def _toggle_verbose(self):
        self._verbose = not self._verbose
        btn = self.query_one("#verbose-btn", Button)
        if self._verbose:
            btn.label = "Verbose ON"
            btn.add_class("active")
        else:
            btn.label = "Verbose OFF"
            btn.remove_class("active")

        for agent_cards in self._cards.values():
            for card in agent_cards:
                if isinstance(card, IterationCard):
                    card.set_verbose(self._verbose)
                    if not self._verbose:
                        card._collapsed = True
                        card._write()

    def _export(self):
        asyncio.create_task(self._do_export())

    async def _do_export(self):
        try:
            result = self._last_result
            if not result:
                return
            fa = result.get("final_answer", "")
            text = f"# ADAL Research Result\n\n**Query:** {result.get('query', '')}\n"
            text += f"**Status:** {result.get('status', 'unknown')}\n\n"
            if isinstance(fa, str):
                text += fa
            elif isinstance(fa, dict):
                for k, v in fa.items():
                    text += f"## {k.replace('_', ' ').title()}\n{str(v)}\n\n"

            from pathlib import Path

            from adal.tui.utils import generate_export_filename

            content_preview = fa if isinstance(fa, str) else str(fa)
            filename = await generate_export_filename(
                result.get("query", ""), content_preview
            )
            path = Path(f"{filename}.md")
            path.write_text(text)
            self.notify(f"Exported to {path}", title="Export")
        except Exception as e:
            self.notify(str(e), title="Export Failed", severity="error")

    def action_copy_debug(self):
        import pyperclip
        try:
            log = self.query_one("#debug-log", RichLog)
            lines = [str(line.text) for line in log.lines if str(line.text).strip()]
        except Exception:
            self.notify("Debug log not available", title="Copy Debug", severity="warning")
            return
        if not lines:
            self.notify("Debug log is empty", title="Copy Debug", severity="warning")
            return
        pyperclip.copy("\n".join(lines))
        self.notify(f"Copied {len(lines)} debug lines to clipboard", title="Copy Debug")

    def action_copy_all(self):
        import pyperclip
        from rich.text import Text as RichText

        chat = self.query_one(ChatHistory)
        lines = []
        for child in chat.children:
            try:
                if isinstance(child, IterationCard):
                    markup = child._build()
                    plain = RichText.from_markup(markup).plain
                    if plain.strip():
                        lines.append(plain.strip())
                elif isinstance(child, (VerticalScroll,)):
                    for sub in child.children:
                        try:
                            if hasattr(sub, "renderable") and sub.renderable is not None:
                                plain = str(sub.renderable)
                                if hasattr(sub.renderable, "plain"):
                                    plain = sub.renderable.plain
                                if plain.strip():
                                    lines.append(plain.strip())
                        except Exception:
                            pass
                elif hasattr(child, "renderable") and child.renderable is not None:
                    plain = str(child.renderable)
                    if hasattr(child.renderable, "plain"):
                        plain = child.renderable.plain
                    if plain.strip():
                        lines.append(plain.strip())
            except Exception:
                pass
        text = "\n\n".join(lines)
        if text:
            pyperclip.copy(text)
            self.notify(f"Copied {len(lines)} blocks to clipboard", title="Copy")
        else:
            self.notify("Nothing to copy", title="Copy", severity="warning")

    def _dispatch_command(self, query: str):
        command_input = self.query_one("#query-input", CommandInput)
        parsed = command_input.get_command_and_args()
        if parsed is None:
            return
        cmd_name, args = parsed
        cmd_name = cmd_name.lower()

        handlers = {
            "/help": self._cmd_help,
            "/verbose": self._cmd_verbose,
            "/theme": self._cmd_theme,
            "/stop": self._cmd_stop,
            "/clear": self._cmd_clear,
            "/export": self._cmd_export,
            "/settings": self._cmd_settings,
            "/history": self._cmd_history,
            "/library": self._cmd_library,
            "/session": self._cmd_session,
            "/model": self._cmd_model,
            "/status": self._cmd_status,
            "/back": self._cmd_back,
            "/quit": self._cmd_quit,
            "/exit": self._cmd_quit,
            "/telemetry": self._cmd_telemetry,
            "/diagnostics": self._cmd_diagnostics,
        }

        handler = handlers.get(cmd_name)
        if handler:
            handler(args)
        else:
            self.notify(f"Unknown command: {cmd_name}. Type /help for available commands.", title="Command", severity="warning")

    def _cmd_help(self, _args: str):
        lines = ["[bold $accent]Available Slash Commands[/bold $accent]\n"]
        for cmd in COMMAND_REGISTRY:
            if cmd.usage:
                lines.append(f"[bold $accent]{cmd.name}[/bold $accent] [dim]{cmd.usage}[/dim]")
            else:
                lines.append(f"[bold $accent]{cmd.name}[/bold $accent] [dim]{cmd.description}[/dim]")
        self.query_one(ChatHistory).add_markdown("\n".join(lines))

    def _cmd_verbose(self, _args: str):
        self._toggle_verbose()
        state = "ON" if self._verbose else "OFF"
        self.notify(f"Verbose mode: {state}", title="Verbose")

    def action_debug_cycle(self):
        panel = self.query_one(DebugPanel)
        if not panel.has_class("visible"):
            panel.add_class("visible")
            panel.remove_class("maximized")
            self.remove_class("debug-max")
            self._debug = True
            if self._worker:
                self._worker._debug = True
            self.notify("Debug: minimized (6 lines)  |  F6 to expand", title="Debug")
        elif not panel.has_class("maximized"):
            panel.add_class("maximized")
            self.add_class("debug-max")
            self._debug = True
            if self._worker:
                self._worker._debug = True
            self.notify("Debug: MAX — chat hidden  |  F6 to hide", title="Debug")
        else:
            panel.remove_class("visible", "maximized")
            self.remove_class("debug-max")
            self._debug = False
            if self._worker:
                self._worker._debug = False
            self.notify("Debug: OFF", title="Debug")

    def action_debug_tier(self):
        from adal.tui.widgets.debug_panel import (
            _CURRENT_TIER,
        )
        tiers = [
            (VERBOSITY_LOW, "LOW"),
            (VERBOSITY_MED, "MED"),
            (VERBOSITY_HIGH, "HIGH"),
        ]
        idx = _CURRENT_TIER
        next_idx = (idx + 1) % 3
        panel = self.query_one(DebugPanel)
        panel.set_tier(tiers[next_idx][0])
        self.notify(f"Debug tier: {tiers[next_idx][1]}", title="Debug")

    def _cmd_theme(self, args: str):
        from adal.tui.app import THEMES
        name = args.strip().lower()
        if name and name in THEMES:
            self.app.theme = name
            self.notify(f"Theme changed to {name}", title="Theme")
        elif name:
            self.notify(f"Theme '{name}' not found. Available: {', '.join(THEMES)}", title="Theme", severity="warning")
        else:
            self.notify(f"Current theme: {self.app.theme}. Usage: /theme <name>", title="Theme")

    def _cmd_stop(self, _args: str):
        self.app.action_stop()
        self.notify("Stopped", title="Stop")

    def _cmd_clear(self, _args: str):
        chat = self.query_one(ChatHistory)
        for widget in list(chat.children):
            widget.remove()
        self._cards = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._iter = 0
        self._update_status("Chat cleared")

    def _cmd_export(self, _args: str):
        self._export()

    def _cmd_settings(self, _args: str):
        from adal.tui.screens.settings.hub import SettingsHubScreen
        self.app.push_screen(SettingsHubScreen())

    def _cmd_history(self, _args: str):
        self.app.push_history()

    def _cmd_library(self, _args: str):
        self.app.push_library()

    def _cmd_session(self, args: str):
        sid = args.strip()
        if sid:
            self.app.push_session_detail(sid)
        else:
            self.notify("Usage: /session <session-id>", title="Session", severity="warning")

    def _cmd_model(self, _args: str):
        model = settings.llm_model or settings.deepseek_model
        provider = settings.llm_provider
        self.notify(f"Provider: {provider}  |  Model: {model}", title="Model")

    def _cmd_status(self, _args: str):
        if self._last_result:
            r = self._last_result
            elapsed = int(time.time() - self._start_time) if self._start_time > 0 else 0
            m, s = divmod(elapsed, 60)
            status = r.get("status", "unknown")
            iterations = r.get("iterations", 0)
            validated = r.get("validated_count", 0)
            failed = r.get("failed_count", 0)
            cost = r.get("cost", {}).get("total_cost", 0)
            self.query_one(ChatHistory).add_markdown(
                f"## Session Status\n"
                f"- Status: **{status.upper()}**\n"
                f"- Iterations: {iterations}  |  Validated: {validated}  |  Failed: {failed}\n"
                f"- Elapsed: {m}m{s:02d}s  |  Cost: ${cost:.5f}"
            )
        else:
            self.notify("No active session data available", title="Status")

    def _cmd_back(self, _args: str):
        self.app.action_back()

    def _cmd_quit(self, _args: str):
        self.app.exit()

    def _cmd_telemetry(self, args: str):
        if args.lower() in ("on", "1", "true", "enable"):
            settings.telemetry_enabled = True
            if self._worker and self._worker.orc:
                self._worker.orc.set_telemetry(True)
            self._update_status("\U0001f9e0  Cognitive telemetry ENABLED")
            self.notify("Cognitive telemetry enabled — observer will run after each iteration", title="Telemetry")
        elif args.lower() in ("off", "0", "false", "disable"):
            settings.telemetry_enabled = False
            if self._worker and self._worker.orc:
                self._worker.orc.set_telemetry(False)
            self._update_status("Telemetry disabled")
            self.notify("Cognitive telemetry disabled", title="Telemetry")
        else:
            status = "ON" if settings.telemetry_enabled else "OFF"
            self.notify(f"Cognitive telemetry: {status}\nUsage: /telemetry [on/off]", title="Telemetry")

    def _cmd_diagnostics(self, _args: str):
        self.app.push_telemetry_dashboard()

    def on_key(self, event):
        if event.key == "tab" and isinstance(self.focused, CommandInput):
            inp = self.focused
            if inp.is_command():
                inp.accept_suggestion()
                event.prevent_default()
                event.stop()
            return
        if event.key == "escape" and isinstance(self.focused, CommandInput):
            inp = self.focused
            if inp.is_command():
                inp.close_suggestions()
                inp.clear()
                event.prevent_default()
                event.stop()
            return
