from textual.widgets import Label


class StatusBar(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._telemetry_active = False

    def update_info(self, info: str):
        prefix = "[bold bright_magenta]\U0001f9e0 OBS[/bold bright_magenta] " if self._telemetry_active else ""
        self.update(f"{prefix}{info}")

    def set_telemetry(self, active: bool):
        self._telemetry_active = active
