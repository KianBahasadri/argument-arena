#!/usr/bin/env python3
"""Check the installed Discord schema and match settings UI."""

import asyncio
import tempfile
from pathlib import Path

from discord import app_commands

from argument_arena.client import ArenaClient
from argument_arena.config import Config
from argument_arena.help_ui import HELP
from argument_arena.settings import DEFAULTS
from argument_arena.settings_ui import FEATURES
from argument_arena.storage import Storage


async def main():
    with tempfile.TemporaryDirectory() as directory:
        async with Storage(Path(directory) / "arena.sqlite3") as storage:
            config = Config(123, Path(directory) / "unused-token", sync_commands=False)
            async with ArenaClient(config, storage) as client:
                commands = []
                for command in client.tree.get_commands(guild=client.guild):
                    command.to_dict(client.tree)  # Serialize actual Discord command schema offline.
                    if isinstance(command, app_commands.Group):
                        assert len(command.commands) <= 25
                        commands.extend(command.walk_commands())
                    else:
                        commands.append(command)
                assert {c.qualified_name for c in commands} == {
                    "challenge",
                    "match",
                    "train",
                    "profile",
                    "leaderboard",
                    "admin",
                    "help",
                }, "Keep superseded actions inside menus, not visible slash subcommands"
                assert (
                    client.tree.get_command("challenge", guild=client.guild).parameters[0].name
                    == "member"
                )
    assert set(FEATURES) == set(DEFAULTS), "Every match feature needs a named UI control"
    assert "24-hour" in HELP["automatic"][1]
    assert "same revision" in HELP["start"][1]
    print(f"Product contract: {len(commands)} commands, {len(DEFAULTS)} settings")


if __name__ == "__main__":
    asyncio.run(main())
