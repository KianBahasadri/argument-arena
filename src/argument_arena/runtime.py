"""Supervised async lifecycle; the data lock outlives all client/database activity."""

import asyncio
import logging
import signal
from contextlib import contextmanager

from argument_arena.client import ArenaClient
from argument_arena.config import Config
from argument_arena.health import HEARTBEAT_INTERVAL, write_health
from argument_arena.locking import process_lock
from argument_arena.logging import configure_logging
from argument_arena.storage import Storage

logger = logging.getLogger(__name__)


@contextmanager
def shutdown_signals(stop: asyncio.Event):
    loop = asyncio.get_running_loop()
    previous = {}
    native = set()
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.getsignal(sig)
        try:
            loop.add_signal_handler(sig, stop.set)
            native.add(sig)
        except NotImplementedError:  # Local Python on Windows; container uses the POSIX path.
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        yield
    finally:
        for sig, handler in previous.items():
            if sig in native:
                loop.remove_signal_handler(sig)
            signal.signal(sig, handler)


async def heartbeat(client: ArenaClient, storage: Storage, config: Config) -> None:
    while True:
        await storage.check()
        write_health(config.data_dir, ready=client.gateway_ready and client.is_ready())
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def run(config: Config, stop: asyncio.Event | None = None) -> None:
    token = config.read_token()
    configure_logging(config.log_level, secrets=(token,))
    stop = stop if stop is not None else asyncio.Event()
    with process_lock(config.data_dir), shutdown_signals(stop):
        write_health(config.data_dir, ready=False)
        try:
            async with Storage(config.data_dir / "arena.sqlite3") as storage:
                async with ArenaClient(config, storage) as client:
                    tasks = [
                        asyncio.create_task(client.start(token, reconnect=True), name="gateway"),
                        asyncio.create_task(heartbeat(client, storage, config), name="heartbeat"),
                        asyncio.create_task(stop.wait(), name="shutdown"),
                        asyncio.create_task(client.worker.run(), name="arena-worker"),
                    ]
                    try:
                        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        for task in done:
                            # Propagate fatal login, sync, DB, or health errors.
                            task.result()
                        logger.info("shutdown_requested")
                    finally:
                        try:
                            write_health(config.data_dir, ready=False)
                        finally:
                            try:
                                await asyncio.wait_for(client.close(), timeout=15)
                            finally:
                                for task in tasks:
                                    task.cancel()
                                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            write_health(config.data_dir, ready=False)
        logger.info("shutdown_complete")
