import asyncio
import sqlite3
import subprocess
import sys

import pytest

from argument_arena.locking import AlreadyRunning, process_lock
from argument_arena.storage import MIGRATIONS, Migration, MigrationError, Storage, restore, snapshot


async def test_migrations_are_idempotent_and_state_survives_restart(tmp_path):
    path = tmp_path / "arena.sqlite3"
    async with Storage(path) as storage:
        assert await storage.get("guild:1", "config") is None
        await storage.put("guild:1", "config", {"enabled": True, "roles": [1, 2]})
        await storage.put("guild:2", "config", "another guild")
    async with Storage(path) as storage:
        assert await storage.get("guild:1", "config") == {"enabled": True, "roles": [1, 2]}
        assert await storage.get("guild:2", "config") == "another guild"
        async with storage.connection.execute("SELECT COUNT(*) FROM schema_migrations") as cursor:
            assert await cursor.fetchone() == (len(MIGRATIONS),)


async def test_failed_and_cancelled_transactions_rollback(tmp_path):
    async with Storage(tmp_path / "arena.sqlite3") as storage:
        for error in (ValueError, asyncio.CancelledError):
            with pytest.raises(error):
                async with storage.transaction() as db:
                    await db.execute(
                        "INSERT INTO settings(namespace,key,value_json) VALUES ('test','key','1')"
                    )
                    raise error()
            assert await storage.get("test", "key") is None
        await asyncio.gather(*(storage.put("parallel", str(n), n) for n in range(10)))
        assert await storage.get("parallel", "9") == 9


async def test_bad_migration_rolls_back_ddl_and_version(tmp_path):
    path = tmp_path / "arena.sqlite3"
    async with Storage(path):
        pass
    bad = Migration(len(MIGRATIONS) + 1, "bad", ("CREATE TABLE future(id INTEGER)", "INVALID SQL"))
    with pytest.raises(sqlite3.OperationalError):
        async with Storage(path, (*MIGRATIONS, bad)):
            pass
    async with Storage(path) as storage:
        async with storage.connection.execute(
            "SELECT name FROM sqlite_master WHERE name='future'"
        ) as cursor:
            assert await cursor.fetchone() is None


async def test_unknown_and_changed_migrations_refuse_start(tmp_path):
    path = tmp_path / "arena.sqlite3"
    async with Storage(
        path, (*MIGRATIONS, Migration(len(MIGRATIONS) + 1, "future", ("SELECT 1",)))
    ):
        pass
    with pytest.raises(MigrationError):
        async with Storage(path):
            pass
    with pytest.raises(MigrationError):
        async with Storage(path, (Migration(1, "changed", ("SELECT 1",)),)):
            pass


async def test_backup_includes_wal_and_restore_preserves_data(tmp_path):
    path, backup = tmp_path / "arena.sqlite3", tmp_path / "backup.sqlite3"
    async with Storage(path) as storage:
        await storage.put("test", "key", {"saved": True})
        # Snapshot uses SQLite backup rather than copying only the main file while WAL is active.
        snapshot(path, backup)
        await storage.put("test", "key", "changed")
    with pytest.raises(FileExistsError):
        snapshot(path, backup)
    await restore(backup, path)
    async with Storage(path) as storage:
        assert await storage.get("test", "key") == {"saved": True}


async def test_incompatible_restore_keeps_original_data(tmp_path):
    path, newer = tmp_path / "arena.sqlite3", tmp_path / "newer.sqlite3"
    async with Storage(path) as storage:
        await storage.put("test", "original", True)
    async with Storage(
        newer, (*MIGRATIONS, Migration(len(MIGRATIONS) + 1, "future", ("SELECT 1",)))
    ):
        pass
    with pytest.raises(MigrationError):
        await restore(newer, path)
    async with Storage(path) as storage:
        assert await storage.get("test", "original") is True


async def test_corrupt_and_unrelated_snapshots_do_not_replace_database(tmp_path):
    path = tmp_path / "arena.sqlite3"
    async with Storage(path) as storage:
        await storage.put("test", "original", True)
    unrelated = tmp_path / "unrelated.sqlite3"
    with sqlite3.connect(unrelated) as db:
        db.execute("CREATE TABLE unrelated(id INTEGER)")
    with pytest.raises(MigrationError):
        await restore(unrelated, path)
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        await restore(corrupt, path)
    async with Storage(path) as storage:
        assert await storage.get("test", "original") is True


def test_process_lock_blocks_maintenance_and_other_process(tmp_path):
    with process_lock(tmp_path):
        with pytest.raises(AlreadyRunning):
            with process_lock(tmp_path):
                pass
        result = subprocess.run(
            [sys.executable, "-m", "argument_arena", "--data-dir", str(tmp_path), "migrate"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        assert result.returncode == 1
        assert "AlreadyRunning" in result.stdout
    with process_lock(tmp_path):
        pass
