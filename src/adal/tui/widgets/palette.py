from textual.command import Hit, Hits, Provider


class ADALProvider(Provider):
    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        commands = [
            ("New Session", "Start a new research session", "new"),
            ("Session History", "View past research sessions", "history"),
            ("Research Library", "Browse validated synthesis procedures", "library"),
            ("Settings: Agents", "Configure agent temperature and penalties", "settings_agents"),
            ("Settings: Models", "Switch LLM provider and model", "settings_models"),
            ("Settings: Memory", "Configure vector memory settings", "settings_memory"),
            ("Settings: Search", "Configure web search throttle and cache", "settings_search"),
            ("Settings: General", "Log level, database URL", "settings_general"),
            ("Settings: Loop Control", "Tool turns, retries, pivot threshold", "settings_loop"),
            ("Settings: Advanced", "Iterations, sandbox, memory/search tuning", "settings_advanced"),
            ("Settings: Theme", "Choose color theme from 8 available options", "settings_theme"),
            ("Settings: Pricing", "Configure per-token LLM cost tracking", "settings_pricing"),
            ("Telemetry Dashboard", "View cognitive meta-diagnostics", "telemetry"),
            ("Toggle Theme", "Quick-cycle to the next theme", "toggle_theme"),
            ("Export Last Result", "Export the most recent result as markdown", "export"),
            ("Quit", "Exit ADAL", "quit"),
        ]
        for name, help_text, action in commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    self._mk_callable(action),
                    help=help_text,
                )

    def _mk_callable(self, action: str):
        return lambda a=action: self.app._handle_palette(a)
