from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label

from adal.config import settings
from adal.tui.screens.selectable import SelectableScreen
from adal.tui.screens.settings.agents import _update_env


class AdvancedSettingsScreen(SelectableScreen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="advanced-settings"):
            yield Label("[bold]Execution Limits[/bold]")
            yield Label("Max Iterations")
            yield Input(value=str(settings.max_iterations), placeholder="10", id="max-iter")
            yield Label("  [dim]Total research loop iterations[/dim]")
            yield Label("Sandbox Timeout (seconds)")
            yield Input(value=str(settings.sandbox_timeout), placeholder="120", id="sandbox-timeout")
            yield Label("  [dim]Script execution time limit[/dim]")
            yield Label("Planner Initial Tool Turns")
            yield Input(value=str(settings.planner_initial_tool_turns), placeholder="0", id="planner-init-turns")
            yield Label("  [dim]Tool turns for initial domain classification (0 = no tools)[/dim]")
            yield Label("Self-Critique Max Turns")
            yield Input(value=str(settings.self_critique_max_tool_turns), placeholder="3", id="critique-turns")
            yield Label("  [dim]Tool turns for proposer self-critique review[/dim]")
            yield Label("Deep Verify Max Turns")
            yield Input(value=str(settings.deep_verify_max_tool_turns), placeholder="3", id="deep-verify-turns")
            yield Label("  [dim]Tool turns for deep verification pass[/dim]")
            yield Label("Revise Max Turns")
            yield Input(value=str(settings.revise_max_tool_turns), placeholder="3", id="revise-turns")
            yield Label("  [dim]Tool turns for proposer revision pass[/dim]")

            yield Label("[bold]Memory Tuning[/bold]")
            yield Label("Memory Context Cap")
            yield Input(value=str(settings.memory_enrich_context_cap), placeholder="3", id="memory-context-cap")
            yield Label("  [dim]Max memories injected into agent prompts[/dim]")
            yield Label("Memory Index Min Rows")
            yield Input(value=str(settings.memory_index_min_rows), placeholder="256", id="memory-index-min")
            yield Label("  [dim]Row count before LanceDB creates vector index[/dim]")

            yield Label("[bold]Search Tuning[/bold]")
            yield Label("Search Max Results")
            yield Input(value=str(settings.search_max_results), placeholder="5", id="search-max-results")
            yield Label("  [dim]Results returned per web_search call[/dim]")
            yield Label("Search Timeout (seconds)")
            yield Input(value=str(settings.search_timeout), placeholder="20", id="search-timeout")
            yield Label("  [dim]DDG request timeout[/dim]")
            yield Label("Fetch Max Chars")
            yield Input(value=str(settings.fetch_max_chars), placeholder="10000", id="fetch-max-chars")
            yield Label("  [dim]Truncation length for fetched page content[/dim]")
            yield Label("Fetch Timeout (seconds)")
            yield Input(value=str(settings.fetch_timeout), placeholder="25", id="fetch-timeout")
            yield Label("Fetch Max Retries")
            yield Input(value=str(settings.fetch_max_retries), placeholder="3", id="fetch-max-retries")
            yield Label("Search Backoff Base")
            yield Input(value=str(settings.search_backoff_base), placeholder="2.0", id="search-backoff-base")

            yield Button("\U0001f4be Save", id="save-advanced", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-advanced":
            return
        for field_id, key in [
            ("max-iter", "MAX_ITERATIONS"),
            ("sandbox-timeout", "SANDBOX_TIMEOUT"),
            ("planner-init-turns", "PLANNER_INITIAL_TOOL_TURNS"),
            ("critique-turns", "SELF_CRITIQUE_MAX_TOOL_TURNS"),
            ("deep-verify-turns", "DEEP_VERIFY_MAX_TOOL_TURNS"),
            ("revise-turns", "REVISE_MAX_TOOL_TURNS"),
            ("memory-context-cap", "MEMORY_ENRICH_CONTEXT_CAP"),
            ("memory-index-min", "MEMORY_INDEX_MIN_ROWS"),
            ("search-max-results", "SEARCH_MAX_RESULTS"),
            ("search-timeout", "SEARCH_TIMEOUT"),
            ("fetch-max-chars", "FETCH_MAX_CHARS"),
            ("fetch-timeout", "FETCH_TIMEOUT"),
            ("fetch-max-retries", "FETCH_MAX_RETRIES"),
            ("search-backoff-base", "SEARCH_BACKOFF_BASE"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Advanced Settings Saved")
