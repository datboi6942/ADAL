from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label

from adal.config import settings
from adal.tui.screens.selectable import SelectableScreen
from adal.tui.screens.settings.agents import _update_env


class PricingSettingsScreen(SelectableScreen):
    DEFAULT_CSS = """
    #pricing-settings {
        height: auto;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="pricing-settings"):
            yield Label("[bold]LLM Pricing[/bold] (per million tokens, for cost tracking)")
            yield Label("Input Price ($)")
            yield Input(value=str(settings.llm_input_price_per_mtok), id="input-price")
            yield Label("Cached Input Price ($)")
            yield Input(value=str(settings.llm_cached_price_per_mtok), id="cached-price")
            yield Label("Output Price ($)")
            yield Input(value=str(settings.llm_output_price_per_mtok), id="output-price")
            yield Button("\U0001f4be Save", id="save-pricing", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id != "save-pricing":
            return
        for field_id, key in [
            ("input-price", "LLM_INPUT_PRICE_PER_MTOK"),
            ("cached-price", "LLM_CACHED_PRICE_PER_MTOK"),
            ("output-price", "LLM_OUTPUT_PRICE_PER_MTOK"),
        ]:
            val = self.query_one(f"#{field_id}", Input).value.strip()
            if val:
                _update_env(key, val)
        self.notify("Saved — restart adal to apply", title="Pricing Saved")
