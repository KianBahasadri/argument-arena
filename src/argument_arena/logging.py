"""JSON logs with conservative fields and redaction at the output boundary."""

import json
import logging
import re
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        for secret in self.secrets:
            message = message.replace(secret, "[REDACTED]")
        # Discord interaction/webhook URLs can contain credentials distinct from the bot token.
        message = re.sub(r"https?://\S+", "[URL REDACTED]", message)
        payload = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": message,
        }
        if record.exc_info and record.exc_info[0]:
            # Exception messages and tracebacks can include request bodies and credentials.
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True)


def configure_logging(level: str = "INFO", *, secrets: tuple[str, ...] = ()) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(secrets))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # The library's debug HTTP/Gateway logs include payloads. Keep them off at every app level.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("filelock").setLevel(logging.WARNING)
