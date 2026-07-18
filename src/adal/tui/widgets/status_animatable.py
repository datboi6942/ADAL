"""Mixin for screens with an animated status bar."""

import random
import time

from textual.widgets import Static

from adal.tui.widgets.loading_spinner import (
    AGENT_ICONS,
    AGENT_LABELS,
    BAR_WIDTH,
    GRADIENT,
    SPARKLE_CHARS,
)


class StatusAnimatableMixin:
    _tick_count: int = 0
    _status_timer: object | None = None
    _iter: int = 0
    _max_iters: int = 1
    _current_agent: str = ""
    _start_time: float = 0.0
    _ticking: bool = False

    _status_label_fallback: str = "Working"

    def _update_status(self, text: str) -> None:
        self.query_one("#status-text", Static).update(f"[dim]{text}[/dim]")

    def _on_status_animation_started(self) -> None:
        pass

    def _start_status_animation(self) -> None:
        self._on_status_animation_started()
        self._tick_count = 0
        self._ticking = True
        if self._status_timer is None:
            self._status_timer = self.set_timer(0.15, self._status_tick)

    def _stop_status_animation(self) -> None:
        self._ticking = False
        if self._status_timer:
            self._status_timer.stop()
            self._status_timer = None

    def _status_tick(self) -> None:
        try:
            if not self._ticking:
                return
            self._tick_count += 1
            elapsed = int(time.time() - self._start_time) if self._start_time > 0 else 0
            m, s = divmod(max(elapsed, 0), 60)
            agent_key = self._current_agent or ""

            icon = AGENT_ICONS.get(agent_key, "\u269b")
            pulse_val = ((self._tick_count // 2) % 16) - 8
            if pulse_val < 0:
                icon = f"[dim]{icon}[/dim]"
            elif pulse_val > 0:
                icon = f"[bold]{icon}[/bold]"

            fill_pct = self._iter / self._max_iters if self._max_iters > 0 else 0
            filled = int(fill_pct * BAR_WIDTH)

            bar_chars = []
            for i in range(BAR_WIDTH):
                wave_dist = (i - (self._tick_count % BAR_WIDTH)) % BAR_WIDTH
                if wave_dist < BAR_WIDTH // 2:
                    wave_bright = wave_dist / (BAR_WIDTH // 2)
                else:
                    wave_bright = (BAR_WIDTH - wave_dist) / (BAR_WIDTH // 2)
                if i < filled:
                    color_idx = (i + self._tick_count // 6) % len(GRADIENT)
                    bar_chars.append(f"[{GRADIENT[color_idx]}]\u2588[/{GRADIENT[color_idx]}]")
                elif i == filled:
                    color_idx = (i + self._tick_count // 6) % len(GRADIENT)
                    bar_chars.append(f"[{GRADIENT[color_idx]}]\u2593[/{GRADIENT[color_idx]}]")
                elif i == filled + 1:
                    bar_chars.append("[dim]\u2591[/dim]")
                else:
                    if random.random() < wave_bright * 0.08:
                        bar_chars.append("[dim]\u2592[/dim]")
                    else:
                        bar_chars.append("[dim]\u2591[/dim]")

            sparkle = " "
            if filled < BAR_WIDTH and random.random() < 0.12:
                sparkle_char = random.choice(SPARKLE_CHARS)
                col = GRADIENT[(filled + self._tick_count // 6) % len(GRADIENT)]
                sparkle = f"[{col}]{sparkle_char}[/{col}]"

            bar = "".join(bar_chars)
            agent_label = AGENT_LABELS.get(agent_key, "")
            agent_icon = AGENT_ICONS.get(agent_key, "\u269b")
            if agent_label:
                label = f"[bold]{agent_icon} {agent_label}[/bold]"
            else:
                label = f"[dim]{agent_icon} {self._status_label_fallback}[/dim]"

            line = (
                f"{icon} {bar} {sparkle} "
                f"[bold]{self._iter}/{self._max_iters}[/bold] "
                f"{label}  "
                f"[dim]{m:02d}:{s:02d}[/dim]"
            )
            self.query_one("#status-text", Static).update(line)
            self._status_timer = self.set_timer(0.15, self._status_tick)
        except Exception:
            pass
