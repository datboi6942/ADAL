from dataclasses import dataclass


@dataclass
class SlashCommand:
    name: str
    description: str
    usage: str = ""


COMMAND_REGISTRY: list[SlashCommand] = [
    SlashCommand("/help", "Show available slash commands"),
    SlashCommand("/verbose", "Toggle verbose mode (show full reasoning and tool calls)"),
    SlashCommand("/theme", "Change color theme", "/theme <name> — e.g., /theme dracula"),
    SlashCommand("/stop", "Stop the current research run"),
    SlashCommand("/clear", "Clear chat history"),
    SlashCommand("/export", "Export the last result to adal_export.md"),
    SlashCommand("/settings", "Open settings hub"),
    SlashCommand("/history", "Browse past research sessions"),
    SlashCommand("/library", "Browse validated synthesis procedures"),
    SlashCommand("/session", "Load a session by ID", "/session <id>"),
    SlashCommand("/model", "Show the current LLM model"),
    SlashCommand("/status", "Show current session runtime stats"),
    SlashCommand("/back", "Go to the previous screen"),
    SlashCommand("/quit", "Exit ADAL (alias: /exit)"),
    SlashCommand("/exit", "Exit ADAL (alias: /quit)"),
]


def filter_commands(query: str) -> list[SlashCommand]:
    if not query:
        return list(COMMAND_REGISTRY)
    q = query.lower().lstrip("/")
    return [c for c in COMMAND_REGISTRY if q in c.name.lower() or q in c.description.lower()]
