import asyncio
import time

from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from adal.tui.db_queries import get_hypotheses, get_interactions, get_session, get_validation_results
from adal.tui.widgets.chat_history import ChatHistory
from adal.tui.widgets.loading_spinner import LoadingSpinner
from adal.tui.widgets.query_input import QueryInput
from adal.tui.worker import OrcWorker, ReasoningUpdate, ResultReady, StatusUpdate

AGENT_LABELS = {"planner": "PLANNER", "proposer": "PROPOSER", "verifier": "VERIFIER", "decision": "DECISION"}

STATUS_ICONS = {"verified": "\u2713", "rejected": "\u2717", "proposed": "\u00b7", "validating": "\u23f3", "superseded": "~"}


class SessionDetailScreen(Screen):
    COMPONENT_CLASSES = {"input"}

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
        self._status_dots = 0
        self._status_timer = None
        self._iter = 0

    def compose(self):
        yield ChatHistory(id="chat-history")
        yield QueryInput(id="query-input")
        with Horizontal(id="status-line"):
            yield LoadingSpinner(id="loading-spinner")
            yield Static("", id="status-text")
            yield Button("\u2699 Settings", id="settings-btn", classes="status-btn")
        yield Footer()

    def on_mount(self):
        self.query_one("#query-input", QueryInput).focus()
        self._update_status("Loading session\u2026")
        asyncio.create_task(self._load_session())

    def _update_status(self, text: str):
        self.query_one("#status-text", Static).update(f"[dim]{text}[/dim]")

    def _start_status_animation(self):
        self._status_dots = 0
        if self._status_timer is None:
            self._status_timer = self.set_interval(0.5, self._status_tick)

    def _stop_status_animation(self):
        if self._status_timer:
            self._status_timer.stop()
            self._status_timer = None

    def _status_tick(self):
        self._status_dots = (self._status_dots + 1) % 4
        dots = "." * (self._status_dots + 1) if self._status_dots < 3 else "..."
        agent = AGENT_LABELS.get(self._current_agent or "", "") if self._current_agent else ""
        elapsed = int(time.time() - self._start_time) if self._start_time > 0 else 0

        if agent:
            line = f"\u23f3 {agent} continuing{dots}"
        else:
            line = f"\u23f3 Continuing{dots}"

        if elapsed > 10:
            m, s = divmod(elapsed, 60)
            line += f" [{m}m{s}s]"

        self.query_one("#status-text", Static).update(f"[dim]{line}[/dim]")

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
            f"Ask a follow-up question below\u2026"
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

    def on_input_submitted(self, event: Input.Submitted):
        query = event.value.strip()
        if not query or self._query_running:
            return
        self._query_running = True
        self._start_time = time.time()
        self._cards = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent = None

        history = self.query_one(ChatHistory)
        history.add_markdown(f"## Follow-up Query\n{query}")
        event.input.clear_query()
        event.input.disabled = True
        self._start_status_animation()
        self.query_one("#loading-spinner", LoadingSpinner).start()

        asyncio.create_task(self._run_continue(query))

    async def _run_continue(self, query: str):
        try:
            self._worker = OrcWorker(self.app)
            await self._worker.run_restore(self._session_id, query=query)
        except Exception as e:
            self.query_one(ChatHistory).add_result(f"[red]Error: {e}[/red]")
            self._query_running = False
            self._stop_status_animation()
            self.query_one(QueryInput).disabled = False
            self.query_one(QueryInput).focus()
            self.query_one("#loading-spinner", LoadingSpinner).stop()

    def on_status_update(self, event: StatusUpdate):
        agent = event.name.lower()
        chat = self.query_one(ChatHistory)

        if agent == "proposer" and event.status == "thinking":
            self._iter += 1

        if event.status == "thinking":
            card = chat.add_card(agent, self._iter, "", "Continuing \u2026")
            self._cards[agent].append(card)
            self._current_agent = agent
            self._status_dots = 0
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
        self.query_one(QueryInput).disabled = False
        self.query_one(QueryInput).focus()
        self.query_one("#loading-spinner", LoadingSpinner).stop()

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

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "continue-research" and self._last_result:
            qi = self.query_one(QueryInput)
            qi.placeholder = "Type your follow-up question and press Enter"
            qi.focus()
        elif bid == "export-result" and self._last_result:
            self._export()
        elif bid == "settings-btn":
            from adal.tui.screens.settings.hub import SettingsHubScreen
            self.app.push_screen(SettingsHubScreen())

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
