from textual.widgets import RichLog


class ReasoningLog(RichLog):
    AGENT_COLORS = {"PLANNER": "yellow", "PROPOSER": "cyan", "VERIFIER": "magenta"}

    def __init__(self, **kwargs):
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self.auto_scroll = True

    def append_reasoning(self, name: str, text: str):
        color = self.AGENT_COLORS.get(name, "white")
        prefix = f"[bold {color}]\U0001f4ad {name}[/bold {color}] "

        if hasattr(self, "scroll_offset") and hasattr(self, "max_scroll_y"):
            at_bottom = self.scroll_offset.y + self.size.height >= self.max_scroll_y - 2
        else:
            at_bottom = True

        self.auto_scroll = at_bottom
        self.write(prefix + text[:3000])
