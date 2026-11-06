from unittest.mock import AsyncMock

import discord.http
import pytest


@pytest.fixture(autouse=True)
def forbid_discord_http(monkeypatch):
    """An accidental real Discord request must fail the offline suite immediately."""
    monkeypatch.setattr(
        discord.http.HTTPClient,
        "request",
        AsyncMock(side_effect=AssertionError("Discord HTTP is forbidden in offline tests")),
    )


@pytest.fixture
async def product(tmp_path):
    from argument_arena.storage import Storage
    from tests.helpers import Clock, configure, services

    async with Storage(tmp_path / "arena.sqlite3") as storage:
        bundle = services(storage, Clock())
        await configure(bundle.arena)
        yield bundle
