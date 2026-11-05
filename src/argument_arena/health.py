"""Local heartbeat probes; no listener, Discord request, or secret is needed."""

import json
import os
import time
from pathlib import Path

HEARTBEAT_INTERVAL = 5
MAX_HEARTBEAT_AGE = 30


def write_health(data_dir: Path, *, ready: bool) -> None:
    path = data_dir / "health.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"updated_at": time.time(), "ready": ready, "pid": os.getpid()}),
        encoding="utf-8",
    )
    temporary.replace(path)


def healthy(data_dir: Path, *, readiness: bool = True) -> bool:
    try:
        payload = json.loads((data_dir / "health.json").read_text(encoding="utf-8"))
        age = time.time() - float(payload["updated_at"])
        return 0 <= age <= MAX_HEARTBEAT_AGE and (not readiness or payload["ready"] is True)
    except (OSError, ValueError, KeyError, TypeError):
        return False
