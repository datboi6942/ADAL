from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, Switch

ENV_PATH = Path(".env")

PROVIDER_INFO = {
    "deepseek": "DeepSeek V4 Pro — reasoning-enabled LLM. Requires DEEPSEEK_API_KEY.",
    "openai": "OpenAI GPT-4o and o-series. Requires OPENAI_API_KEY.",
    "openrouter": "OpenRouter — access any model through one API. Requires OPENROUTER_API_KEY.\nModel format: provider/model (e.g., deepseek/deepseek-v4-pro, anthropic/claude-sonnet-4-6)",
    "ollama": "Local LLM via Ollama. No API key needed. Requires Ollama running locally.",
    "custom": "Custom OpenAI-compatible endpoint. Requires base URL and optional API key.",
}

PROVIDER_DEFAULTS = {
    "deepseek": {"model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1", "api_key": True},
    "openai": {"model": "gpt-4o", "base_url": "", "api_key": True},
    "openrouter": {"model": "", "base_url": "", "api_key": True},
    "ollama": {"model": "", "base_url": "http://localhost:11434/v1", "api_key": False},
    "custom": {"model": "", "base_url": "", "api_key": True},
}


class ProviderScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield Label("ADAL Setup", classes="title")
            yield Label("Choose your LLM provider:", classes="subtitle")
            yield Select(
                [("DeepSeek", "deepseek"), ("OpenAI", "openai"),
                 ("OpenRouter", "openrouter"), ("Ollama (local)", "ollama"),
                 ("Custom Endpoint", "custom")],
                prompt="Select provider...",
                id="provider_select",
            )
            yield Static(id="provider_info", classes="info")
            with Horizontal(id="buttons"):
                yield Button("Continue →", id="next", variant="primary")
                yield Button("Quit", id="quit", variant="error")
        yield Footer()

    def on_mount(self):
        self.query_one(Button).focus()
        self._show_info()

    def on_select_changed(self):
        self._show_info()

    def _show_info(self):
        select = self.query_one("#provider_select", Select)
        info = PROVIDER_INFO.get(select.value or "deepseek", "")
        self.query_one("#provider_info", Static).update(info)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "next":
            select = self.query_one("#provider_select", Select)
            if not select.value:
                self.notify("Please select a provider", severity="warning")
                return
            app = self.app
            app.provider = select.value if hasattr(select, 'value') else "deepseek"
            app.push_screen(CredentialsScreen())
        elif event.button.id == "quit":
            self.app.exit()


class CredentialsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Label("Credentials", classes="title")
            yield Label(id="provider_label", classes="subtitle")
            yield Input(placeholder="API Key (sk-...)", id="api_key", password=True)
            yield Input(placeholder="Model name", id="model")
            yield Input(placeholder="Base URL", id="base_url")
            yield Switch(value=True, id="thinking_switch")
            yield Label("Reasoning/Thinking Mode")
            with Horizontal(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    def on_mount(self):
        app = self.app
        p = app.provider
        defaults = PROVIDER_DEFAULTS.get(p, {})
        self.query_one("#provider_label", Label).update(f"Provider: {p.title()} — {PROVIDER_INFO.get(p, '')}")
        self.query_one("#model", Input).value = defaults.get("model", "")
        self.query_one("#base_url", Input).value = defaults.get("base_url", "")
        if not defaults.get("api_key", True):
            self.query_one("#api_key", Input).value = "ollama"
            self.query_one("#api_key", Input).disabled = True
        self.query_one("#thinking_switch", Switch).display = (p == "deepseek")
        self.query_one(Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "next":
            app = self.app
            app.api_key = self.query_one("#api_key", Input).value.strip()
            app.model = self.query_one("#model", Input).value.strip()
            app.base_url = self.query_one("#base_url", Input).value.strip()
            app.thinking = self.query_one("#thinking_switch", Switch).value
            app.push_screen(ReviewScreen())
        elif event.button.id == "back":
            self.app.pop_screen()


class ReviewScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Label("Review & Save", classes="title")
            yield Label(f"Will write to: {ENV_PATH}", classes="subtitle")
            yield Static(id="preview", classes="preview")
            with Horizontal(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("💾 Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel", variant="error")
        yield Footer()

    def on_mount(self):
        app = self.app
        p = app.provider
        lines = [f"LLM_PROVIDER={p}"]
        if p == "deepseek":
            lines.append(f"DEEPSEEK_API_KEY={app.api_key}")
            lines.append(f"DEEPSEEK_BASE_URL={app.base_url or PROVIDER_DEFAULTS[p]['base_url']}")
            lines.append(f"DEEPSEEK_MODEL={app.model or PROVIDER_DEFAULTS[p]['model']}")
            lines.append("REASONING_EFFORT=max")
        elif p == "openai":
            lines.append(f"OPENAI_API_KEY={app.api_key}")
            if app.model:
                lines.append(f"LLM_MODEL={app.model}")
            if app.base_url:
                lines.append(f"CUSTOM_BASE_URL={app.base_url}")
        elif p == "openrouter":
            lines.append(f"OPENROUTER_API_KEY={app.api_key}")
            if app.model:
                lines.append(f"LLM_MODEL={app.model}")
        elif p == "ollama":
            if app.base_url != "http://localhost:11434/v1":
                lines.append(f"OLLAMA_BASE_URL={app.base_url}")
            if app.model:
                lines.append(f"OLLAMA_MODEL={app.model}")
        elif p == "custom":
            lines.append(f"CUSTOM_API_KEY={app.api_key}")
            lines.append(f"CUSTOM_BASE_URL={app.base_url}")
            if app.model:
                lines.append(f"CUSTOM_MODEL={app.model}")
        lines.extend([
            "LLM_MAX_TOKENS=65536",
        ])
        self.query_one("#preview", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save":
            self._save()
            self.app.exit()
        elif event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "cancel":
            self.app.exit()

    def _save(self):
        app = self.app
        p = app.provider
        lines = []
        existing = {}
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k] = line

        lines.append(f"LLM_PROVIDER={p}")
        if p == "deepseek":
            lines.append(f"DEEPSEEK_API_KEY={app.api_key}")
            lines.append(f"DEEPSEEK_BASE_URL={app.base_url or PROVIDER_DEFAULTS[p]['base_url']}")
            lines.append(f"DEEPSEEK_MODEL={app.model or PROVIDER_DEFAULTS[p]['model']}")
        elif p == "openai":
            lines.append(f"OPENAI_API_KEY={app.api_key}")
            if app.model:
                lines.append(f"LLM_MODEL={app.model}")
        elif p == "openrouter":
            lines.append(f"OPENROUTER_API_KEY={app.api_key}")
            if app.model:
                lines.append(f"LLM_MODEL={app.model}")
        elif p == "ollama":
            if app.model:
                lines.append(f"OLLAMA_MODEL={app.model}")
            if app.base_url != "http://localhost:11434/v1":
                lines.append(f"OLLAMA_BASE_URL={app.base_url}")
        elif p == "custom":
            lines.append(f"CUSTOM_API_KEY={app.api_key}")
            lines.append(f"CUSTOM_BASE_URL={app.base_url}")
            if app.model:
                lines.append(f"CUSTOM_MODEL={app.model}")

        for k in ["DATABASE_URL", "MAX_ITERATIONS", "SANDBOX_TIMEOUT", "LOG_LEVEL",
                   "LLM_MAX_TOKENS", "LLM_INPUT_PRICE_PER_MTOK", "LLM_CACHED_PRICE_PER_MTOK",
                   "LLM_OUTPUT_PRICE_PER_MTOK", "OPENAI_API_KEY", "OPENAI_EMBEDDING_MODEL",
                   "MEMORY_ENABLED", "MEMORY_DB_PATH", "MEMORY_MAX_EPISODIC",
                   "MEMORY_MAX_GLOBAL", "MEMORY_PRUNE_THRESHOLD",
                   "PROPOSER_TEMPERATURE", "VERIFIER_TEMPERATURE", "PLANNER_TEMPERATURE",
                   "FORCED_ANSWER_TEMPERATURE"]:
            if k in existing and k not in lines:
                lines.append(existing[k])

        if "LLM_MAX_TOKENS" not in [line.split("=")[0] for line in lines]:
            lines.append("LLM_MAX_TOKENS=65536")

        ENV_PATH.write_text("\n".join(lines) + "\n")
        self.notify(f"Saved to {ENV_PATH}", title="Success")


class SetupApp(App):
    CSS = """
    #main {
        padding: 1 2;
        height: auto;
    }
    .title {
        text-style: bold;
        color: $accent;
        content-align: center middle;
        padding: 0 0 1 0;
    }
    .subtitle {
        padding: 0 0 1 0;
    }
    .info {
        padding: 1 0;
        color: $text-muted;
        height: auto;
    }
    .preview {
        padding: 1;
        background: $surface;
        border: solid $primary;
        height: auto;
    }
    #buttons {
        padding: 1 0;
        align: center middle;
    }
    Button {
        margin: 0 1;
    }
    Input {
        margin: 0 0 1 0;
    }
    Select {
        margin: 0 0 1 0;
    }
    Switch {
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "pop_screen", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self.provider = "deepseek"
        self.api_key = ""
        self.model = ""
        self.base_url = ""
        self.thinking = True

    def on_mount(self):
        self.push_screen(ProviderScreen())


def run_setup():
    app = SetupApp()
    app.run()
