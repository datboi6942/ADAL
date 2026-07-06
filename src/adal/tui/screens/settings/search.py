from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label

from adal.config import settings
from adal.tui.screens.settings.agents import _update_env


class SearchSettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="search-settings"):
            yield Label("Throttle Delay (seconds)")
            yield Input(value=str(settings.search_throttle_delay), placeholder="2.0", id="throttle-delay")
            yield Label("Max Retries")
            yield Input(value=str(settings.search_max_retries), placeholder="3", id="max-retries")
            yield Label("Blocked Fetch Hosts (comma-separated)")
            yield Input(value=settings.blocked_fetch_hosts, placeholder="pubchem.ncbi.nlm.nih.gov", id="blocked-hosts")
            yield Button("\U0001f4be Save", id="save-search", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-search":
            return
        for field_id, key in [
            ("throttle-delay", "SEARCH_THROTTLE_DELAY"),
            ("max-retries", "SEARCH_MAX_RETRIES"),
            ("blocked-hosts", "BLOCKED_FETCH_HOSTS"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Search Settings Saved")
