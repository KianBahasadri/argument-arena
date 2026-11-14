"""Console entry point and offline operator utilities."""

import argparse
import asyncio
import logging
import os
from pathlib import Path

from argument_arena.config import Config
from argument_arena.health import healthy
from argument_arena.locking import process_lock
from argument_arena.logging import configure_logging
from argument_arena.runtime import run
from argument_arena.storage import Storage, restore, snapshot


async def migrate(path: Path) -> None:
    async with Storage(path):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Argument Arena bot and maintenance")
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("AA_DATA_DIR", ".state")))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Start the Gateway client (the default)")
    sub.add_parser("check-config", help="Validate configuration and token file without connecting")
    probe = sub.add_parser("healthcheck", help="Probe local readiness without Discord access")
    probe.add_argument("--liveness", action="store_true")
    sub.add_parser("migrate", help="Apply migrations offline; bot must be stopped")
    backup = sub.add_parser("backup", help="Create a SQLite snapshot; bot must be stopped")
    backup.add_argument("destination", type=Path)
    recovery = sub.add_parser("restore", help="Restore a validated snapshot; bot must be stopped")
    recovery.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        if args.command == "healthcheck":
            return 0 if healthy(args.data_dir, readiness=not args.liveness) else 1
        if args.command in {"migrate", "backup", "restore"}:
            with process_lock(args.data_dir):
                database = args.data_dir / "arena.sqlite3"
                if args.command == "migrate":
                    asyncio.run(migrate(database))
                elif args.command == "backup":
                    snapshot(database, args.destination)
                else:
                    asyncio.run(restore(args.source, database))
        else:
            config = Config.from_env()
            if args.command == "check-config":
                config.read_token()
                logging.getLogger(__name__).info("configuration_valid")
            else:
                asyncio.run(run(config))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        # Only the class is safe: config values, tokens, paths and HTTP bodies must stay private.
        logging.getLogger(__name__).error("operation_failed:%s", type(error).__name__)
        return 1
    return 0
