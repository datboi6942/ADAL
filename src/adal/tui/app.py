from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Markdown, Static

from adal.config import settings
from adal.tui.screens.dashboard import DashboardScreen
from adal.tui.screens.history import HistoryScreen
from adal.tui.screens.library import LibraryScreen
from adal.tui.screens.session_detail import SessionDetailScreen
from adal.tui.screens.settings.advanced import AdvancedSettingsScreen
from adal.tui.screens.settings.agents import AgentSettingsScreen
from adal.tui.screens.settings.general import GeneralSettingsScreen
from adal.tui.screens.settings.hub import SettingsHubScreen
from adal.tui.screens.settings.loop import LoopSettingsScreen
from adal.tui.screens.settings.memory import MemorySettingsScreen
from adal.tui.screens.settings.models import ModelSettingsScreen
from adal.tui.screens.settings.pricing import PricingSettingsScreen
from adal.tui.screens.settings.search import SearchSettingsScreen
from adal.tui.screens.settings.theme import ThemeSettingsScreen
from adal.tui.screens.telemetry_dashboard import TelemetryDashboardScreen
from adal.tui.screens.welcome import WelcomeScreen
from adal.tui.widgets.palette import ADALProvider

HELP_TEXT = """\
# ADAL — Keybindings

| Key | Action |
|-----|--------|
| `F1` | This help screen |
| `F2` | Command palette (search all actions) |
| `F5` | Stop current research run |
| `F9` | Go back to previous screen |
| `Ctrl+D` | Cycle through 9 themes |
| `Ctrl+,` | Open agent settings |
| `Q` | Quit ADAL |

## Navigation
Press **F2** to open the command palette, then type to search:
- **Settings** — configure agents, models, memory, search, general
- **History** — view past research sessions
- **Library** — browse validated synthesis procedures
- **New Session** — start a fresh research session

## Slash Commands
Type `/` in the query input for command suggestions:
- `/help` — show commands
- `/verbose` — toggle detailed output
- `/theme <name>` — change theme
- `/stop` — stop current run
"""

THEMES = [
    "textual-dark",
    "textual-light",
    "dracula",
    "gruvbox",
    "nord",
    "monokai",
    "solarized-light",
    "flexoki",
]


class HelpScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-container {
        width: 62;
        max-height: 35;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-container"):
            yield Markdown(HELP_TEXT)
            yield Static("Press any key to close", classes="dim")

