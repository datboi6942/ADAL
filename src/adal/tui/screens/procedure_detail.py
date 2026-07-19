
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Label, Static

from adal.db.models import Hypothesis, Session, ValidationResult
from adal.tui.screens.selectable import SelectableScreen

CONFIDENCE_BAR = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"]


def _s(text: object) -> str:
    return str(text or "").replace("[", "\\[")


class ProcedureDetailScreen(SelectableScreen):
    DEFAULT_CSS = """
    ProcedureDetailScreen {
        align: center top;
    }
    #procedure-scroll {
        height: 1fr;
        padding: 2 4;
    }
    #procedure-banner {
        width: 100%;
        padding: 1 0;
        margin-bottom: 1;
        border-bottom: solid $primary-darken-1;
    }
    .procedure-section {
        margin-bottom: 1;
    }
    .procedure-section-title {
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
    }
    .procedure-badge {
        padding: 0 2;
        color: $text;
    }
    .confidence-bar {
        color: $success;
    }
    .procedure-actions {
        width: 100%;
        padding: 2 0;
        align: center middle;
        layout: horizontal;
    }
    .procedure-actions Button {
        margin: 0 1;
    }
    """

    def __init__(self, hypothesis: Hypothesis, session: Session, validation: ValidationResult | None = None):
        super().__init__()
        self._hypothesis = hypothesis
        self._session = session
        self._validation = validation

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="procedure-scroll"):
            yield Static("", id="procedure-banner")
            yield VerticalScroll(id="procedure-body")
        yield Footer()

    def on_mount(self):
        self._build_content()

    def _build_content(self):
        content = self._hypothesis.content or {}
        hyp = content.get("hypothesis", {})
        validation = self._validation
        session = self._session

        banner = self.query_one("#procedure-banner", Static)
        body = self.query_one("#procedure-body", VerticalScroll)
        body.remove_children()

        domain = session.domain.value.upper()
        conf = validation.confidence if validation else 0
        conf_bar = self._render_confidence(conf)
        passed = validation.passed if validation else True

        status_color = "$success" if passed else "$error"
        status_text = "\u2713 VALIDATED" if passed else "\u2717 REJECTED"

        banner.update(
            f"[bold $accent]{_s(hyp.get('statement', 'Untitled'))[:120]}[/bold $accent]\n\n"
            f"[dim]Domain:[/dim] [bold]{domain}[/bold]  "
            f"[dim]Yield:[/dim] [bold]{_s(hyp.get('expected_yield_range', 'N/A'))}[/bold]  "
            f"[dim]Status:[/dim] [{status_color}]{status_text}[/{status_color}]\n"
            f"[dim]Session:[/dim] {_s(session.query[:80])}...  "
            f"[dim]Created:[/dim] {self._hypothesis.created_at.strftime('%Y-%m-%d')}\n"
            f"[dim]Confidence:[/dim] [bold]{conf:.0%}[/bold] {conf_bar}"
        )

        self._add_section(body, "Synthesis Procedure", hyp.get("synthesis_procedure", ""))
        self._add_section(body, "Workup Procedure", hyp.get("workup_procedure", ""))
        self._add_section(body, "Analysis Summary", content.get("analysis_summary", ""))

        exec_result = content.get("execution_result", {})
        if exec_result and isinstance(exec_result, dict):
            stdout = exec_result.get("stdout", "") or exec_result.get("output", "")
            stderr = exec_result.get("stderr", "")
            if stdout or stderr:
                out = f"```\n{stdout or ''}\n{stderr or ''}\n```"
                self._add_section(body, "Execution Output", out)

        if validation and validation.proof:
            proof = validation.proof or {}
            flaws = proof.get("fatal_flaws", [])
            if flaws:
                flaws_text = "\n".join(f"  \u2022 {f}" for f in flaws)
                self._add_section(body, "Fatal Flaws", flaws_text)
            suggestions = proof.get("suggestions", [])
            if suggestions:
                sugg_text = "\n".join(f"  \u2022 {s}" for s in suggestions)
                self._add_section(body, "Suggestions", sugg_text)

        corrected = content.get("corrected_values", {})
        if corrected and isinstance(corrected, dict):
            corr_text = "\n".join(f"  {k}: {v}" for k, v in corrected.items())
            self._add_section(body, "Corrected Values", corr_text)

        yield_text = hyp.get("expected_yield_range", "")
        equiv = hyp.get("equivalents_used", "")
        if yield_text or equiv:
            extra = f"**Yield:** {yield_text}\n**Equivalents:** {equiv}" if yield_text or equiv else ""
            self._add_section(body, "Yield Details", extra)

        citations = content.get("citations", []) or hyp.get("citations", [])
        if citations:
            self._add_section(body, "Citations", "\n".join(f"  \u2022 {c}" for c in citations[:15]))

        features = content.get("features_detected", [])
        if features:
            self._add_section(body, "Features Detected", ", ".join(str(f) for f in features[:20]))

        actions = VerticalScroll(classes="procedure-actions")
        body.mount(actions)
        actions.mount(Button(f"\U0001f4cb View Full Session ({session.id[:8]})", id="view-session", variant="primary"))
        actions.mount(Button("\U0001f4e5 Export Markdown", id="export-procedure"))

    def _add_section(self, container, title: str, content: str):
        if not content or not str(content).strip():
            return
        container.mount(Label(f"[bold $accent]\u2500 {title} \u2500[/bold $accent]", classes="procedure-section-title"))
        container.mount(Static(_s(str(content)[:3000]), classes="procedure-section"))

    def _render_confidence(self, conf: float) -> str:
        level = min(int(conf * len(CONFIDENCE_BAR)), len(CONFIDENCE_BAR) - 1)
        filled = "".join(CONFIDENCE_BAR[: level + 1])
        empty = "".join(["\u00b7"] * (len(CONFIDENCE_BAR) - level - 1))
        return f"[{'$success' if conf >= 0.7 else '$warning' if conf >= 0.4 else '$error'}]{filled}[/][dim]{empty}[/dim]"

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "view-session":
            self.app.push_session_detail(self._session.id)
        elif bid == "export-procedure":
            self._export()

    def _export(self):
        self._do_export()

    def _do_export(self):
        import re

        from adal.tui.widgets.export_dialog import ExportDialog

        content = self._hypothesis.content or {}
        hyp = content.get("hypothesis", {})
        text = f"# {hyp.get('statement', 'Validated Procedure')}\n\n"
        text += f"**Domain:** {self._session.domain.value.upper()}\n"
        text += f"**Yield:** {hyp.get('expected_yield_range', 'N/A')}\n"
        text += f"**Session:** {self._session.query}\n\n"
        text += f"## Synthesis Procedure\n{hyp.get('synthesis_procedure', '')}\n\n"
        if hyp.get("workup_procedure"):
            text += f"## Workup\n{hyp.get('workup_procedure', '')}\n\n"
        text += f"## Analysis\n{content.get('analysis_summary', '')}\n\n"

        name = hyp.get("statement", "adal_procedure")
        name = re.sub(r"[^a-zA-Z0-9_\- ]", "", str(name)).strip()
        name = re.sub(r"\s+", "_", name)[:80].strip("_-")
        filename = f"{name}.md" if name else "adal_procedure.md"

        self.app.push_screen(ExportDialog(text, filename))
