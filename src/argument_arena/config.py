"""Non-secret environment configuration; secrets are read only at runtime."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(ValueError):
    """Invalid operator input. Messages never contain input values."""


@dataclass(frozen=True)
class Config:
    guild_id: int
    token_file: Path
    data_dir: Path = Path(".state")
    sync_commands: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        guild = env.get("AA_GUILD_ID", "")
        if not guild.isascii() or not guild.isdecimal() or not 0 < int(guild) < 2**64:
            raise ConfigurationError("AA_GUILD_ID must be a positive Discord snowflake")
        token_file = env.get("AA_DISCORD_TOKEN_FILE", "").strip()
        if not token_file:
            raise ConfigurationError("AA_DISCORD_TOKEN_FILE must name a mounted token file")
        data_dir = env.get("AA_DATA_DIR", ".state").strip()
        if not data_dir:
            raise ConfigurationError("AA_DATA_DIR must name a writable data directory")
        sync = env.get("AA_SYNC_COMMANDS", "true").lower()
        if sync not in {"true", "false"}:
            raise ConfigurationError("AA_SYNC_COMMANDS must be true or false")
        level = env.get("AA_LOG_LEVEL", "INFO").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("AA_LOG_LEVEL must be a standard logging level")
        return cls(int(guild), Path(token_file), Path(data_dir), sync == "true", level)

    def read_token(self) -> str:
        try:
            # Bound the read; neither the contents nor filesystem exception is reported.
            with self.token_file.open(encoding="utf-8") as handle:
                token = handle.read(4097).strip()
        except (OSError, UnicodeError):
            raise ConfigurationError("Discord token file must be readable UTF-8") from None
        if not token or len(token) > 4096 or any(char.isspace() for char in token):
            raise ConfigurationError("Discord token file must contain one non-empty token")
        return token
