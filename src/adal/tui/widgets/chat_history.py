import random as _random_module

from textual.containers import VerticalScroll
from textual.widgets import Static

CONFETTI_CHARS = ["\u2728", "\u2726", "\u2747", "\u2731", "\u25c6", "\u25c8", "\u2727", "\u2b25"]
SHAKE_OFFSETS = [3, -2, 2, -1, 1, -1, 0, 0]
PULSE_CLASSES = ["pulse-0", "pulse-1", "pulse-2", "pulse-3"]
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
        self._reasoning_full = ""
        self._pulse = 0
        self._pulse_timer = None
        self._fade_timer = None
        self._confetti_frames: list[str] = []
        self._confetti_idx = 0
        self._confetti_timer = None
        self._shake_idx = 0
        self._shake_timer = None
        self._tool_calls: list[tuple[str, str]] = []
        self._verbose = False
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
        self._reasoning_full = text
        self._write()

    def set_verbose(self, verbose: bool):
        self._verbose = verbose
        self._write()

    def add_tool_call(self, tool_name: str, preview: str):
        self._tool_calls.append((tool_name, preview[:200]))
        if self._verbose:
            self._write()

    def celebrate(self):
        _random_module.seed(42 + (self._iteration or 0) * 137)
        self._confetti_frames = []
        colors = ["bold $accent", "bold $primary", "bold $secondary", "bold $success", "bold $warning"]

        for _ in range(12):
            rows = []
            for _ in range(3):
                line = ""
                for _ in range(25):
                    c = _random_module.choice(CONFETTI_CHARS)
                    col = _random_module.choice(colors)
                    pad = " " * _random_module.randint(0, 2)
                    line += f"{pad}[{col}]{c}[/{col}]"
                rows.append(line)
            self._confetti_frames.append("\n".join(rows))
        self._confetti_idx = 0
        self._confetti_base = self._build()
        self._confetti_timer = self.set_interval(0.08, self._confetti_tick)

    def shake(self):
        self._shake_idx = 0
        self.styles.color = "$error"
        self._shake_timer = self.set_interval(0.05, self._shake_tick)
        self.set_timer(0.4, self._clear_shake_tint)

    def _confetti_tick(self):
        if self._confetti_idx < len(self._confetti_frames):
            confetti_line = self._confetti_frames[self._confetti_idx]
            self._confetti_idx += 1
            self.update(f"{self._confetti_base}\n{confetti_line}")
        else:
            if self._confetti_timer:
                self._confetti_timer.stop()
                self._confetti_timer = None
            self._write()

    def _shake_tick(self):
        if self._shake_idx < len(SHAKE_OFFSETS):
            offset = SHAKE_OFFSETS[self._shake_idx]
            self._shake_idx += 1
            self.styles.margin = (0, 0, 0, offset)
        else:
            if self._shake_timer:
                self._shake_timer.stop()
                self._shake_timer = None
            self.styles.margin = (0, 0, 0, 0)

    def _clear_shake_tint(self):
        self.styles.color = "$text"

    def _start_pulse(self):
        if self._pulse_timer is None:
            self._pulse = 0
            self.add_class(PULSE_CLASSES[0])
            self._pulse_timer = self.set_interval(0.5, self._pulse_tick)

    def _stop_pulse(self):
        if self._pulse_timer:
            self._pulse_timer.stop()
            self._pulse_timer = None
        for cls in PULSE_CLASSES:
            self.remove_class(cls)

    def _pulse_tick(self):
        old_class = PULSE_CLASSES[self._pulse]
        self._pulse = (self._pulse + 1) % len(PULSE_CLASSES)
        new_class = PULSE_CLASSES[self._pulse]
        self.remove_class(old_class)
        self.add_class(new_class)

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

        preview = ""
        if self._reasoning_preview:
            text = self._reasoning_full if self._verbose else self._reasoning_preview
            preview = f" \u201c[dim italic]{text}[/dim italic]\u201d"

        if self._status:
            header = (
                f"[bold {cv}]{arrow} {self._icon} {self._agent}[/bold {cv}] "
                f"[dim](iter {self._iteration})[/dim] [bold]{self._status}[/bold]"
                f"{preview}"
            )
        else:
            header = (
                f"[bold {cv}]{arrow} {self._icon} {self._agent}[/bold {cv}] "
                f"[dim](iter {self._iteration})[/dim]{preview}"
            )

        lines = [header]
        if not self._collapsed and self._detail:
            detail = self._detail if self._verbose else self._detail[:500]
            lines.append(f"[dim]{detail}[/dim]")

        if not self._collapsed and self._verbose and self._tool_calls:
            for tool_name, tool_preview in self._tool_calls:
                icon = {"web_search": "\U0001f50d", "fetch_url": "\U0001f310", "calculate": "\U0001f522"}.get(tool_name, "\u2699")
                lines.append(f"[dim italic]{icon} {tool_name}: {tool_preview}[/dim italic]")

        return "\n".join(lines)


class ChatHistory(VerticalScroll):
    def add_card(self, agent: str, iteration: int, detail: str, status: str = ""):
        card = IterationCard(agent, iteration, detail, status, classes="chat-card")
        card.styles.opacity = 0
        self.mount(card)
        self.scroll_end(animate=False)

        def _fade_in():
            card.styles.opacity = 1

        card.set_timer(0.05, _fade_in)
        return card

    def add_result(self, text: str):
        self.mount(Static(text, classes="chat-result"))
        self.scroll_end(animate=False)

    def add_markdown(self, md: str):
        from textual.widgets import Markdown
        self.mount(Markdown(md, classes="chat-card"))
        self.scroll_end(animate=False)
