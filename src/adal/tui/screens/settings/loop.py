from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label

from adal.config import settings
from adal.tui.screens.settings.agents import _update_env


class LoopSettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="loop-settings"):
            yield Label("[bold]Agent Loop Control[/bold]\n[dim]Parameters that govern the research iteration cycle[/dim]")
            yield Label("Max Tool Turns")
            yield Input(value=str(settings.llm_max_tool_turns), placeholder="6", id="max-tool-turns")
            yield Label("  [dim]Max web search + tool cycles before forced answer[/dim]")
            yield Label("LLM Retry Count")
            yield Input(value=str(settings.agent_llm_retry_count), placeholder="2", id="llm-retry-count")
            yield Label("  [dim]Retries when LLM returns empty or bad output[/dim]")
            yield Label("Pivot Threshold")
            yield Input(value=str(settings.orchestrator_pivot_threshold), placeholder="3", id="pivot-threshold")
            yield Label("  [dim]Consecutive identical failures before auto-PIVOT[/dim]")
            yield Label("Max Parallel Tools")
            yield Input(value=str(settings.max_parallel_tools), placeholder="2", id="max-parallel-tools")
            yield Label("  [dim]Max tools executed per LLM turn[/dim]")
            yield Label("Tool Fail Streak Limit")
            yield Input(value=str(settings.tool_fail_streak_limit), placeholder="3", id="tool-fail-limit")
            yield Label("  [dim]Consecutive tool failures before forced answer[/dim]")
            yield Button("\U0001f4be Save", id="save-loop", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-loop":
            return
        for field_id, key in [
            ("max-tool-turns", "LLM_MAX_TOOL_TURNS"),
            ("llm-retry-count", "AGENT_LLM_RETRY_COUNT"),
            ("pivot-threshold", "ORCHESTRATOR_PIVOT_THRESHOLD"),
            ("max-parallel-tools", "MAX_PARALLEL_TOOLS"),
            ("tool-fail-limit", "TOOL_FAIL_STREAK_LIMIT"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Loop Settings Saved")
