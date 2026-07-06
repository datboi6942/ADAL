from textual.widgets import Label


class StatusBar(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_info(self, info: str):
        self.update(info)
