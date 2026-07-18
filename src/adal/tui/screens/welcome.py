from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from adal import __version__

LOGO = """\
[bold $accent]   █████╗ ██████╗  █████╗ ██╗
   ██╔══██╗██╔══██╗██╔══██╗██║
   ███████║██║  ██║███████║██║
   ██╔══██║██║  ██║██╔══██║██║
   ██║  ██║██████╔╝██║  ██║███████╗
   ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚══════╝[/bold $accent]"""


class WelcomeScreen(Screen):
    BINDINGS = [
        Binding("up", "focus_previous", "Previous", show=False),
        Binding("down", "focus_next", "Next", show=False),
        Binding("tab", "focus_next", show=False),
        Binding("shift+tab", "focus_previous", show=False),
    ]

    def action_focus_next(self):
        self.focus_next()

    def action_focus_previous(self):
        self.focus_previous()

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center middle;
        background: $surface;
    }
    #welcome-box {
        width: 56;
        height: auto;
        padding: 2 3;
        border: thick $primary;
        background: $panel;
        border-title-color: $primary;
        border-title-style: bold;
        transition: border-title-color 1.5s in_out_cubic;
    }
    #welcome-logo {
        width: 100%;
        height: auto;
        content-align: center middle;
        padding-bottom: 1;
        opacity: 0;
        transition: opacity 0.5s in_cubic;
    }
    #welcome-logo.visible {
        opacity: 1;
    }
    #welcome-subtitle {
        width: 100%;
        content-align: center middle;
        padding-bottom: 1;
        color: $text-muted;
        text-style: italic;
        opacity: 0;
        transition: opacity 0.5s in_cubic;
    }
    #welcome-subtitle.visible {
        opacity: 1;
    }
    #welcome-buttons {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 1 0;
        opacity: 0;
        transition: opacity 0.5s in_cubic;
    }
    #welcome-buttons.visible {
        opacity: 1;
    }
    #welcome-buttons Button {
        width: 40;
        margin: 1 0;
    }
    #btn-new-session {
        background: $accent 30%;
        transition: background 0.3s in_out_cubic;
    }
    #btn-new-session:hover {
        background: $accent 50%;
    }
    #welcome-footer {
        width: 100%;
        content-align: center middle;
        padding-top: 1;
        color: $text-disabled;
        opacity: 0;
        transition: opacity 0.5s in_cubic;
    }
    #welcome-footer.visible {
        opacity: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Container(id="welcome-box"):
            yield Static(LOGO, id="welcome-logo")
            yield Static(
                "[bold]A[/bold]utonomous [bold]D[/bold]iscovery [bold]&[/bold] [bold]A[/bold]nalysis [bold]L[/bold]ab\n"
                "Multi-Agent Scientific Research System",
                id="welcome-subtitle",
            )
            with Vertical(id="welcome-buttons"):
                yield Button("\U0001f52c  New Research Session", id="btn-new-session", variant="primary")
                yield Button("\U0001f4da  Browse Library", id="btn-library")
                yield Button("\U0001f4cb  Past Sessions", id="btn-history")
                yield Button("\u2699\ufe0f  Settings", id="btn-settings")
            yield Static(
                f"ADAL v{__version__}  \u2022  "
                "[bold $accent italic]L[/bold $accent italic] Ctrl+D theme  "
                "\u2022  F2 commands  \u2022  / for slash commands  \u2022  Q quit",
                id="welcome-footer",
            )
        yield Footer()

    def on_mount(self):
        self.call_after_refresh(self._on_first_layout)

    def _on_first_layout(self):
        self.query_one("#btn-new-session", Button).focus()
        self._animate_entrance()
        self._start_border_glow()

    def _animate_entrance(self):
        self.set_timer(0.1, lambda: self.query_one("#welcome-logo").add_class("visible"))
        self.set_timer(0.3, lambda: self.query_one("#welcome-subtitle").add_class("visible"))
        self.set_timer(0.5, lambda: self.query_one("#welcome-buttons").add_class("visible"))
        self.set_timer(0.7, lambda: self.query_one("#welcome-footer").add_class("visible"))
        self.set_timer(0.8, lambda: self.query_one("#welcome-buttons").refresh(layout=True))

    def _start_border_glow(self):
        self._glow_phase = 0
        self._glow_colors = ["cyan", "magenta", "green", "blue", "cyan"]
        self._glow_timer = self.set_interval(2.0, self._glow_tick)

    def _glow_tick(self):
        self._glow_phase = (self._glow_phase + 1) % len(self._glow_colors)
        box = self.query_one("#welcome-box")
        box.styles.border_title_color = self._glow_colors[self._glow_phase]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-new-session":
            from adal.tui.screens.dashboard import DashboardScreen
            self.app.push_screen(DashboardScreen())
        elif bid == "btn-library":
            self.app.push_library()
        elif bid == "btn-history":
            self.app.push_history()
        elif bid == "btn-settings":
            from adal.tui.screens.settings.hub import SettingsHubScreen
            self.app.push_screen(SettingsHubScreen())
