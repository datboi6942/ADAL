import asyncio

from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Label, Static

from adal.tui.db_queries import list_sessions
from adal.tui.screens.selectable import SelectableScreen


class HistoryScreen(SelectableScreen):
    DEFAULT_CSS = """
    #history-content {
        height: auto;
        padding: 1 2;
    }
    #history-content Button {
        margin: 0 0 1 0;
    }
    .history-sep {
        width: 100%;
        height: 0;
    }
    """

    def compose(self):
        yield Header()
        with VerticalScroll(id="history-content"):
            yield Label("Loading sessions\u2026", id="history-status")
        yield Footer()

    def on_mount(self):
        asyncio.create_task(self._load())

    async def _load(self):
        sessions = await list_sessions(limit=100)
        container = self.query_one("#history-content", VerticalScroll)
        await container.remove_children()

        if not sessions:
            container.mount(Label("[dim]No past sessions found. Start a new research session![/dim]"))
            return

        icons = {"converged": "\u2713", "failed": "\u2717", "active": "\u23f3",
                 "max_iterations": "\u26a0", "cancelled": "\u23f9"}

        for s in sessions:
            icon = icons.get(s.status.value, "?")
            display_query = s.query[:80] + ("\u2026" if len(s.query) > 80 else "")
            container.mount(
                Static(
                    f"{icon} [bold]{display_query}[/bold]\n"
                    f"   [dim]{s.domain.value}  |  {s.status.value}  |  "
                    f"{s.iteration} iter  |  {s.created_at.strftime('%Y-%m-%d %H:%M')}[/dim]"
                )
            )
            container.mount(
                Button(f"View Session \u2192 ({s.id[:8]})", id=f"session-{s.id}", variant="default")
            )
            container.mount(Static("", classes="history-sep"))

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("session-"):
            sid = bid.replace("session-", "")
            self.app.push_session_detail(sid)
