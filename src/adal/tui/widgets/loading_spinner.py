import random

from textual.widgets import Static

AGENT_ICONS = {
    "planner": "\U0001f9e0",
    "proposer": "\U0001f52c",
    "verifier": "\U0001f50d",
    "": "\u269b",
}

AGENT_LABELS = {
    "planner": "PLANNER",
    "proposer": "PROPOSER",
    "verifier": "VERIFIER",
    "decision": "DECISION",
}

AGENT_COLORS = {
    "planner": "cyan",
    "proposer": "bright_magenta",
    "verifier": "bright_yellow",
    "": "bright_cyan",
}

GRADIENT = [
    "bright_cyan", "cyan", "bright_magenta", "magenta",
    "bright_yellow", "yellow", "bright_green", "green",
]

SPARKLE_CHARS = ["\u2728", "\u2726", "\u2747", "\u2731"]

BAR_WIDTH = 24


class LoadingSpinner(Static):
    DEFAULT_CSS = """
    LoadingSpinner {
        width: 1fr;
        height: 1;
        padding: 0 1;
        transition: opacity 0.25s in_out_cubic;
        overflow: hidden;
    }
    LoadingSpinner.active {
        opacity: 1;
    }
    LoadingSpinner.inactive {
        opacity: 0;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._timer = None
        self._fade_timer = None
        self._tick_count = 0
        self._iteration = 0
        self._max_iter = 10
        self._agent = ""
        self._elapsed = 0

    def start(self):
        self._tick_count = 0
        self._iteration = 0
        self._max_iter = 10
        self._agent = ""
        self._elapsed = 0
        self.add_class("active")
        self.remove_class("inactive")
        self.update(self._build_line())
        self._timer = self.set_interval(0.06, self._tick)

    def stop(self):
        if self._fade_timer:
            self._fade_timer.stop()
            self._fade_timer = None
        if self._timer:
            self._timer.stop()
            self._timer = None
        self.add_class("inactive")
        self.remove_class("active")
        self._fade_timer = self.set_timer(0.3, self._clear)

    def _clear(self):
        self.update("")
        self.remove_class("inactive")

    def set_progress(self, iteration: int, max_iter: int = 10):
        self._iteration = iteration
        self._max_iter = max(max_iter, 1)

    def set_agent(self, name: str):
        self._agent = name

    def set_elapsed(self, seconds: int):
        self._elapsed = seconds

    @staticmethod
    def _fmt_time(seconds: int) -> str:
        m, s = divmod(max(seconds, 0), 60)
        return f"{m}:{s:02d}"

    def _tick(self):
        self._tick_count += 1
        self.update(self._build_line())

    def _build_line(self):
        parts = []

        icon = AGENT_ICONS.get(self._agent, "\u269b")
        pulse_val = (self._tick_count % 16) - 8
        if pulse_val < 0:
            icon = f"[dim]{icon}[/dim]"
        elif pulse_val > 0:
            icon = f"[bold]{icon}[/bold]"

        parts.append(icon)

        fill_pct = self._iteration / self._max_iter if self._max_iter > 0 else 0
        filled = int(fill_pct * BAR_WIDTH)

        wave_offset = self._tick_count % BAR_WIDTH

        bar_chars = []
        for i in range(BAR_WIDTH):
            wave_dist = (i - wave_offset) % BAR_WIDTH
            if wave_dist < BAR_WIDTH // 2:
                wave_bright = wave_dist / (BAR_WIDTH // 2)
            else:
                wave_bright = (BAR_WIDTH - wave_dist) / (BAR_WIDTH // 2)

            if i < filled:
                color_idx = (i + self._tick_count // 3) % len(GRADIENT)
                color = GRADIENT[color_idx]
                bar_chars.append(f"[{color}]\u2588[/{color}]")
            elif i == filled:
                color_idx = (i + self._tick_count // 3) % len(GRADIENT)
                color = GRADIENT[color_idx]
                bar_chars.append(f"[{color}]\u2593[/{color}]")
            elif i == filled + 1:
                bar_chars.append("[dim]\u2591[/dim]")
            else:
                if random.random() < wave_bright * 0.3:
                    bar_chars.append("[dim]\u2592[/dim]")
                else:
                    bar_chars.append("[dim]\u2591[/dim]")

        parts.append("".join(bar_chars))

        if filled < BAR_WIDTH and random.random() < 0.35:
            sparkle = random.choice(SPARKLE_CHARS)
            col = GRADIENT[(filled + self._tick_count // 3) % len(GRADIENT)]
            parts.append(f"[{col}]{sparkle}[/{col}]")
        else:
            parts.append(" ")

        parts.append(f"[bold]{self._iteration}/{self._max_iter}[/bold]")

        parts.append(self._fmt_time(self._elapsed))

        return " ".join(parts)
