from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Switch

from adal.config import settings
from adal.tui.screens.settings.agents import _update_env


class MemorySettingsScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="memory-settings"):
            yield Label("Memory Enabled")
            yield Switch(value=settings.memory_enabled, id="mem-enabled")
            yield Label("Database Path")
            yield Input(value=settings.memory_db_path, placeholder="./memory_vault.lance", id="mem-path")
            yield Label("OpenAI API Key (for embeddings)")
            yield Input(value=settings.openai_api_key, placeholder="sk-...", id="openai-key", password=True)
            yield Label("Embedding Model")
            yield Input(value=settings.openai_embedding_model, placeholder="text-embedding-3-small", id="embed-model")
            yield Label("Prune Threshold (0.5–1.0)")
            yield Input(value=str(settings.memory_prune_threshold), placeholder="0.85", id="prune-threshold")
            yield Label("Max Episodic Memories")
            yield Input(value=str(settings.memory_max_episodic), placeholder="5", id="max-episodic")
            yield Label("Max Global Lessons")
            yield Input(value=str(settings.memory_max_global), placeholder="3", id="max-global")
            yield Label("  [dim]Stored cross-session lessons[/dim]")
            yield Label("Context Cap")
            yield Input(value=str(settings.memory_enrich_context_cap), placeholder="3", id="context-cap")
            yield Label("  [dim]Max memories injected per agent prompt[/dim]")
            yield Button("\U0001f4be Save", id="save-mem", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-mem":
            return
        enabled = self.query_one("#mem-enabled", Switch).value
        _update_env("MEMORY_ENABLED", "true" if enabled else "false")
        for field_id, key in [
            ("mem-path", "MEMORY_DB_PATH"), ("openai-key", "OPENAI_API_KEY"),
            ("embed-model", "OPENAI_EMBEDDING_MODEL"),
            ("prune-threshold", "MEMORY_PRUNE_THRESHOLD"), ("max-episodic", "MEMORY_MAX_EPISODIC"),
            ("max-global", "MEMORY_MAX_GLOBAL"), ("context-cap", "MEMORY_ENRICH_CONTEXT_CAP"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Settings Saved")
