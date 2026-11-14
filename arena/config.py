"""Configuration is read from the environment, never from tracked secrets."""

from dataclasses import dataclass, field
import os


@dataclass
class Config:
    token: str = field(default="", repr=False)
    database_path: str = "data/arena.sqlite3"
    guild_id: int | None = None
    llm_api_key: str = field(default="", repr=False)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    research_api_key: str = field(default="", repr=False)
    research_base_url: str = "https://api.tavily.com"
    daily_llm_calls: int = 500
    daily_research_calls: int = 100
    llm_input_cost_per_million: float = 0
    llm_output_cost_per_million: float = 0
    daily_llm_budget_usd: float = 0
    llm_max_input_bytes: int = 120000
    llm_max_output_tokens: int = 3000
    llm_token_parameter: str = "max_completion_tokens"

    @classmethod
    def from_env(cls):
        return cls(
            token=os.getenv("DISCORD_TOKEN", ""),
            database_path=os.getenv("DATABASE_PATH", "data/arena.sqlite3"),
            guild_id=int(os.environ["DISCORD_GUILD_ID"]) if os.getenv("DISCORD_GUILD_ID") else None,
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini"),
            research_api_key=os.getenv("RESEARCH_API_KEY", ""),
            research_base_url=os.getenv("RESEARCH_BASE_URL", "https://api.tavily.com"),
            daily_llm_calls=int(os.getenv("DAILY_LLM_CALLS", "500")),
            daily_research_calls=int(os.getenv("DAILY_RESEARCH_CALLS", "100")),
            llm_input_cost_per_million=float(os.getenv("LLM_INPUT_COST_PER_MILLION", "0")),
            llm_output_cost_per_million=float(os.getenv("LLM_OUTPUT_COST_PER_MILLION", "0")),
            daily_llm_budget_usd=float(os.getenv("DAILY_LLM_BUDGET_USD", "0")),
            llm_max_input_bytes=int(os.getenv("LLM_MAX_INPUT_BYTES", "120000")),
            llm_max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "3000")),
            llm_token_parameter=os.getenv("LLM_TOKEN_PARAMETER", "max_completion_tokens"),
        )

    def as_dict(self):
        return dict(vars(self))
