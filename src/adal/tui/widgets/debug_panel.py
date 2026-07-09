from textual.containers import Vertical
from textual.message import Message
from textual.widgets import RichLog, Static

CATEGORY_COLORS = {
    "planner": "bright_cyan",
    "proposer": "bright_magenta",
    "verifier": "bright_yellow",
    "fsm": "bright_green",
    "tool": "dim",
    "memory": "bright_blue",
    "llm": "white",
    "sandbox": "bright_cyan",
    "restore": "bright_green",
    "usage": "bright_cyan",
    "db": "dim",
}

VERBOSITY_LOW = 0
VERBOSITY_MED = 1
VERBOSITY_HIGH = 2

_TIER_NAMES = {VERBOSITY_LOW: "LOW", VERBOSITY_MED: "MED", VERBOSITY_HIGH: "HIGH"}

_DEBUG_LINES: list[tuple[str, int]] = []
_MAX_BUFFER = 3000
_CURRENT_TIER: int = VERBOSITY_LOW


class DebugLine(Message):
    def __init__(self, category: str, event: str, detail: str, verbosity: int = VERBOSITY_LOW):
        super().__init__()
        self.category = category
        self.event = event
        self.detail = detail
        self.verbosity = verbosity


class DebugPanel(Vertical):
    DEFAULT_CSS = """
    DebugPanel {
        height: auto;
        max-height: 30;
        min-height: 4;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._line_count = 0

    def compose(self):
        yield Static("  DEBUG (LOW)  ", id="debug-header")
        yield RichLog(id="debug-log", max_lines=3000, markup=True, highlight=True)

    def on_mount(self):
        log = self.query_one("#debug-log", RichLog)
        count = 0
        for line, verbosity in _DEBUG_LINES:
            if verbosity <= _CURRENT_TIER:
                log.write(line)
                count += 1
        self._line_count = count
        self._update_header()

    def _update_header(self):
        try:
            label = _TIER_NAMES.get(_CURRENT_TIER, "???")
            self.query_one("#debug-header", Static).update(f"  DEBUG ({label})  ")
        except Exception:
            pass

    def set_tier(self, tier: int):
        global _CURRENT_TIER
        _CURRENT_TIER = tier
        self._update_header()
        self._replay()

    def _replay(self):
        log = self.query_one("#debug-log", RichLog)
        log.clear()
        count = 0
        for line, verbosity in _DEBUG_LINES:
            if verbosity <= _CURRENT_TIER:
                log.write(line)
                count += 1
        self._line_count = count

    def write(self, category: str, event: str, detail: str, timestamp: str = "",
              verbosity: int = VERBOSITY_LOW):
        if verbosity > _CURRENT_TIER:
            return

        color = CATEGORY_COLORS.get(category, "white")
        if timestamp:
            prefix = f"[dim]{timestamp}[/dim]"
        else:
            from datetime import datetime
            prefix = f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]"
        tag = f"[bold {color}]{category.upper()}.{event.upper()}[/bold {color}]"
        detail_text = str(detail)[:1200].replace("\n", " ")
        line = f"{prefix} {tag} {detail_text}"
        self._line_count += 1
        if self._line_count % 10 == 0:
            line += f"  [dim]({self._line_count})[/dim]"

        _DEBUG_LINES.append((line, verbosity))
        if len(_DEBUG_LINES) > _MAX_BUFFER:
            del _DEBUG_LINES[:(_MAX_BUFFER // 4)]
            self._replay()
            return

        self.query_one("#debug-log", RichLog).write(line)
