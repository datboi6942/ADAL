from textual.screen import Screen


class SelectableScreen(Screen):
    """Screen with auto-copy-on-select support.

    Click-drag text selection automatically copies to clipboard on mouse release.
    """

    def on_text_selected(self) -> None:
        import pyperclip

        selected = self.get_selected_text()
        if selected and selected.strip():
            try:
                pyperclip.copy(selected)
                self.notify("Copied to clipboard", severity="information", timeout=1.5)
                self.clear_selection()
            except pyperclip.PyperclipException:
                self.notify(
                    "Clipboard not available — nothing copied",
                    title="Copy",
                    severity="warning",
                )
