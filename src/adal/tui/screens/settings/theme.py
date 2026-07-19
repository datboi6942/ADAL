from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Label, Select

from adal.tui.screens.selectable import SelectableScreen
from adal.tui.screens.settings.agents import _update_env

THEME_OPTIONS = [
    ("Dark (default)", "textual-dark"),
    ("Light", "textual-light"),
    ("Dracula", "dracula"),
    ("Gruvbox", "gruvbox"),
    ("Nord", "nord"),
    ("Monokai", "monokai"),
    ("Solarized Light", "solarized-light"),
    ("Flexoki", "flexoki"),
]


class ThemeSettingsScreen(SelectableScreen):
    DEFAULT_CSS = """
    #theme-settings {
        height: auto;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="theme-settings"):
            yield Label("Select a theme:")
            yield Select(
                THEME_OPTIONS,
                value=self.app.theme if self.app.theme in dict(THEME_OPTIONS).values() else "textual-dark",
                id="theme-select",
                allow_blank=False,
            )
            yield Label("[dim]Theme changes apply immediately. Save to make it your default.[/dim]")
            yield Button("\U0001f4be Save as Default", id="save-theme", variant="primary")
        yield Footer()

    def on_mount(self):
        select = self.query_one("#theme-select", Select)
        select.value = self.app.theme

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "theme-select" and event.value:
            self.app.theme = str(event.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-theme":
            return
        val = self.query_one("#theme-select", Select).value
        if val:
            _update_env("ADAL_THEME", str(val))
        self.notify("Saved — restart adal to apply as default", title="Theme Saved")
