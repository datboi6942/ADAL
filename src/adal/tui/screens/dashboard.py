import asyncio
import time

from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from adal.tui.widgets.chat_history import ChatHistory
from adal.tui.widgets.loading_spinner import LoadingSpinner
from adal.tui.widgets.query_input import QueryInput
from adal.tui.worker import OrcWorker, ReasoningUpdate, ResultReady, StatusUpdate

AGENT_LABELS = {"planner": "PLANNER", "proposer": "PROPOSER", "verifier": "VERIFIER", "decision": "DECISION"}


class DashboardScreen(Screen):
    COMPONENT_CLASSES = {"input"}

    def __init__(self):
        super().__init__()
        self._worker: OrcWorker | None = None
        self._last_result: dict | None = None
        self._query_running = False
        self._start_time: float = 0
        self._cards: dict[str, list] = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent: str | None = None
        self._continuation_context: str | None = None
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
        self._update_status("Ready \u2014 type a research question and press Enter")

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
        dots = "." * self._status_dots if self._status_dots > 0 else ""
        if not dots:
            dots = "." + "  " * (3 - self._status_dots)

        dots = "." * (self._status_dots + 1) if self._status_dots < 3 else "..."
        agent = AGENT_LABELS.get(self._current_agent or "", "") if self._current_agent else ""
        elapsed = int(time.time() - self._start_time) if self._start_time > 0 else 0

        if agent:
            line = f"\u23f3 {agent} thinking{dots}"
        else:
            line = f"\u23f3 Researching{dots}"

        if elapsed > 10:
            m, s = divmod(elapsed, 60)
            line += f" [{m}m{s}s]"

        self.query_one("#status-text", Static).update(f"[dim]{line}[/dim]")

    def on_input_submitted(self, event: Input.Submitted):
        query = event.value.strip()
        if not query or self._query_running:
            return
        self._query_running = True
        self._start_time = time.time()
        self._iter = 0
        self._cards = {"planner": [], "proposer": [], "verifier": [], "decision": []}
        self._current_agent = None

        history = self.query_one(ChatHistory)
        history.add_markdown(f"## Query\n{query}")
        event.input.clear_query()
        event.input.disabled = True
        self._start_status_animation()
        self.query_one("#loading-spinner", LoadingSpinner).start()

        asyncio.create_task(self._run_query(query))

    async def _run_query(self, query: str):
        try:
            self._worker = OrcWorker(self.app)
            if self._continuation_context:
                enriched = self._build_continuation_query(query)
                self._continuation_context = None
                await self._worker.run_query(enriched)
            else:
                await self._worker.run_query(query)
        except Exception as e:
            self.query_one(ChatHistory).add_result(f"[red]Error: {e}[/red]")
            self._query_running = False
            self._stop_status_animation()
            self.query_one(QueryInput).disabled = False
            self.query_one(QueryInput).focus()
            self.query_one("#loading-spinner", LoadingSpinner).stop()

    def _build_continuation_query(self, new_query: str) -> str:
        prev = self._last_result or {}
        fa = prev.get("final_answer", "")
        if isinstance(fa, dict):
            fa_summary = str(fa)[:800]
        else:
            fa_summary = str(fa)[:800]
        return (
            f"[CONTINUATION] Previous research produced:\n{fa_summary}\n\n"
            f"Now answer this follow-up, building on those findings:\n{new_query}"
        )

    def on_status_update(self, event: StatusUpdate):
        agent = event.name.lower()
        chat = self.query_one(ChatHistory)

        if agent == "proposer" and event.status == "thinking":
            self._iter += 1

        if event.status == "thinking":
            card = chat.add_card(agent, self._iter, "", "Thinking \u2026")
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
        self._continuation_context = result.get("session_id", "")
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
            history.add_markdown(f"## Final Answer\n{fa[:2000]}")
        elif isinstance(fa, dict):
            for k, v in fa.items():
                title = k.replace("_", " ").title()
                history.add_markdown(f"### {title}\n{str(v)[:2000]}")

        actions = VerticalScroll(classes="result-actions")
        history.mount(actions)
        actions.mount(Button("\U0001f504 Continue Research", id="continue-research", variant="primary"))
        actions.mount(Button("View Full Report \u2192", id="view-full-result"))
        actions.mount(Button("Export Markdown \u2193", id="export-result"))

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "continue-research" and self._last_result:
            qi = self.query_one(QueryInput)
            last_query = self._last_result.get("query", "")
            qi.value = ""
            qi.placeholder = (
                f"Follow-up on: \u201c{last_query[:60]}\u2026\u201d  "
                f"\u2014 type your follow-up and press Enter"
            )
            qi.focus()
            self._continuation_context = self._last_result.get("session_id", "")
        elif bid == "view-full-result" and self._last_result:
            sid = self._last_result.get("session_id", "")
            if sid:
                self.app.push_session_detail(sid)
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
