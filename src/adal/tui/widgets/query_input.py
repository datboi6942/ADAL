from textual.widgets import Input


class QueryInput(Input):
    def __init__(self, **kwargs):
        super().__init__(placeholder="Research query... (Enter to submit, Shift+Enter for newline)", **kwargs)

    @property
    def query(self) -> str:
        return self.value.strip()

    def clear_query(self):
        self.value = ""
