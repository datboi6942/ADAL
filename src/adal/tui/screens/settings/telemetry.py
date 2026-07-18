from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Switch

from adal.config import settings

ENV_PATH = Path(".env")


def _update_env(key: str, value: str):
    if not ENV_PATH.exists():
        return
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    upper = key.upper()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k.upper() == upper:
                new_lines.append(f"{key}={value}")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class TelemetrySettingsScreen(Screen):
    DEFAULT_CSS = """
    TelemetrySettingsScreen {
        align: center top;
    }
    #telemetry-settings {
        width: 50;
        height: auto;
        padding: 2 3;
        border: thick $primary;
        background: $panel;
    }
    #telemetry-settings Label {
        padding: 0 0 0 2;
    }
    #telemetry-settings Switch {
        margin: 0 0 1 0;
    }
    #telemetry-settings Input {
        margin: 0 0 1 0;
    }
    #telemetry-settings Select {
        margin: 0 0 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="telemetry-settings"):
            yield Label("[bold $accent]\U0001f9e0 Cognitive Telemetry[/bold $accent]")
            yield Label("  [dim]Post-iteration meta-analysis of FSM cognitive health[/dim]")

            yield Label("[bold]Enable Telemetry[/bold]")
            yield Switch(value=settings.telemetry_enabled, id="telemetry-enabled")
            yield Label("  [dim]Runs async sidecar observer after each iteration[/dim]")

            yield Label("Model")
            yield Input(value=settings.telemetry_model, placeholder="deepseek-v4-pro", id="telemetry-model")
            yield Label("  [dim]LLM for meta-cognitive analysis (uses active provider credentials)[/dim]")

            yield Label("Run Interval (iterations)")
            yield Input(value=str(settings.telemetry_interval), placeholder="1", id="telemetry-interval")
            yield Label("  [dim]How often to run the observer (1 = every iteration)[/dim]")

            yield Button("\U0001f4be Save", id="save-telemetry", variant="primary")
            yield Button("\U0001f9e0 View Diagnostics", id="view-diagnostics", variant="default")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save-telemetry":
            enabled = self.query_one("#telemetry-enabled", Switch).value
            model_val = self.query_one("#telemetry-model", Input).value.strip()
            interval = self.query_one("#telemetry-interval", Input).value.strip()

            settings.telemetry_enabled = enabled
            _update_env("TELEMETRY_ENABLED", str(enabled).upper())
            if model_val:
                settings.telemetry_model = model_val
                _update_env("TELEMETRY_MODEL", model_val)
            if interval:
                settings.telemetry_interval = int(interval)
                _update_env("TELEMETRY_INTERVAL", interval)

            self.notify("Saved — restart may be needed for full effect", title="Telemetry Saved")
        elif event.button.id == "view-diagnostics":
            self.app.push_telemetry_dashboard()