    def on_key(self):
        self.dismiss()


class ADALApp(App):
    COMMANDS = {ADALProvider}
    CSS = """
    .agent-planner { color: $accent; }
    .agent-proposer { color: $primary-lighten-1; }
    .agent-verifier { color: $secondary-lighten-1; }
    .agent-decision { color: $success; }

    Screen {
        align: center top;
    }

    DashboardScreen {
        layout: grid;
        grid-rows: 1fr auto 1 auto;
        grid-columns: 1fr;
    }
    DashboardScreen.debug-max {
        grid-rows: 0 auto 1 1fr;
    }
    SessionDetailScreen {
        layout: grid;
        grid-rows: 1fr auto 1 auto;
        grid-columns: 1fr;
    }
    SessionDetailScreen.debug-max {
        grid-rows: 0 auto 1 1fr;
    }

    #chat-history {
        height: 1fr;
        padding: 0 2;
    }
    .chat-card {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        border-left: solid $primary-darken-1;
        border-top: none;
        border-bottom: none;
        border-right: none;
        transition: border-left 0.3s in_out_cubic, opacity 0.3s in_out_cubic;
    }
    .chat-card:hover {
        border-left: solid $primary-lighten-1;
    }
    .chat-card.pulse-0 {
        border-left: solid $accent;
    }
    .chat-card.pulse-1 {
        border-left: solid $primary-lighten-1;
    }
    .chat-card.pulse-2 {
        border-left: solid $secondary-lighten-1;
    }
    .chat-card.pulse-3 {
        border-left: solid $primary-darken-1;
    }
    .chat-result {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
    }
    .result-actions {
        height: auto;
        padding: 1 2;
        margin: 0 0 2 0;
        align: center middle;
        layout: horizontal;
    }
    .result-actions Button {
        margin: 0 1;
    }
    #continue-research {
        background: $accent;
        color: $text;
    }
    #query-area {
        height: auto;
        margin: 0 2 1 2;
        background: $surface;
        border: solid $primary;
        transition: border 0.3s in_out_cubic;
    }
    #query-area:focus-within {
        border: solid $accent;
    }
    #query-input {
        height: auto;
        min-height: 3;
        max-height: 8;
        background: $surface;
        border: none;
    }
    #query-input:focus-within {
        border: none;
    }
    #suggestion-list {
        height: auto;
        max-height: 14;
        background: $surface-darken-1;
        padding: 0 1;
        border-top: solid $primary-darken-1;
        display: none;
    }
    #suggestion-list.visible {
        display: block;
    }
    .suggestion-row {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    .suggestion-row.selected {
        background: $accent 20%;
        color: $text;
    }
    .suggestion-cmd {
        color: $accent;
    }
    .suggestion-desc {
        color: $text-muted;
        padding-left: 2;
    }
    #status-line {
        height: 1;
        margin: 0 2 0 2;
        padding: 0 1;
        background: $surface;
        overflow: hidden;
    }
    #status-line.idle {
        background: $surface;
    }
    #status-line.running {
        background: $warning 10%;
    }
    #status-line.done {
        background: $success 10%;
    }
    #status-line.error-state {
        background: $error 10%;
    }
    #status-text {
        height: 1;
        width: 1fr;
        min-width: 20;
    }
    .status-btn {
        min-width: 13;
        min-height: 1;
        height: 1;
        padding: 0 1;
    }
    #verbose-btn.active {
        background: $accent 20%;
        color: $accent;
    }
    .debug-panel {
        display: none;
    }
    .debug-panel.visible {
        display: block;
        height: auto;
        min-height: 6;
        max-height: 14;
        border-top: solid $primary;
        background: $surface-darken-1;
    }
    .debug-panel.visible.maximized {
        height: 1fr;
        min-height: 0;
        max-height: 100%;
    }
    #debug-log {
        height: 100%;
        min-height: 4;
        padding: 0 1;
    }
    .debug-panel.maximized #debug-log {
        min-height: 0;
    }
    #debug-header {
        height: 1;
        background: $primary 20%;
        color: $primary;
        padding: 0 1;
        text-style: bold;
    }
    #detail-content, #library-content,
    #model-settings, #memory-settings, #search-settings, #general-settings,
    #loop-settings, #advanced-settings,
    #library-results, #agent-tabs {
        height: auto;
        padding: 1 2;
    }
    #domain-filter {
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("f1", "help", "Help"),
        Binding("f2", "command_palette", "Commands"),
        Binding("f5", "stop", "Stop"),
        Binding("f9", "back", "Back"),
        Binding("ctrl+d", "toggle_theme", "Theme", priority=True),
        Binding("ctrl+comma", "settings", "Settings"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self._sidebar_visible = True

    def compose(self) -> ComposeResult:
        yield Footer()

    def on_mount(self):
        if settings.adal_theme and settings.adal_theme in THEMES:
            self.theme = settings.adal_theme
        self.push_screen(WelcomeScreen())

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_toggle_theme(self):
        try:
            idx = THEMES.index(self.theme)
        except ValueError:
            idx = -1
        next_theme = THEMES[(idx + 1) % len(THEMES)]
        self.theme = next_theme

    def action_settings(self):
        self.push_screen(SettingsHubScreen())

    def _handle_palette(self, action: str):
        if action == "new":
            self.push_screen(DashboardScreen())
        elif action == "history":
            self.push_history()
        elif action == "library":
            self.push_library()
        elif action == "quit":
            self.exit()
        elif action == "export":
            self.notify("Use Export button after a run completes", title="Export")
        elif action == "toggle_theme":
            self.action_toggle_theme()
        elif action.startswith("settings_"):
            self.push_settings(action.replace("settings_", ""))
        elif action == "delete":
            self.notify("Delete not yet implemented", title="Session")
        elif action == "telemetry":
            self.push_telemetry_dashboard()

    def push_settings(self, name: str):
        screens = {
            "agents": AgentSettingsScreen,
            "models": ModelSettingsScreen,
            "loop": LoopSettingsScreen,
            "memory": MemorySettingsScreen,
            "search": SearchSettingsScreen,
            "general": GeneralSettingsScreen,
            "theme": ThemeSettingsScreen,
            "pricing": PricingSettingsScreen,
            "advanced": AdvancedSettingsScreen,
        }
        cls = screens.get(name)
        if cls:
            self.push_screen(cls())

    def push_session_detail(self, session_id: str):
        self.push_screen(SessionDetailScreen(session_id))

    def push_library(self, domain: str | None = None):
        self.push_screen(LibraryScreen(domain))

    def push_history(self):
        self.push_screen(HistoryScreen())

    def push_telemetry_dashboard(self):
        self.push_screen(TelemetryDashboardScreen())

    def action_stop(self):
        screen = self.screen
        if hasattr(screen, "_worker") and screen._worker:
            screen._worker.stop()
            screen._query_running = False
            if hasattr(screen, "_stop_status_animation"):
                screen._stop_status_animation()
            qi = screen.query_one("#query-input")
            qi.disabled = False
            qi.focus()

    def action_back(self):
        if len(self._screen_stack) > 1:
            self.pop_screen()

    def action_save(self):
        self.notify("Use Settings to configure", title="Save")
