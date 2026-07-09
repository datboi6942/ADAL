import asyncio
import random
import time

from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, RichLog, Static

from adal.tui.db_queries import get_hypotheses, get_interactions, get_session, get_validation_results
from adal.tui.widgets.chat_history import ChatHistory, IterationCard
from adal.tui.widgets.debug_panel import (
    VERBOSITY_HIGH,
    VERBOSITY_LOW,
    VERBOSITY_MED,
    DebugLine,
    DebugPanel,
)
from adal.tui.widgets.loading_spinner import AGENT_ICONS, BAR_WIDTH, GRADIENT, SPARKLE_CHARS
from adal.tui.widgets.query_input import CommandInput, CommandSubmit, QuerySubmit
from adal.tui.widgets.suggestion_list import SuggestionList
from adal.tui.worker import OrcWorker, ReasoningUpdate, ResultReady, StatusUpdate

AGENT_LABELS = {"planner": "PLANNER", "proposer": "PROPOSER", "verifier": "VERIFIER", "decision": "DECISION"}

STATUS_ICONS = {"verified": "\u2713", "rejected": "\u2717", "proposed": "\u00b7", "validating": "\u23f3", "superseded": "~"}


class SessionDetailScreen(Screen):
    COMPONENT_CLASSES = {"input"}

    BINDINGS = [
        Binding("ctrl+c", "copy_all", "Copy All", priority=True),
        Binding("f6", "debug_cycle", "Debug", priority=True),
        Binding("f7", "copy_debug", "Copy Debug", priority=True),
        Binding("f8", "debug_tier", "Debug Tier", priority=True),
    ]

    def __init__(self, session_id: str):
        super().__init__()
        self._session_id = session_id
        self._worker: OrcWorker | None = None
        self._last_result: dict | None = None
        self._original_query = ""
        self._query_running = False
        self._start_time: float = 0
        self._cards: dict[str, list] = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent: str | None = None
        self._max_iters = 10
        self._status_timer = None
        self._ticking = False
        self._iter = 0
        self._tick_count = 0
        self._debug = False

    def compose(self):
        yield ChatHistory(id="chat-history")
        with Vertical(id="query-area"):
            yield CommandInput(id="query-input")
            yield SuggestionList(id="suggestion-list")
        with Horizontal(id="status-line"):
            yield Static(" ", id="status-text")
        yield DebugPanel(classes="debug-panel")
        yield Footer()

    def on_mount(self):
        self.query_one("#query-input", CommandInput).focus()
        self._update_status("Loading session\u2026")
        asyncio.create_task(self._load_session())

    def _update_status(self, text: str):
        self.query_one("#status-text", Static).update(f"[dim]{text}[/dim]")

    def _start_status_animation(self):
        self._tick_count = 0
        self._ticking = True
        if self._status_timer is None:
            self._status_timer = self.set_timer(0.15, self._status_tick)

    def _stop_status_animation(self):
        self._ticking = False
        if self._status_timer:
            self._status_timer.stop()
            self._status_timer = None

    def _status_tick(self):
        try:
            self._tick_count += 1
            elapsed = int(time.time() - self._start_time) if self._start_time > 0 else 0
            m, s = divmod(max(elapsed, 0), 60)
            agent_key = self._current_agent or ""

            icon = AGENT_ICONS.get(agent_key, "\u269b")
            pulse_val = ((self._tick_count // 2) % 16) - 8
            if pulse_val < 0:
                icon = f"[dim]{icon}[/dim]"
            elif pulse_val > 0:
                icon = f"[bold]{icon}[/bold]"

            fill_pct = self._iter / self._max_iters if self._max_iters > 0 else 0
            filled = int(fill_pct * BAR_WIDTH)

            bar_chars = []
            for i in range(BAR_WIDTH):
                wave_dist = (i - (self._tick_count % BAR_WIDTH)) % BAR_WIDTH
                if wave_dist < BAR_WIDTH // 2:
                    wave_bright = wave_dist / (BAR_WIDTH // 2)
                else:
                    wave_bright = (BAR_WIDTH - wave_dist) / (BAR_WIDTH // 2)
                if i < filled:
                    color_idx = (i + self._tick_count // 6) % len(GRADIENT)
                    bar_chars.append(f"[{GRADIENT[color_idx]}]\u2588[/{GRADIENT[color_idx]}]")
                elif i == filled:
                    color_idx = (i + self._tick_count // 6) % len(GRADIENT)
                    bar_chars.append(f"[{GRADIENT[color_idx]}]\u2593[/{GRADIENT[color_idx]}]")
                elif i == filled + 1:
                    bar_chars.append("[dim]\u2591[/dim]")
                else:
                    if random.random() < wave_bright * 0.08:
                        bar_chars.append("[dim]\u2592[/dim]")
                    else:
                        bar_chars.append("[dim]\u2591[/dim]")

            sparkle = " "
            if filled < BAR_WIDTH and random.random() < 0.12:
                sparkle_char = random.choice(SPARKLE_CHARS)
                col = GRADIENT[(filled + self._tick_count // 6) % len(GRADIENT)]
                sparkle = f"[{col}]{sparkle_char}[/{col}]"

            bar = "".join(bar_chars)
            agent_label = AGENT_LABELS.get(agent_key, "")
            agent_icon = AGENT_ICONS.get(agent_key, "\u269b")
            if agent_label:
                label = f"[bold]{agent_icon} {agent_label}[/bold]"
            else:
                label = f"[dim]{agent_icon} Continuing[/dim]"

            line = (
                f"{icon} {bar} {sparkle} "
                f"[bold]{self._iter}/{self._max_iters}[/bold] "
                f"{m}:{s:02d}  {label}"
            )
            self.query_one("#status-text", Static).update(line)
        except Exception:
            t = int(time.time() - self._start_time) if self._start_time > 0 else 0
            m, s = divmod(t, 60)
            self.query_one("#status-text", Static).update(
                f"Iter {self._iter}/{self._max_iters}  {m}:{s:02d}"
            )
        if self._ticking:
            self._status_timer = self.set_timer(0.15, self._status_tick)

    async def _load_session(self):
        session = await get_session(self._session_id)
        hypotheses = await get_hypotheses(self._session_id)
        validations = await get_validation_results(self._session_id)
        interactions = await get_interactions(self._session_id)

        valid_map: dict[str, dict] = {}
        for v in validations:
            valid_map[v.hypothesis_id] = {
                "passed": v.passed,
                "confidence": v.confidence,
                "proof": v.proof,
            }

        hyp_iter_map: dict[str, int] = {h.id: h.iteration for h in hypotheses}
        hyp_map: dict[str, any] = {h.id: h for h in hypotheses}

        ROLE_ORDER = {"planner": 0, "proposer": 1, "verifier": 2}
        ROLE_MAP = {
            "planner": {"label": "PLANNER", "agent": "planner"},
            "proposer": {"label": "PROPOSER", "agent": "proposer"},
            "verifier": {"label": "VERIFIER", "agent": "verifier"},
        }

        chat = self.query_one(ChatHistory)

        if not session:
            chat.add_result(f"[red]Session {self._session_id[:8]} not found[/red]")
            self._update_status("Session not found")
            return

        self._original_query = session.query or ""
        self._iter = session.iteration or 0

        chat.add_markdown(f"## Original Query\n{session.query}")

        sorted_ix = sorted(
            interactions,
            key=lambda ix: (
                hyp_iter_map.get(ix.hypothesis_id, 0),
                ROLE_ORDER.get(ix.agent_role.value, 3),
            ),
        )

        for ix in sorted_ix:
            role = ix.agent_role.value
            info = ROLE_MAP.get(role, {"label": role.upper(), "agent": "proposer"})
            data = ix.content or {}
            hyph = data.get("hypothesis", {})
            iteration = hyp_iter_map.get(ix.hypothesis_id, 0)
            hyp_obj = hyp_map.get(ix.hypothesis_id)

            if role == "proposer" and hyp_obj:
                icon = STATUS_ICONS.get(hyp_obj.status.value, "?")
                status_text = f"{icon} {hyp_obj.status.value.upper()}"
            else:
                status_text = info["label"]

            detail = self._build_card_detail(hyp_obj, data, hyph, role, valid_map)
            card = chat.add_card(info["agent"], iteration, detail, status_text)
            card._reasoning_preview = ""
            card._stop_pulse()

        if not sorted_ix:
            chat.add_result("[dim]No agent interaction data available for this session. The session may have failed before any iterations completed, or was created before a recent persistence bug fix.[/dim]")

        if hypotheses:
            last = hypotheses[-1]
            last_data = last.content or {}
            last_hyp = last_data.get("hypothesis", {})
            if last.status.value == "verified":
                fa = last_hyp.get("final_answer") or last_data.get("final_answer", "")
                if fa:
                    chat.add_markdown(f"## Last Validated Result\n{str(fa)[:2000]}")
            elif last.status.value == "rejected":
                chat.add_result("[dim]Last iteration was rejected — ask a follow-up to continue improving.[/dim]")

        self._update_status(
            f"\U0001f4cb Session {session.id[:8]}  \u2022  "
            f"{session.domain.value}  \u2022  "
            f"Ask a follow-up question above\u2026"
        )

    def _build_card_detail(self, h, data: dict, hyp: dict, agent_role: str, valid_map: dict) -> str:
        parts = []

        reasoning = data.get("_reasoning", "")
        if reasoning:
            parts.append(f"[bold $accent]Reasoning:[/bold $accent] {str(reasoning)[:1500]}")

        statement = hyp.get("statement", "")
        if statement:
            parts.append(f"[bold]Hypothesis:[/bold] {statement[:500]}")

        if agent_role == "proposer":
            analysis = data.get("analysis_summary", "") or hyp.get("analysis_summary", "")
            if analysis:
                parts.append(f"[bold]Analysis:[/bold] {str(analysis)[:300]}")

            synth = hyp.get("synthesis_procedure") or hyp.get("workup_procedure")
            if synth:
                parts.append(f"[bold]Synthesis:[/bold] {str(synth)[:500]}")

            yr = hyp.get("expected_yield_range", "")
            if yr:
                parts.append(f"[bold]Yield:[/bold] {yr}")

            exec_result = data.get("execution_result", {})
            if exec_result and isinstance(exec_result, dict):
                stdout = exec_result.get("stdout", "") or exec_result.get("output", "")
                if stdout:
                    parts.append(f"[bold]Execution:[/bold]\n```\n{str(stdout)[:400]}\n```")

            validation = valid_map.get(getattr(h, "id", None)) if h else None
            if validation:
                passed = validation["passed"]
                conf = validation["confidence"]
                symbol = "\u2713" if passed else "\u2717"
                status = "passed" if passed else "FAILED"
                parts.append(f"[bold]Verification:[/bold] {symbol} {status.upper()} ({conf:.0%} confidence)")
                proof = validation.get("proof", {})
                if proof and isinstance(proof, dict):
                    flaws = proof.get("fatal_flaws", [])
                    if flaws:
                        parts.append("[bold]Flaws:[/bold] " + ", ".join(str(f)[:80] for f in flaws[:3]))

        elif agent_role == "verifier":
            validation = valid_map.get(getattr(h, "id", None)) if h else None
            if validation:
                passed = validation["passed"]
                conf = validation["confidence"]
                symbol = "\u2713" if passed else "\u2717"
                verdict_label = "PASSED" if passed else "FAILED"
                parts.append(f"[bold]Verdict:[/bold] {symbol} {verdict_label} ({conf:.0%} confidence)")
                proof = validation.get("proof", {})
                if proof and isinstance(proof, dict):
                    flaws = proof.get("fatal_flaws", [])
                    if flaws:
                        parts.append("[bold]Fatal Flaws:[/bold]")
                        for f in flaws[:5]:
                            parts.append(f"  \u2022 {str(f)[:120]}")
                    suggestions = proof.get("suggestions", [])
                    if suggestions:
                        parts.append("[bold]Suggestions:[/bold]")
                        for s in suggestions[:3]:
                            parts.append(f"  \u2022 {str(s)[:120]}")

            verdict_data = data.get("verdict_result") or data
            corrected = verdict_data.get("corrected_values", {})
            if corrected and isinstance(corrected, dict) and corrected:
                parts.append("[bold]Corrected Values:[/bold]")
                for k, v in list(corrected.items())[:5]:
                    parts.append(f"  {k}: {v}")

        elif agent_role == "planner":
            directive = data.get("directive_to_proposer", "")
            if directive:
                parts.append(f"[bold]Directive:[/bold] {str(directive)[:300]}")
            action = data.get("action", "")
            if action:
                parts.append(f"[bold]Action:[/bold] {action.upper()}")
            reason = data.get("reason", "") or data.get("convergence_criteria_met", "")
            if reason:
                parts.append(f"[bold]Reason:[/bold] {str(reason)[:300]}")

        if not parts:
            parts.append("[dim]No detail available[/dim]")

        return "\n\n".join(parts)

    def on_query_submit(self, event: QuerySubmit):
        query = event.query
        if not query or self._query_running:
            return
        self._query_running = True
        self._start_time = time.time()
        self._cards = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent = None

        history = self.query_one(ChatHistory)
        history.add_markdown(f"## Follow-up Query\n{query}")
        qi = self.query_one(CommandInput)
        qi.clear_query()
        qi.read_only = True
        self._start_status_animation()
        self._status_tick()

        asyncio.create_task(self._run_continue(query))

    def on_command_submit(self, event: CommandSubmit):
        if self._query_running:
            return
        self._dispatch_command(event.command)
        self.query_one(CommandInput).clear_query()

    async def _run_continue(self, query: str):
        try:
            self._worker = OrcWorker(self.app)
            self._worker._debug = self._debug
            await self._worker.run_restore(self._session_id, query=query)
        except Exception as e:
            self.query_one(ChatHistory).add_result(f"[red]Error: {e}[/red]")
            self._query_running = False
            self._stop_status_animation()
            self.query_one(CommandInput).read_only = False
            self.query_one(CommandInput).focus()

    def on_status_update(self, event: StatusUpdate):
        agent = event.name.lower()
        chat = self.query_one(ChatHistory)

        if agent == "proposer" and event.status == "thinking":
            self._iter += 1

        if event.status == "thinking":
            card = chat.add_card(agent, self._iter, "", "Continuing \u2026")
            self._cards[agent].append(card)
            self._current_agent = agent
        elif event.status == "done":
            cards = self._cards.get(agent, [])
            if cards:
                cards[-1].set_status("", event.detail or "")
        elif event.status == "error":
            cards = self._cards.get(agent, [])
            if cards:
                cards[-1].set_status("[red]Failed[/red]", event.detail or "")

    def on_reasoning_update(self, event: ReasoningUpdate):
        agent = event.name.lower()
        cards = self._cards.get(agent, [])
        if cards:
            cards[-1].set_reasoning_preview(event.text)
            if not cards[-1]._collapsed:
                cards[-1]._detail += "\n" + event.text[:500]
                cards[-1]._write()

    def on_result_ready(self, event: ResultReady):
        self._query_running = False
        self._stop_status_animation()
        self.query_one(CommandInput).read_only = False
        self.query_one(CommandInput).focus()

        result = event.result
        self._last_result = result
        elapsed = time.time() - self._start_time

        status = result.get("status", "unknown")
        iterations = result.get("iterations", 0)
        validated = result.get("validated_count", 0)
        cost = result.get("cost", {}).get("total_cost", 0)

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
            history.add_markdown(f"## Updated Result\n{fa[:2000]}")
        elif isinstance(fa, dict):
            for k, v in fa.items():
                title = k.replace("_", " ").title()
                history.add_markdown(f"### {title}\n{str(v)[:2000]}")

        actions = VerticalScroll(classes="result-actions")
        history.mount(actions)
        actions.mount(Button("\U0001f504 Continue Research", id="continue-research", variant="primary"))
        actions.mount(Button("Export Markdown \u2193", id="export-result"))

    def on_debug_line(self, event: DebugLine):
        if self._debug:
            self.query_one(DebugPanel).write(
                event.category, event.event, event.detail,
                verbosity=event.verbosity,
            )

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

    def _dispatch_command(self, query: str):
        command_input = self.query_one(CommandInput)
        parsed = command_input.get_command_and_args()
        if parsed is None:
            return
        cmd_name, args = parsed
        cmd_name = cmd_name.lower()

        if cmd_name == "/help":
            from adal.tui.widgets.commands import COMMAND_REGISTRY
            lines = ["[bold $accent]Available Slash Commands[/bold $accent]\n"]
            for cmd in COMMAND_REGISTRY:
                if cmd.usage:
                    lines.append(f"[bold $accent]{cmd.name}[/bold $accent] [dim]{cmd.usage}[/dim]")
                else:
                    lines.append(f"[bold $accent]{cmd.name}[/bold $accent] [dim]{cmd.description}[/dim]")
            self.query_one(ChatHistory).add_markdown("\n".join(lines))
        elif cmd_name == "/verbose":
            self.notify("Verbose mode is not available in session view", title="Verbose")
        elif cmd_name in ("/quit", "/exit"):
            self.app.exit()
        elif cmd_name == "/settings":
            from adal.tui.screens.settings.hub import SettingsHubScreen
            self.app.push_screen(SettingsHubScreen())
        elif cmd_name == "/back":
            self.app.action_back()
        elif cmd_name == "/history":
            self.app.push_history()
        elif cmd_name == "/library":
            self.app.push_library()
        elif cmd_name == "/status":
            self.notify("Session detail loaded — see above", title="Status")
        elif cmd_name == "/clear":
            self.notify("Clear not available in session view", title="Clear")
        else:
            self.notify(f"Unknown command: {cmd_name}. Type /help for available commands.", title="Command", severity="warning")

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "continue-research" and self._last_result:
            qi = self.query_one(CommandInput)
            qi.placeholder = "Type your follow-up question and press Enter"
            qi.focus()
        elif bid == "export-result" and self._last_result:
            self._export()

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

    def _export(self):
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
            path = Path("adal_export.md")
            path.write_text(text)
            self.notify(f"Exported to {path}", title="Export")
        except Exception as e:
            self.notify(str(e), title="Export Failed", severity="error")
