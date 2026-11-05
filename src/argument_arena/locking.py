"""One process per durable data directory, including maintenance commands."""

from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def process_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(data_dir / "bot.lock", timeout=0)
    try:
        lock.acquire()
    except Timeout:
        raise AlreadyRunning(
            "Another bot or maintenance process holds the data directory"
        ) from None
    try:
        yield
    finally:
        lock.release()
