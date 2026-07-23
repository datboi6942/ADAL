from textual.message import Message
from textual.widgets import TextArea

from adal.tui.widgets.suggestion_list import SuggestionList


class QuerySubmit(Message):
    def __init__(self, query: str):
        super().__init__()
        self.query = query


class CommandSubmit(Message):
    def __init__(self, command: str):
        super().__init__()
        self.command = command


class CommandInput(TextArea):
    def __init__(
        self,
        suggestion_list_id: str = "suggestion-list",
        **kwargs,
    ):
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "indent")
        super().__init__(**kwargs)
        self._suggestion_list_id = suggestion_list_id
        self._in_command_mode = False
        self._suggestion_list: SuggestionList | None = None
        self._submitting = False
        self._history: list[str] = []
        self._history_idx: int = 0

    @property
    def command_text(self) -> str:
        return self.text.strip()

    def clear_query(self):
        self.clear()

    def on_text_area_changed(self, event: TextArea.Changed):
        raw = self.text
        text = raw.strip()

        if self._submitting:
            return

        if raw.endswith("\n") and text:
            self._submitting = True
            self.text = text
            self._submitting = False

            if text not in self._history:
                self._history.append(text)
            self._history_idx = len(self._history)

            if text.startswith("/"):
                self.post_message(CommandSubmit(text))
            else:
                self.post_message(QuerySubmit(text))
            return

        previous_mode = self._in_command_mode
        self._in_command_mode = text.startswith("/")

        if not previous_mode and self._in_command_mode:
            self._show_suggestions(text)
        elif self._in_command_mode:
            self._filter_suggestions(text)
        elif previous_mode and not self._in_command_mode:
            self._hide_suggestions()

    def get_command_and_args(self) -> tuple[str, str] | None:
        stripped = self.text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped[1:].split(maxsplit=1)
        cmd_name = "/" + parts[0]
        args = parts[1] if len(parts) > 1 else ""
        return cmd_name, args

    def is_command(self) -> bool:
        return self.text.strip().startswith("/")

    def navigate_suggestions(self, delta: int):
        sl = self._get_suggestion_list()
        if sl and sl._visible:
            sl.move_selection(delta)
            return True
        return False

    def accept_suggestion(self) -> str | None:
        sl = self._get_suggestion_list()
        if sl and sl._visible and sl.selected_command():
            cmd = sl.selected_command()
            self.text = cmd.name + " "
            sl.hide()
            self._in_command_mode = True
            return cmd.name
        return None

    def close_suggestions(self):
        self._hide_suggestions()

    def on_key(self, event):
        sl = self._get_suggestion_list()
        if sl and sl._visible:
            if event.key == "up":
                self.navigate_suggestions(-1)
                event.prevent_default()
                event.stop()
                return
            if event.key == "down":
                self.navigate_suggestions(1)
                event.prevent_default()
                event.stop()
                return
            return

        if event.key == "up" and self._history:
            self._show_history(-1)
            event.prevent_default()
            event.stop()
            return
        if event.key == "down" and self._history:
            self._show_history(1)
            event.prevent_default()
            event.stop()
            return

    def _show_history(self, delta: int):
        self._history_idx = max(0, min(len(self._history), self._history_idx + delta))
        if self._history_idx < len(self._history):
            self.text = self._history[self._history_idx]
        else:
            self.text = ""

    def _show_suggestions(self, value: str):
        sl = self._get_suggestion_list()
        if sl is None:
            return
        sl.show_results(value)

    def _filter_suggestions(self, value: str):
        sl = self._get_suggestion_list()
        if sl is None:
            return
        sl.show_results(value)

    def _hide_suggestions(self):
        sl = self._get_suggestion_list()
        if sl is None:
            return
        sl.hide()

    def _get_suggestion_list(self) -> SuggestionList | None:
        if self._suggestion_list is not None:
            return self._suggestion_list
        try:
            self._suggestion_list = self.screen.query_one(f"#{self._suggestion_list_id}", SuggestionList)
        except Exception:
            return None
        return self._suggestion_list


QueryInput = CommandInput
