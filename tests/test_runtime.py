import asyncio
import json
import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from argument_arena import runtime
from argument_arena.config import Config
from argument_arena.health import healthy, write_health
from argument_arena.locking import process_lock


def test_health_requires_fresh_ready_heartbeat(tmp_path, monkeypatch):
    assert not healthy(tmp_path)
    write_health(tmp_path, ready=False)
    assert healthy(tmp_path, readiness=False)
    assert not healthy(tmp_path)
    write_health(tmp_path, ready=True)
    assert healthy(tmp_path)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 31)
    assert not healthy(tmp_path)
    monkeypatch.setattr(time, "time", lambda: now - 31)
    assert not healthy(tmp_path)
    (tmp_path / "health.json").write_text("malformed")
    assert not healthy(tmp_path)


class FakeClient:
    failure = None
    instance = None

    def __init__(self, config, storage):
        self.config = config
        self.gateway_ready = True
        self.worker = SimpleNamespace(run=lambda: asyncio.Event().wait())
        self.close = AsyncMock()
        self.started = asyncio.Event()
        FakeClient.instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def start(self, token, *, reconnect):
        assert token == "offline-test-token"
        assert reconnect is True
        self.started.set()
        if self.failure:
            raise self.failure
        await asyncio.Event().wait()

    def is_ready(self):
        return True


@pytest.fixture
def runtime_config(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_text("offline-test-token")
    monkeypatch.setattr(runtime, "ArenaClient", FakeClient)
    monkeypatch.setattr(runtime, "shutdown_signals", lambda _: nullcontext())
    monkeypatch.setattr(FakeClient, "failure", None)
    return Config(123, token, tmp_path)


async def test_shutdown_closes_client_database_tasks_and_releases_lock(runtime_config):
    stop = asyncio.Event()
    task = asyncio.create_task(runtime.run(runtime_config, stop))
    for _ in range(100):
        if healthy(runtime_config.data_dir):
            break
        await asyncio.sleep(0.01)
    assert healthy(runtime_config.data_dir)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert FakeClient.instance.close.await_count >= 1
    assert not healthy(runtime_config.data_dir)
    assert not [
        t
        for t in asyncio.all_tasks()
        if t.get_name() in {"gateway", "heartbeat", "shutdown", "arena-worker"}
    ]
    with process_lock(runtime_config.data_dir):
        pass


async def test_fatal_gateway_error_propagates_and_clears_readiness(runtime_config, monkeypatch):
    monkeypatch.setattr(FakeClient, "failure", RuntimeError("offline failure"))
    with pytest.raises(RuntimeError, match="offline failure"):
        await runtime.run(runtime_config)
    assert FakeClient.instance.close.await_count >= 1
    payload = json.loads((runtime_config.data_dir / "health.json").read_text())
    assert payload["ready"] is False


async def test_health_failure_stops_client(runtime_config, monkeypatch):
    async def failed_health(*_):
        raise OSError("disk failure")

    monkeypatch.setattr(runtime, "heartbeat", failed_health)
    with pytest.raises(OSError, match="disk failure"):
        await runtime.run(runtime_config)
    assert FakeClient.instance.close.await_count >= 1


def test_sigterm_performs_real_process_shutdown(tmp_path):
    import os
    import signal
    import subprocess
    import sys

    if os.name == "nt":
        pytest.skip("POSIX SIGTERM delivery; Windows local fallback is separate")
    token = tmp_path / "token"
    token.write_text("offline-test-token")
    script = """
import asyncio
from unittest.mock import AsyncMock
from pathlib import Path
from argument_arena import runtime
from argument_arena.config import Config
class Client:
    gateway_ready = True
    close = AsyncMock()
    def __init__(self, *_): self.worker = self
    async def run(self): await asyncio.Event().wait()
    async def __aenter__(self): return self
    async def __aexit__(self, *_): await self.close()
    async def start(self, *args, **kwargs): await asyncio.Event().wait()
    def is_ready(self): return True
runtime.ArenaClient = Client
import sys
asyncio.run(runtime.run(Config(123, Path(sys.argv[1]), Path(sys.argv[2]))))
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(token), str(tmp_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and process.poll() is None:
            if healthy(tmp_path):
                break
            time.sleep(0.02)
        assert healthy(tmp_path)
        process.send_signal(signal.SIGTERM)
        output, errors = process.communicate(timeout=10)
        assert process.returncode == 0, errors
        assert "shutdown_complete" in output
        assert "offline-test-token" not in output
        assert not healthy(tmp_path)
        with process_lock(tmp_path):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
