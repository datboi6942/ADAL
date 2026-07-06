from textual.widgets import Static

RING_FRAMES = ["\u25dc", "\u25dd", "\u25de", "\u25df"]
RING_COLORS = ["bold cyan", "bold magenta", "bold yellow", "bold green", "bold blue"]


class LoadingSpinner(Static):
    DEFAULT_CSS = """
    LoadingSpinner {
        width: 5;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._frame = 0
        self._color = 0
        self._timer = None

    def start(self):
        self._frame = 0
        self._color = 0
        self._render_frame()
        self._timer = self.set_interval(0.12, self._tick)

    def stop(self):
        self.update("")
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _tick(self):
        self._frame = (self._frame + 1) % len(RING_FRAMES)
        self._color = (self._color + 1) % len(RING_COLORS)
        self._render_frame()

    def _render_frame(self):
        color = RING_COLORS[self._color]
        chars = [RING_FRAMES[(self._frame + i) % len(RING_FRAMES)] for i in range(3)]
        self.update(f"[{color}]{chars[0]} {chars[1]} {chars[2]}[/{color}]")
