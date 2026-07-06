from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static


class SettingsHubScreen(Screen):
    DEFAULT_CSS = """
    SettingsHubScreen {
        align: center middle;
    }
    #settings-hub {
        width: 44;
        height: auto;
        padding: 2 3;
        border: thick $primary;
        background: $panel;
    }
    #settings-hub Button {
        width: 100%;
        margin: 1 0;
    }
    """

    CATEGORIES = [
        ("\U0001f9e0  Agent Generation Params", "agents", "primary",
         "Temperature, Top-P, Top-K, penalties, seed"),
        ("\U0001f916  Model & Provider", "models", "primary",
         "LLM provider, API key, model name, max tokens"),
        ("\U0001f504  Loop Control", "loop", "default",
         "Tool turns, retry count, pivot threshold"),
        ("\U0001f9e0  Vector Memory", "memory", "default",
         "LanceDB path, embeddings, prune threshold"),
        ("\U0001f50d  Web Search", "search", "default",
         "Throttle delay, retries, blocked hosts"),
        ("\u2699\ufe0f  General", "general", "default",
         "Log level, database URL"),
        ("\U0001f3a8  Theme", "theme", "default",
         "Pick from 8 color themes"),
        ("\U0001f4b0  Pricing", "pricing", "default",
         "Per-token LLM cost tracking"),
        ("\U0001f527  Advanced", "advanced", "default",
         "Iterations, sandbox, memory tuning, search tuning"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="settings-hub"):
            yield Static("[bold $accent]Settings[/bold $accent]", id="hub-title")
            for label, key, variant, desc in self.CATEGORIES:
                yield Button(f"{label}\n  [dim italic]{desc}[/dim italic]", id=f"hub-{key}", variant=variant)
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("hub-"):
            category = bid[4:]
            self.app.push_settings(category)
