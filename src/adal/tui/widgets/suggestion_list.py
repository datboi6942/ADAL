from textual.widgets import Static

from adal.tui.widgets.commands import SlashCommand, filter_commands


class SuggestionList(Static):
    DEFAULT_CSS = """
    SuggestionList {
        height: auto;
        max-height: 14;
        background: $surface-darken-1;
        padding: 0 1;
        border-top: solid $primary-darken-1;
        display: none;
    }
    SuggestionList.visible {
        display: block;
    }
    .suggestion-row {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    .suggestion-row.selected {
        background: $accent 20%;
        color: $text;
    }
    .suggestion-cmd {
        color: $accent;
    }
    .suggestion-desc {
        color: $text-muted;
        padding-left: 2;
    }
    """

    def __init__(self, **kwargs):
        super().__init__("", **kwargs)
        self._commands: list[SlashCommand] = []
        self._selected = 0
        self._visible = False

    def show_results(self, query: str):
        self._commands = filter_commands(query)
        self._selected = 0
        self._visible = True
        self.add_class("visible")
        self._render_suggestions()

    def hide(self):
        self._visible = False
        self.remove_class("visible")
        self._commands = []
        self._selected = 0
        self.update("")

    def move_selection(self, delta: int):
        if not self._commands:
            return
        self._selected = (self._selected + delta) % len(self._commands)
        self._render_suggestions()

    def selected_command(self) -> SlashCommand | None:
        if 0 <= self._selected < len(self._commands):
            return self._commands[self._selected]
        return None

    def _render_suggestions(self):
        if not self._commands:
            self.update("[dim]No matching commands[/dim]")
            return

        lines = []
        for i, cmd in enumerate(self._commands):
            marker = "\u25b8" if i == self._selected else " "
            cmd_name = cmd.name
            if cmd.usage:
                line = f"{marker} [bold $accent]{cmd_name}[/bold $accent] [dim]{cmd.usage}[/dim]"
            else:
                line = f"{marker} [bold $accent]{cmd_name}[/bold $accent]  [dim italic]{cmd.description}[/dim italic]"
            lines.append(line)
        self.update("\n".join(lines))
