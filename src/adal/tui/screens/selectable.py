from textual.screen import Screen


class SelectableScreen(Screen):
    """Screen with auto-copy-on-select support.

    Click-drag text selection automatically copies to clipboard on mouse release.
    """

    def on_text_selected(self) -> None:
        import pyperclip

        selected = self.get_selected_text()
        if selected and selected.strip():
            pyperclip.copy(selected)
