import asyncio

from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Select

from adal.tui.db_queries import get_validated_procedures
from adal.tui.screens.procedure_detail import ProcedureDetailScreen


class LibraryScreen(Screen):
    DEFAULT_CSS = """
    LibraryScreen { align: center top; }
    #library-content { height: 1fr; padding: 1 2; }
    #domain-filter { margin: 0 0 1 0; }
    .lib-entry {
        width: 100%;
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        border-left: solid $primary-darken-1;
    }
    .lib-entry:hover { border-left: solid $accent; }
    #library-results Button { width: 100%; margin: 0 0 1 0; }
    """

    def __init__(self, domain: str | None = None):
        super().__init__()
        self._domain = domain
        self._procedures: list = []

    def compose(self):
        yield Header()
        with VerticalScroll(id="library-content"):
            yield Select(
                [("All Domains", ""), ("Chemistry", "chemistry"), ("Physics", "physics"),
                 ("Astrophysics", "astrophysics"), ("Particle/Nuclear", "particle_nuclear")],
                value=self._domain or "", id="domain-filter",
            )
            yield VerticalScroll(id="library-results")
        yield Footer()

    def on_mount(self):
        asyncio.create_task(self._load())

    async def _load(self, domain: str | None = None):
        results = await get_validated_procedures(domain or self._domain)
        self._procedures = list(results)
        container = self.query_one("#library-results", VerticalScroll)
        await container.remove_children()

        if not self._procedures:
            container.mount(Label("[dim]No validated procedures found. Run a successful research session first![/dim]"))
            return

        for hyp, session, validation in self._procedures:
            content = hyp.content or {}
            hd = content.get("hypothesis", {})
            statement = hd.get("statement", "Untitled")[:100]
            yr = hd.get("expected_yield_range", "N/A")
            conf = validation.confidence if validation else 0

            btn = Button(
                f"\u2713 [bold]{statement}[/bold]\n"
                f"   [dim]{session.domain.value.upper()}  \u2022  "
                f"Yield: {yr}  \u2022  "
                f"Confidence: {conf:.0%}[/dim]",
                id=f"lib-{hyp.id}",
                variant="default",
            )
            container.mount(btn)

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("lib-"):
            hyp_id = bid[4:]
            for hyp, session, validation in self._procedures:
                if hyp.id == hyp_id:
                    self.app.push_screen(ProcedureDetailScreen(hyp, session, validation))
                    return

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "domain-filter":
            asyncio.create_task(self._load(event.value))
