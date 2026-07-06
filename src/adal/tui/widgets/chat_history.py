from textual.containers import VerticalScroll
from textual.widgets import Static

PULSE_FRAMES = ["\u25cf\u25cb\u25cb\u25cb", "\u25cb\u25cf\u25cb\u25cb", "\u25cb\u25cb\u25cf\u25cb", "\u25cb\u25cb\u25cb\u25cf"]
AGENT_COLORS = {
    "planner": "$accent",
    "proposer": "$primary-lighten-1",
    "verifier": "$secondary-lighten-1",
    "decision": "$success",
}


class IterationCard(Static):
    def __init__(self, agent: str, iteration: int, detail: str, status: str = "", collapsed: bool = True, **kwargs):
        self._agent = agent.upper()
        self._iteration = iteration
        self._detail = detail
        self._status = status
        self._collapsed = collapsed
        self._reasoning_preview = ""
        self._pulse = 0
        self._pulse_timer = None
        icons = {"planner": "\U0001f9e0", "proposer": "\U0001f52c", "verifier": "\U0001f50d", "decision": "\U0001f3af"}
        self._icon = icons.get(agent, "\u25cf")
        self._color_var = AGENT_COLORS.get(agent, "$text")
        super().__init__("", **kwargs)
        self._write()

    def toggle(self):
        self._collapsed = not self._collapsed
        self._write()

    def set_status(self, status: str, detail: str = ""):
        self._status = status
        if detail:
            self._detail = detail
        self._collapsed = False
        self._stop_pulse()
        self._write()

    def set_reasoning_preview(self, text: str):
        self._reasoning_preview = text[:80]
        self._write()

    def _start_pulse(self):
        if self._pulse_timer is None:
            self._pulse_timer = self.set_interval(0.4, self._pulse_tick)

    def _stop_pulse(self):
        if self._pulse_timer:
            self._pulse_timer.stop()
            self._pulse_timer = None

    def _pulse_tick(self):
        self._pulse = (self._pulse + 1) % len(PULSE_FRAMES)
        self._write()

    def on_click(self):
        self.toggle()

    def _write(self):
        self.update(self._build())

    def _build(self) -> str:
        arrow = "\u25b6" if self._collapsed else "\u25bc"
        cv = self._color_var

        is_thinking = "Thinking" in self._status
        if is_thinking and self._pulse_timer is None:
            self._start_pulse()

        pulse_str = ""
        if is_thinking:
            pulse_str = "  " + PULSE_FRAMES[self._pulse]

        preview = ""
        if self._reasoning_preview:
            preview = f" \u201c[dim italic]{self._reasoning_preview}[/dim italic]\u201d"

        if self._status:
            header = f"[bold {cv}]{arrow} {self._icon} {self._agent}[/bold {cv}] [dim](iter {self._iteration})[/dim] [bold]{self._status}[/bold]{preview}{pulse_str}"
        else:
            header = f"[bold {cv}]{arrow} {self._icon} {self._agent}[/bold {cv}] [dim](iter {self._iteration})[/dim]{preview}"

        lines = [header]
        if not self._collapsed and self._detail:
            lines.append(f"[dim]{self._detail[:500]}[/dim]")
        return "\n".join(lines)


class ChatHistory(VerticalScroll):
    def add_card(self, agent: str, iteration: int, detail: str, status: str = ""):
        card = IterationCard(agent, iteration, detail, status, classes="chat-card")
        self.mount(card)
        self.scroll_end(animate=False)
        return card

    def add_result(self, text: str):
        self.mount(Static(text, classes="chat-result"))
        self.scroll_end(animate=False)

    def add_markdown(self, md: str):
        from textual.widgets import Markdown
        self.mount(Markdown(md, classes="chat-card"))
        self.scroll_end(animate=False)
