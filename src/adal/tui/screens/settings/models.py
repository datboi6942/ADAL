from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select

from adal.config import settings
from adal.tui.screens.settings.agents import _update_env

PROVIDER_DEFAULTS = {
    "deepseek": {"model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/v1"},
    "openai": {"model": "gpt-4o", "base_url": ""},
    "openrouter": {"model": "", "base_url": ""},
    "ollama": {"model": "llama3.1", "base_url": "http://localhost:11434/v1"},
    "custom": {"model": "", "base_url": ""},
}

PROVIDER_KEYS = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL"),
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", ""),
    "ollama": ("OLLAMA_API_KEY", "OLLAMA_MODEL", "OLLAMA_BASE_URL"),
    "custom": ("CUSTOM_API_KEY", "CUSTOM_MODEL", "CUSTOM_BASE_URL"),
}

ATTR_MAP = {
    "deepseek": ("deepseek_api_key", "deepseek_model", "deepseek_base_url"),
    "openai": ("openai_api_key", "openai_model", ""),
    "openrouter": ("openrouter_api_key", "openrouter_model", ""),
    "ollama": ("", "ollama_model", "ollama_base_url"),
    "custom": ("custom_api_key", "custom_model", "custom_base_url"),
}


class ModelSettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="model-settings"):
            yield Label("Provider")
            yield Select(
                [("DeepSeek", "deepseek"), ("OpenAI", "openai"),
                 ("OpenRouter", "openrouter"), ("Ollama", "ollama"), ("Custom", "custom")],
                value=settings.llm_provider,
                id="provider-select",
            )
            yield Label("API Key")
            yield Input(placeholder="sk-...", id="api-key", password=True)
            yield Label("Model Name")
            yield Input(placeholder="deepseek-v4-pro", id="model-name")
            yield Label("Base URL")
            yield Input(placeholder="https://api.deepseek.com/v1", id="base-url")
            yield Label("Max Tokens")
            yield Input(value=str(settings.llm_max_tokens), placeholder="65536", id="max-tokens")
        yield Label("Reasoning Effort (DeepSeek only)")
        yield Select(
            [("max", "max"), ("high", "high"), ("medium", "medium"), ("low", "low")],
            value=settings.reasoning_effort,
            id="reasoning-effort",
        )

        yield Label("[bold]Sub-Agent Models[/bold]")
        yield Label("  [dim]Cheaper models for internal verification, critique, retry calls[/dim]")
        yield Label("DeepSeek Sub-Model")
        yield Input(value=settings.deepseek_sub_model, placeholder="deepseek-v4-chat", id="deepseek-sub")
        yield Label("OpenAI Sub-Model")
        yield Input(value=settings.openai_sub_model, placeholder="gpt-4o-mini", id="openai-sub")
        yield Label("OpenRouter Sub-Model")
        yield Input(value=settings.openrouter_sub_model, placeholder="", id="openrouter-sub")
        yield Label("Ollama Sub-Model")
        yield Input(value=settings.ollama_sub_model, placeholder="", id="ollama-sub")
        yield Label("Custom Sub-Model")
        yield Input(value=settings.custom_sub_model, placeholder="", id="custom-sub")

        yield Button("\U0001f4be Save", id="save-model", variant="primary")
        yield Footer()

    def on_mount(self):
        self._fill_provider_fields()

    def on_select_changed(self, event: Select.Changed):
        if event.select.id == "provider-select" and event.value:
            self._fill_provider_fields()

    def _fill_provider_fields(self):
        prov = self.query_one("#provider-select", Select).value
        prov = str(prov).lower() if prov else "deepseek"
        defaults = PROVIDER_DEFAULTS.get(prov, {})
        attrs = ATTR_MAP.get(prov, ("", "", ""))

        model_inp = self.query_one("#model-name", Input)
        url_inp = self.query_one("#base-url", Input)
        key_inp = self.query_one("#api-key", Input)

        key_attr = attrs[0]
        model_attr = attrs[1]
        url_attr = attrs[2]

        if key_attr:
            key_inp.value = str(getattr(settings, key_attr, ""))
        else:
            key_inp.value = ""
        key_inp.placeholder = "sk-..."

        if model_attr:
            model_val = getattr(settings, model_attr, "")
            model_inp.value = str(model_val) if model_val else ""
        else:
            model_inp.value = ""
        model_inp.placeholder = defaults.get("model", "")

        if url_attr:
            url_val = getattr(settings, url_attr, "")
            url_inp.value = str(url_val) if url_val else ""
        else:
            url_inp.value = ""
        url_inp.placeholder = defaults.get("base_url", "")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-model":
            return
        provider = self.query_one("#provider-select", Select).value
        if provider:
            _update_env("LLM_PROVIDER", str(provider))
        prov = str(provider).lower() if provider else ""
        key_map = {"deepseek": "DEEPSEEK_API_KEY", "openai": "OPENAI_API_KEY",
                   "openrouter": "OPENROUTER_API_KEY", "ollama": "OLLAMA_API_KEY",
                   "custom": "CUSTOM_API_KEY"}
        base_url_map = {"deepseek": "DEEPSEEK_BASE_URL", "ollama": "OLLAMA_BASE_URL",
                        "openai": "OPENAI_BASE_URL", "custom": "CUSTOM_BASE_URL"}
        model_map = {"deepseek": "DEEPSEEK_MODEL", "openai": "OPENAI_MODEL",
                     "openrouter": "OPENROUTER_MODEL", "ollama": "OLLAMA_MODEL",
                     "custom": "CUSTOM_MODEL"}
        for field_id, key in [("api-key", key_map.get(prov, "")), ("model-name", model_map.get(prov, "")),
                               ("base-url", base_url_map.get(prov, "")), ("max-tokens", "LLM_MAX_TOKENS")]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val and key:
                _update_env(key, val)
        reasoning = self.query_one("#reasoning-effort", Select).value
        if reasoning:
            _update_env("REASONING_EFFORT", str(reasoning))
        for field_id, key in [
            ("deepseek-sub", "DEEPSEEK_SUB_MODEL"),
            ("openai-sub", "OPENAI_SUB_MODEL"),
            ("openrouter-sub", "OPENROUTER_SUB_MODEL"),
            ("ollama-sub", "OLLAMA_SUB_MODEL"),
            ("custom-sub", "CUSTOM_SUB_MODEL"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Settings Saved")
