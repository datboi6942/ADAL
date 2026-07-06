from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label

from adal.config import settings
from adal.tui.screens.settings.agents import _update_env


class GeneralSettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="general-settings"):
            yield Label("[bold]Application[/bold]")
            yield Label("Log Level")
            yield Input(value=settings.log_level, placeholder="INFO", id="log-level")
            yield Label("  [dim]DEBUG, INFO, WARNING, or ERROR[/dim]")
            yield Label("Database URL")
            yield Input(value=settings.database_url, placeholder="sqlite+aiosqlite:///adal.db", id="db-url")
            yield Label("  [dim]SQLAlchemy connection string[/dim]")
            yield Button("\U0001f4be Save", id="save-general", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-general":
            return
        for field_id, key in [
            ("log-level", "LOG_LEVEL"), ("db-url", "DATABASE_URL"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Settings Saved")
