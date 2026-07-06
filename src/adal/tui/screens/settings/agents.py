from pathlib import Path

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, TabbedContent, TabPane

from adal.config import settings

ENV_PATH = Path(".env")


def _update_env(key: str, value: str):
    lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line_s = line.strip()
            if line_s and not line_s.startswith("#") and "=" in line_s:
                k, _ = line_s.split("=", 1)
                if k == key:
                    lines.append(f"{key}={value}")
                    found = True
                else:
                    lines.append(line)
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


class AgentSettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="agent-tabs"):
            for agent in ["proposer", "verifier", "planner"]:
                with TabPane(agent.title(), id=f"tab-{agent}"):
                    with VerticalScroll(id=f"scroll-{agent}"):
                        yield Label("[bold]Sampling[/bold]")
                        yield Label("Temperature (0.0–2.0)")
                        yield Input(value=str(getattr(settings, f"{agent}_temperature", "")), id=f"{agent}-temp")
                        yield Label("Top-P (0.0–1.0)")
                        yield Input(value=str(getattr(settings, f"{agent}_top_p", "")), id=f"{agent}-topp")
                        yield Label("Top-K (0 = disabled)")
                        yield Input(value=str(getattr(settings, f"{agent}_top_k", 0)), id=f"{agent}-topk")
                        yield Label("[bold]Penalties[/bold]")
                        yield Label("Frequency Penalty (−2.0 – 2.0)")
                        yield Input(value=str(getattr(settings, f"{agent}_frequency_penalty", "")), id=f"{agent}-freq")
                        yield Label("Presence Penalty (−2.0 – 2.0)")
                        yield Input(value=str(getattr(settings, f"{agent}_presence_penalty", "")), id=f"{agent}-pres")
                        yield Label("[bold]Reproducibility[/bold]")
                        yield Label("Seed (leave empty for random)")
                        val = getattr(settings, f"{agent}_seed", None)
                        yield Input(value=str(val) if val is not None else "", id=f"{agent}-seed")
        with VerticalScroll(id="forced-answer"):
            yield Label("[bold]Fallback[/bold]")
            yield Label("Forced Answer Temperature (0.0–1.0)")
            yield Input(value=str(settings.forced_answer_temperature), id="forced-temp")
        yield Button("\U0001f4be Save", id="save-agent", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-agent":
            return
        for agent in ["proposer", "verifier", "planner"]:
            for suffix, key_base in [
                ("temp", "temperature"), ("topp", "top_p"), ("topk", "top_k"),
                ("freq", "frequency_penalty"), ("pres", "presence_penalty"), ("seed", "seed"),
            ]:
                val = self.query_one(f"#{agent}-{suffix}", Input).value.strip()
                if val:
                    _update_env(f"{agent}_{key_base}", val)
        val = self.query_one("#forced-temp", Input).value.strip()
        if val:
            _update_env("forced_answer_temperature", val)
        self.notify("Saved — restart adal to apply", title="Settings Saved")
