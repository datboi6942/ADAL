from pathlib import Path

from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Input, Static


class ExportDialog(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    DEFAULT_CSS = """
    ExportDialog {
        align: center middle;
    }
    #export-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        padding: 2 3;
        border: thick $primary;
        background: $panel;
    }
    #export-title {
        text-style: bold;
        padding-bottom: 1;
        color: $accent;
    }
    #current-path {
        margin: 0 0 1 0;
    }
    #tree-area {
        height: auto;
        min-height: 4;
    }
    #export-dir-tree {
        height: 12;
        margin: 0 0 1 0;
        border: solid $primary-darken-1;
        padding: 0 1;
    }
    #export-dir-tree:focus {
        border: solid $accent;
    }
    #export-filename-label {
        padding: 1 0 0 0;
        color: $text-muted;
    }
    #export-filename {
        margin: 0 0 1 0;
    }
    #export-save-path {
        padding: 0 0 1 0;
        color: $success;
    }
    #export-buttons {
        width: 100%;
        height: auto;
        align: center middle;
    }
    #export-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, content: str, filename: str = "adal_export.md"):
        super().__init__()
        self._content = content
        self._filename = filename
        self._directory = "/"

    def compose(self):
        from textual.containers import Vertical
        with Vertical(id="export-dialog"):
            yield Static("Select Export Location", id="export-title")
            yield Static("[dim]Path (type or browse):[/dim]", id="current-path-label")
            yield Input(value=self._directory, id="current-path")
            with Vertical(id="tree-area"):
                yield DirectoryTree(self._directory, id="export-dir-tree")
            yield Static("Filename:", id="export-filename-label")
            yield Input(value=self._filename, id="export-filename")
            yield Static("", id="export-save-path")
            with Horizontal(id="export-buttons"):
                yield Button("Save", variant="primary", id="export-save")
                yield Button("Cancel", variant="default", id="export-cancel")

    def on_mount(self):
        self._update_save_preview()

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected):
        self._directory = str(event.path)
        self.query_one("#current-path", Input).value = self._directory
        self._update_save_preview()

    async def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "export-filename":
            self._save()
        elif event.input.id == "current-path":
            new_path = event.value.strip()
            if not new_path:
                return
            p = Path(new_path)
            if not p.is_dir():
                self.notify(f"Directory not found: {new_path}", severity="warning", title="Export")
                event.input.value = self._directory
                return
            self._directory = str(p)
            await self._replace_tree()

    async def _replace_tree(self):
        area = self.query_one("#tree-area")
        old_tree = self.query_one("#export-dir-tree", DirectoryTree)
        await old_tree.remove()
        area.mount(DirectoryTree(self._directory, id="export-dir-tree"))
        self._update_save_preview()
        self.query_one("#export-filename", Input).focus()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "export-filename":
            self._update_save_preview()

    def _update_save_preview(self):
        filename = self.query_one("#export-filename", Input).value.strip() or "untitled.md"
        if not filename.endswith(".md"):
            filename += ".md"
        path = Path(self._directory) / filename
        self.query_one("#export-save-path", Static).update(
            f"Save to: [bold]{path}[/bold]"
        )

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "export-cancel":
            self.dismiss()
        elif event.button.id == "export-save":
            self._save()

    def action_dismiss(self):
        self.dismiss()

    def action_save(self):
        self._save()

    def _save(self):
        filename = self.query_one("#export-filename", Input).value.strip()
        if not filename:
            self.notify("Enter a filename", severity="warning", title="Export")
            return
        if not filename.endswith(".md"):
            filename += ".md"
        path = Path(self._directory) / filename
        try:
            path.write_text(self._content, encoding="utf-8")
            self.notify(f"Exported to {path}", title="Export")
        except Exception as e:
            self.notify(str(e), severity="error", title="Export Failed")
        self.dismiss()
