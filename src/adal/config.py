from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("database_url")
    @classmethod
    def _resolve_db_path(cls, v: str) -> str:
        if v.startswith("sqlite+aiosqlite:///"):
            parts = v.split("///", 1)
            if len(parts) == 2 and parts[1] and not parts[1].startswith("/"):
                absolute = Path(parts[1]).resolve()
                return f"sqlite+aiosqlite:///{absolute}"
        return v

    llm_provider: str = "deepseek"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-pro"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    openrouter_api_key: str = ""
    openrouter_model: str = ""

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = ""

    custom_api_key: str = ""
    custom_base_url: str = ""
    custom_model: str = ""

    deepseek_sub_model: str = "deepseek-v4-chat"
    openai_sub_model: str = "gpt-4o-mini"
    openrouter_sub_model: str = ""
    ollama_sub_model: str = ""
    custom_sub_model: str = ""

    llm_model: str = ""
    llm_max_tokens: int = 65536
    reasoning_effort: str = "max"

    database_url: str = "sqlite+aiosqlite:///adal.db"
    max_iterations: int = 10
    sandbox_timeout: int = 120
    log_level: str = "INFO"

    llm_input_price_per_mtok: float = 0.435
    llm_cached_price_per_mtok: float = 0.003625
    llm_output_price_per_mtok: float = 0.87

    openai_embedding_model: str = "text-embedding-3-small"
    memory_enabled: bool = True
    memory_db_path: str = "./memory_vault.lance"
    memory_max_episodic: int = 5
    memory_max_global: int = 3
    memory_prune_threshold: float = 0.85

    proposer_temperature: float = 0.7
    proposer_top_p: float = 0.95
    proposer_frequency_penalty: float = 0.3
    proposer_presence_penalty: float = 0.2
    proposer_top_k: int = 0
    proposer_seed: int | None = None

    verifier_temperature: float = 0.3
    verifier_top_p: float = 0.9
    verifier_frequency_penalty: float = 0.0
    verifier_presence_penalty: float = 0.0
    verifier_top_k: int = 0
    verifier_seed: int | None = None

    planner_temperature: float = 0.4
    planner_top_p: float = 0.9
    planner_frequency_penalty: float = 0.0
    planner_presence_penalty: float = 0.1
    planner_top_k: int = 0
    planner_seed: int | None = None

    forced_answer_temperature: float = 0.1

    search_throttle_delay: float = 2.0
    search_max_retries: int = Field(3, ge=1, le=30)
    blocked_fetch_hosts: str = "pubchem.ncbi.nlm.nih.gov"

    search_max_results: int = 5
    search_timeout: float = 20.0
    search_backoff_base: float = 2.0

    fetch_max_chars: int = 10000
    fetch_max_retries: int = Field(3, ge=1, le=30)
    fetch_timeout: float = 25.0

    llm_max_tool_turns: int = 12
    agent_llm_retry_count: int = 2
    orchestrator_pivot_threshold: int = 3

    planner_max_tool_turns: int = 2
    planner_initial_tool_turns: int = 0
    proposer_max_tool_turns: int = 1
    verifier_max_tool_turns: int = 3
    self_critique_max_tool_turns: int = 2
    deep_verify_max_tool_turns: int = 2
    revise_max_tool_turns: int = 3

    planner_timeout: float = 60.0
    proposer_timeout: float = 120.0
    verifier_timeout: float = 90.0
    self_critique_timeout: float = 60.0
    deep_verify_timeout: float = 90.0
    revise_timeout: float = 90.0

    max_parallel_tools: int = 2
    tool_fail_streak_limit: int = 3

    memory_enrich_context_cap: int = 3
    memory_index_min_rows: int = 256
    memory_query_oversample_factor: int = Field(3, ge=1, le=20)

    adal_theme: str = "textual-dark"

    telemetry_enabled: bool = False
    telemetry_model: str = "deepseek-v4-pro"
    telemetry_interval: int = 1

    @property
    def db_path(self) -> Path:
        if self.database_url.startswith("sqlite"):
            parts = self.database_url.split("///")
            if len(parts) == 2:
                return Path(parts[1])
        return Path("adal.db")


settings = Settings()
