"""Run with python -m arena; one process owns the durable queue and database."""
import contextlib
import fcntl
import logging
from pathlib import Path

from .bot import ArenaBot
from .config import Config


@contextlib.contextmanager
def database_lock(path):
    if path == ":memory:":
        yield
        return
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("Another Argument Arena process already owns this database.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.from_env()
    if not config.token:
        raise SystemExit("DISCORD_TOKEN must be supplied through the environment or a Kubernetes Secret.")
    with database_lock(config.database_path):
        bot = ArenaBot(config)
        bot.run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
