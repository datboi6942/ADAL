from textual.widgets import Markdown


class SynthViewer(Markdown):
    def __init__(self, content: str = ""):
        super().__init__(content or "*No procedure available*", id="synth-viewer")
