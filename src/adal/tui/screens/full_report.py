import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Markdown, Static

from adal.tui.screens.selectable import SelectableScreen

CONFIDENCE_BAR = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"]


def _s(text: object) -> str:
    return str(text or "").replace("[", "\\[")


class FullReportScreen(SelectableScreen):
    DEFAULT_CSS = """
    FullReportScreen {
        align: center top;
    }
    #report-scroll {
        height: 1fr;
        padding: 2 4;
    }
    #report-banner {
        width: 100%;
        padding: 1 0;
        margin-bottom: 1;
        border-bottom: solid $primary-darken-1;
        height: auto;
    }
    #report-actions {
        width: 100%;
        padding: 2 0;
        align: center middle;
        layout: horizontal;
    }
    #report-actions Button {
        margin: 0 1;
    }
    """

    def __init__(self, result: dict):
        super().__init__()
        self._result = result

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="report-scroll"):
            yield Static("", id="report-banner")
            yield Markdown(" ", id="report-body")
            yield VerticalScroll(id="report-actions")
        yield Footer()

    def on_mount(self):
        self._build_content()

    def _build_content(self):
        r = self._result

        query = r.get("query", "")
        domain = r.get("domain", "unknown").upper()
        status_val = r.get("status", "unknown")
        iterations = r.get("iterations", 0)
        validated = r.get("validated_count", 0)
        failed = r.get("failed_count", 0)
        cost = r.get("cost", {}).get("total_cost", 0)
        elapsed = r.get("elapsed_seconds", 0)

        status_display = status_val.upper()
        status_color = "$success" if status_val in ("converged",) else "$error"

        banner = self.query_one("#report-banner", Static)
        banner.update(
            f"[bold $accent]{_s(query)[:200]}[/bold $accent]\n\n"
            f"[dim]Domain:[/dim] [bold]{domain}[/bold]  "
            f"[dim]Status:[/dim] [{status_color}]{status_display}[/{status_color}]  "
            f"[dim]Iterations:[/dim] {iterations}\n"
            f"[dim]Validated:[/dim] [bold $success]{validated}[/bold $success]  "
            f"[dim]Failed:[/dim] [bold $error]{failed}[/bold $error]  "
            f"[dim]Cost:[/dim] ${cost:.5f}  "
            f"[dim]Elapsed:[/dim] {int(elapsed // 60)}m{int(elapsed % 60):02d}s"
        )

        md_parts = []

        fa = r.get("final_answer", "")
        if fa and str(fa).strip():
            md_parts.append(_s(str(fa)))

        validated_results = r.get("validated_results", [])
        if validated_results:
            md_parts.append("\n\n---\n\n# Validated Results\n")
            for i, vr in enumerate(validated_results, 1):
                hyp = vr.get("hypothesis", {}) if isinstance(vr.get("hypothesis"), dict) else {}
                verdict = vr.get("verdict", {}) if isinstance(vr.get("verdict"), dict) else {}
                iteration = vr.get("iteration", i)

                statement = hyp.get("statement", "")
                if statement:
                    md_parts.append(f"\n## Result {i} \u2014 Iteration {iteration}\n")
                    md_parts.append(f"**{_s(str(statement)[:200])}**\n\n")

                conf = verdict.get("confidence", 0)
                conf_pct = conf * 100
                md_parts.append(f"- **Confidence:** {conf_pct:.0f}%\n")
                md_parts.append(f"- **Verdict:** {verdict.get('verdict', 'N/A')}\n")

                synthesis = hyp.get("synthesis_procedure", "")
                if synthesis and str(synthesis).strip():
                    md_parts.append(f"\n### Synthesis Procedure\n{_s(str(synthesis)[:5000])}\n")

                workup = hyp.get("workup_procedure", "")
                if workup and str(workup).strip():
                    md_parts.append(f"\n### Workup Procedure\n{_s(str(workup)[:3000])}\n")

                analysis = hyp.get("analysis_summary", "") or vr.get("analysis_summary", "")
                if analysis and str(analysis).strip():
                    md_parts.append(f"\n### Analysis Summary\n{_s(str(analysis)[:3000])}\n")

                expected_yield = hyp.get("expected_yield_range", "")
                if expected_yield:
                    md_parts.append(f"\n**Expected Yield:** {_s(str(expected_yield))}\n")

                exec_result = hyp.get("execution_result", {}) if isinstance(hyp.get("execution_result"), dict) else {}
                stdout = exec_result.get("stdout", "") or exec_result.get("output", "")
                stderr = exec_result.get("stderr", "")
                if stdout or stderr:
                    md_parts.append(f"\n### Execution Output\n```\n{stdout or ''}\n{stderr or ''}\n```\n")

                flaws = verdict.get("fatal_flaws", [])
                if flaws:
                    md_parts.append("\n### Fatal Flaws\n")
                    for f in flaws:
                        md_parts.append(f"- {_s(str(f))}\n")

                suggestions = verdict.get("suggestions", [])
                if suggestions:
                    md_parts.append("\n### Suggestions\n")
                    for s in suggestions:
                        md_parts.append(f"- {_s(str(s))}\n")

                corrected = verdict.get("corrected_values", {})
                if corrected and isinstance(corrected, dict):
                    md_parts.append("\n### Corrected Values\n")
                    for k, v in corrected.items():
                        md_parts.append(f"- **{_s(str(k))}:** {_s(str(v))}\n")

                citations = hyp.get("citations", [])
                if citations:
                    md_parts.append("\n### Citations\n")
                    for c in citations[:15]:
                        md_parts.append(f"- {_s(str(c))}\n")

                notes = hyp.get("notes", [])
                if notes:
                    md_parts.append("\n### Notes\n")
                    for n in notes:
                        md_parts.append(f"- {_s(str(n))}\n")

                if i < len(validated_results):
                    md_parts.append("\n---\n")

        failed_attempts = r.get("failed_attempts", [])
        if failed_attempts:
            md_parts.append("\n\n---\n\n# Failed Attempts\n")
            for fa_entry in failed_attempts:
                iteration = fa_entry.get("iteration", "?")
                summary = fa_entry.get("hypothesis_summary", fa_entry.get("reason", ""))
                flaws = fa_entry.get("fatal_flaws", [])
                reason = fa_entry.get("reason", "")
                md_parts.append(f"\n### Iteration {iteration}\n")
                if summary:
                    md_parts.append(f"{_s(str(summary)[:500])}\n\n")
                if flaws:
                    md_parts.append("**Fatal flaws:**\n")
                    for f in flaws:
                        md_parts.append(f"- {_s(str(f))}\n")
                if reason and reason != summary:
                    md_parts.append(f"\n**Reason:** {_s(str(reason)[:300])}\n")
                md_parts.append("\n")

        body = self.query_one("#report-body", Markdown)
        body.update("\n".join(md_parts) if md_parts else "*No report content available.*")

        actions = self.query_one("#report-actions", VerticalScroll)
        actions.mount(Button("\U0001f4e5 Export Markdown", id="export-report", variant="primary"))
        actions.mount(Button("\U0001f519 Back to Dashboard", id="back-dashboard"))

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "export-report":
            self._export()
        elif bid == "back-dashboard":
            self.dismiss()

    def _export(self):
        asyncio.create_task(self._do_export())

    async def _do_export(self):
        try:
            r = self._result
            query = r.get("query", "")
            fa = r.get("final_answer", "")
            text = f"# ADAL Research Report\n\n**Query:** {query}\n"
            text += f"**Domain:** {r.get('domain', 'unknown')}\n"
            text += f"**Status:** {r.get('status', 'unknown')}\n"
            text += f"**Iterations:** {r.get('iterations', 0)}\n"
            text += f"**Validated:** {r.get('validated_count', 0)}\n"
            text += f"**Failed:** {r.get('failed_count', 0)}\n"
            text += f"**Cost:** ${r.get('cost', {}).get('total_cost', 0):.5f}\n\n"
            text += "---\n\n"

            if isinstance(fa, str):
                text += fa
            elif isinstance(fa, dict):
                for k, v in fa.items():
                    text += f"## {k.replace('_', ' ').title()}\n{str(v)}\n\n"

            validated_results = r.get("validated_results", [])
            if validated_results:
                text += "\n\n---\n\n# Validated Results\n\n"
                for vr in validated_results:
                    hyp = vr.get("hypothesis", {}) if isinstance(vr.get("hypothesis"), dict) else {}
                    text += f"## {hyp.get('statement', 'Procedure')[:200]}\n\n"
                    for key in ("synthesis_procedure", "workup_procedure", "analysis_summary"):
                        val = hyp.get(key, "") or vr.get(key, "")
                        if val and str(val).strip():
                            text += f"### {key.replace('_', ' ').title()}\n{str(val)}\n\n"
                    text += "---\n\n"

            from adal.tui.utils import generate_export_filename

            content_preview = fa if isinstance(fa, str) else str(fa)
            filename = await generate_export_filename(query, content_preview)
            path = Path(f"{filename}.md")
            path.write_text(text)
            self.notify(f"Exported to {path}", title="Export")
        except Exception as e:
            self.notify(str(e), title="Export Failed", severity="error")
