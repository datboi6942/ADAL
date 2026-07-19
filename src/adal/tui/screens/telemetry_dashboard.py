import asyncio

from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Select, Static

from adal.db.models import DiagnosticSeverity
from adal.tui.db_queries import get_diagnostic_stats, get_meta_diagnostics
from adal.tui.screens.selectable import SelectableScreen

SEVERITY_ICONS = {
    DiagnosticSeverity.CRITICAL: "\U0001f534",
    DiagnosticSeverity.HIGH: "\U0001f7e0",
    DiagnosticSeverity.MED: "\U0001f535",
    DiagnosticSeverity.LOW: "\u26aa",
}

SEVERITY_COLORS = {
    DiagnosticSeverity.CRITICAL: "bold $error",
    DiagnosticSeverity.HIGH: "bold $warning",
    DiagnosticSeverity.MED: "bold $primary",
    DiagnosticSeverity.LOW: "dim",
}


class TelemetryDashboardScreen(SelectableScreen):
    DEFAULT_CSS = """
    TelemetryDashboardScreen {
        align: center top;
    }
    #telemetry-content {
        height: 1fr;
        padding: 1 2;
    }
    #telemetry-stats {
        height: auto;
        padding: 1 2;
        background: $surface;
        border: solid $primary-darken-1;
        margin-bottom: 1;
    }
    #severity-filter {
        margin: 0 0 1 0;
    }
    #telemetry-results {
        height: 1fr;
    }
    .diag-entry {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border-left: solid $primary-darken-1;
        background: $surface;
    }
    .diag-session {
        padding-left: 2;
    }
    .diag-critique {
        padding-left: 2;
    }
    .diag-recommendation {
        padding-left: 2;
    }
    """

    def __init__(self):
        super().__init__()
        self._diagnostics: list = []

    def compose(self):
        yield Header()
        with VerticalScroll(id="telemetry-content"):
            yield Static("Loading diagnostics\u2026", id="telemetry-stats")
            yield Select(
                [("All Severities", ""), ("Critical", "critical"),
                 ("High", "high"), ("Med", "med"), ("Low", "low")],
                value="",
                id="severity-filter",
            )
            yield VerticalScroll(id="telemetry-results")
        yield Footer()

    def on_mount(self):
        asyncio.create_task(self._load())

    async def _load(self, severity: str | None = None):
        stats = await get_diagnostic_stats()
        results = await get_meta_diagnostics(severity=severity)
        self._diagnostics = list(results)

        stats_parts = []
        for sev in (DiagnosticSeverity.CRITICAL, DiagnosticSeverity.HIGH, DiagnosticSeverity.MED, DiagnosticSeverity.LOW):
            count = stats.get(sev, 0)
            if count > 0:
                icon = SEVERITY_ICONS.get(sev, "")
                color = SEVERITY_COLORS.get(sev, "dim")
                stats_parts.append(f"[{color}]{icon} {sev.value.upper()} {count}[/{color}]")
            else:
                stats_parts.append(f"[dim]{sev.value.upper()} 0[/dim]")
        stats_text = "  ".join(stats_parts)
        total = sum(stats.values())
        if total > 0:
            stats_text = f"[bold]Diagnostics: {total} total[/bold]    {stats_text}"
        else:
            stats_text = "[dim]No diagnostics recorded yet[/dim]    " + stats_text

        self.query_one("#telemetry-stats", Static).update(stats_text)

        container = self.query_one("#telemetry-results", VerticalScroll)
        await container.remove_children()

        if not self._diagnostics:
            container.mount(Static(
                "[dim]No diagnostics recorded yet.[/dim]\n\n"
                "[bold]To enable cognitive telemetry:[/bold]\n"
                "  \u2022 Type [bold $accent]/telemetry on[/bold $accent] in the query input\n"
                "  \u2022 Start a research query — the observer runs after each iteration\n"
                "  \u2022 Diagnostics appear here automatically\n\n"
                "[dim]Or configure in: Settings \u2192 Cognitive Telemetry[/dim]",
                classes="diag-entry",
            ))
            return

        for diag, session_query, session_domain in self._diagnostics:
            sev = diag.severity
            color = SEVERITY_COLORS.get(sev, "dim")
            icon = SEVERITY_ICONS.get(sev, "")
            session_label = (session_query or "?")[:60]
            domain_str = f" [{session_domain}]" if session_domain else ""

            lines = [
                f"[{color}]{icon} [{sev.value.upper()}] iter {diag.iteration}: {diag.pattern_detected}[/{color}]",
                f"[dim]Session {diag.session_id[:8]}{domain_str}: \"{session_label}\"[/dim]",
            ]
            if diag.debugger_critique:
                lines.append(f"[dim italic]{diag.debugger_critique[:300]}[/dim italic]")
            if diag.system_recommendation:
                lines.append(f"[dim]\u2192 {diag.system_recommendation[:200]}[/dim]")

            entry = Static("\n".join(lines), classes="diag-entry")
            container.mount(entry)

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "severity-filter":
            val = event.value
            asyncio.create_task(self._load(severity=val if val else None))
