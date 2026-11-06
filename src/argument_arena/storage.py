"""Async SQLite transactions, append-only migrations, and namespaced JSON settings."""

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256("\n".join(self.statements).encode()).hexdigest()


MIGRATIONS = (
    Migration(
        1,
        "foundation_settings",
        (
            "CREATE TABLE settings (namespace TEXT NOT NULL, key TEXT NOT NULL, "
            "value_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "PRIMARY KEY(namespace, key))",
        ),
    ),
)


class Storage:
    def __init__(self, path: Path, migrations: Sequence[Migration] = MIGRATIONS) -> None:
        self.path = path
        self.migrations = migrations
        self._connection: aiosqlite.Connection | None = None
        self._mutex = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("Storage is not open")
        return self._connection

    async def __aenter__(self) -> "Storage":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path, isolation_level=None)
        try:
            await self.connection.execute("PRAGMA journal_mode=WAL")
            await self.connection.execute("PRAGMA foreign_keys=ON")
            await self.connection.execute("PRAGMA busy_timeout=5000")
            await self._migrate()
        except BaseException:
            await self._connection.close()
            self._connection = None
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.connection.close()
        self._connection = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Serialize transactions; rollback on exceptions or cancellation. Do not nest."""
        async with self._mutex:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except BaseException:
                await self.connection.rollback()
                raise
            else:
                await self.connection.commit()

    async def _migrate(self) -> None:
        if [m.version for m in self.migrations] != list(range(1, len(self.migrations) + 1)):
            raise MigrationError("Migrations must be ordered and contiguous starting at one")
        async with self.transaction() as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL)"
            )
            async with db.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ) as cursor:
                applied = await cursor.fetchall()
            expected = [(m.version, m.name, m.checksum) for m in self.migrations]
            if applied != expected[: len(applied)]:
                raise MigrationError(
                    "Database schema is newer than this build or migrations changed"
                )
            for migration in self.migrations[len(applied) :]:
                for statement in migration.statements:
                    await db.execute(statement)
                await db.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) VALUES (?, ?, ?)",
                    (migration.version, migration.name, migration.checksum),
                )

    async def get(self, namespace: str, key: str, default: Any = None) -> Any:
        async with self._mutex:
            async with self.connection.execute(
                "SELECT value_json FROM settings WHERE namespace=? AND key=?", (namespace, key)
            ) as cursor:
                row = await cursor.fetchone()
        return default if row is None else json.loads(row[0])

    async def put(self, namespace: str, key: str, value: Any) -> None:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        async with self.transaction() as db:
            await db.execute(
                "INSERT INTO settings(namespace, key, value_json) VALUES (?, ?, ?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET "
                "value_json=excluded.value_json, updated_at=CURRENT_TIMESTAMP",
                (namespace, key, encoded),
            )

    async def check(self) -> None:
        async with self._mutex:
            async with self.connection.execute("SELECT 1") as cursor:
                await cursor.fetchone()


def snapshot(source: Path, destination: Path) -> None:
    """Consistent SQLite backup, including WAL contents, without overwriting a backup."""
    if destination.exists():
        raise FileExistsError("Backup destination already exists")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as original:
        with destination.open("xb"):
            pass
        try:
            with sqlite3.connect(destination) as backup:
                original.backup(backup)
                if backup.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise MigrationError("Snapshot integrity check failed")
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


async def restore(source: Path, destination: Path) -> None:
    """Validate/migrate a staged backup before atomically replacing stopped bot state."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "restored.sqlite3"
        await asyncio.to_thread(snapshot, source, staged)
        with sqlite3.connect(staged) as candidate:
            try:
                recorded = candidate.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()
            except sqlite3.DatabaseError:
                raise MigrationError("Snapshot is not an Argument Arena database") from None
            if not recorded or recorded[0] == 0:
                raise MigrationError("Snapshot has no recorded Argument Arena schema")
        async with Storage(staged):
            pass
        # The caller must hold process_lock: no open readers/writers or active WAL files.
        for suffix in ("-wal", "-shm"):
            Path(str(destination) + suffix).unlink(missing_ok=True)
        os.replace(staged, destination)
