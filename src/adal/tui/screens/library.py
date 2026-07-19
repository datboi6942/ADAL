import asyncio

from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Label, Select

from adal.tui.db_queries import get_validated_procedures
from adal.tui.screens.procedure_detail import ProcedureDetailScreen
from adal.tui.screens.selectable import SelectableScreen


class LibraryScreen(SelectableScreen):
    DEFAULT_CSS = """
    LibraryScreen { align: center top; }
    #library-content { height: 1fr; padding: 1 2; }
    #domain-filter { margin: 0 0 1 0; }
    .lib-row {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        layout: horizontal;
    }
    .lib-row Button {
        margin: 0 1 0 0;
        height: auto;
        min-height: 3;
    }
    .lib-view-btn { width: 1fr; }
    .lib-export-btn { width: 12; }
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

            row = Horizontal(
                Button(
                    f"\u2713 [bold]{statement}[/bold]\n"
                    f"   [dim]{session.domain.value.upper()}  \u2022  "
                    f"Yield: {yr}  \u2022  "
                    f"Confidence: {conf:.0%}[/dim]",
                    id=f"lib-{hyp.id}",
                    variant="default",
                    classes="lib-view-btn",
                ),
                Button(
                    "\u2193 Export",
                    id=f"export-{hyp.id}",
                    variant="primary",
                    classes="lib-export-btn",
                ),
                classes="lib-row",
            )
            container.mount(row)

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("lib-"):
            hyp_id = bid[4:]
            for hyp, session, validation in self._procedures:
                if hyp.id == hyp_id:
                    self.app.push_screen(ProcedureDetailScreen(hyp, session, validation))
                    return
        elif bid.startswith("export-"):
            hyp_id = bid[7:]
            for hyp, session, validation in self._procedures:
                if hyp.id == hyp_id:
                    self._do_export(hyp, session, validation)
                    return

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "domain-filter":
            asyncio.create_task(self._load(event.value))

    def _do_export(self, hyp, session, validation):
        import re

        from adal.tui.widgets.export_dialog import ExportDialog

        content = hyp.content or {}
        hd = content.get("hypothesis", {})
        text = f"# {hd.get('statement', 'Validated Procedure')}\n\n"
        text += f"**Domain:** {session.domain.value.upper()}\n"
        text += f"**Yield:** {hd.get('expected_yield_range', 'N/A')}\n"
        text += f"**Session:** {session.query}\n\n"
        text += f"## Synthesis Procedure\n{hd.get('synthesis_procedure', '')}\n\n"
        if hd.get("workup_procedure"):
            text += f"## Workup\n{hd.get('workup_procedure', '')}\n\n"
        text += f"## Analysis\n{content.get('analysis_summary', '')}\n\n"

        name = hd.get("statement", "adal_procedure")
        name = re.sub(r"[^a-zA-Z0-9_\- ]", "", str(name)).strip()
        name = re.sub(r"\s+", "_", name)[:80].strip("_-")
        filename = f"{name}.md" if name else "adal_procedure.md"

        self.app.push_screen(ExportDialog(text, filename))
