"""Small SQL repository. Each unit of work uses the foundation's serialized transaction."""

import json
from contextlib import asynccontextmanager

from argument_arena.settings import ArenaError


def encode(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


class Unit:
    def __init__(self, db):
        self.db = db

    async def rows(self, sql, args=()):
        async with self.db.execute(sql, args) as cursor:
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in await cursor.fetchall()]

    async def one(self, sql, args=()):
        rows = await self.rows(sql, args)
        return rows[0] if rows else None

    async def document(self, kind, key, default=None):
        row = await self.one("SELECT data FROM documents WHERE kind=? AND id=?", (kind, key))
        return json.loads(row["data"]) if row else default

    async def save(self, kind, key, data):
        await self.db.execute(
            "INSERT INTO documents(kind,id,data) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
            (kind, key, encode(data)),
        )

    async def match(self, match_id, guild=None):
        row = await self.one("SELECT data FROM matches WHERE id=?", (match_id,))
        if row is None:
            raise ArenaError("Match not found.")
        match = json.loads(row["data"])
        if guild is not None and match["guild"] != guild:
            raise ArenaError("Match belongs to another server.")
        return match

    async def save_match(self, match):
        await self.db.execute(
            "INSERT INTO matches(id,guild,channel,state,created,data) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET channel=excluded.channel,state=excluded.state,"
            "data=excluded.data",
            (
                match["id"],
                match["guild"],
                match.get("channel"),
                match["state"],
                match["created"],
                encode(match),
            ),
        )

    async def event(self, match, kind, actor, data, now):
        await self.db.execute(
            "INSERT INTO events(match_id,kind,actor,data,created) VALUES(?,?,?,?,?)",
            (match, kind, actor, encode(data), now),
        )

    async def job(self, key, kind, match, data, now):
        await self.db.execute(
            "INSERT OR IGNORE INTO jobs(id,kind,match_id,data,due) VALUES(?,?,?,?,?)",
            (key, kind, match, encode(data), now),
        )

    async def notice(self, match, key, text, now, user=None, destination=None, guard=None):
        await self.job(
            key,
            "notice",
            match["id"],
            {"text": text, "user": user, "destination": destination, "guard": guard},
            now,
        )

    async def use(self, key, limit):
        row = await self.one("SELECT count FROM usage WHERE id=?", (key,))
        if row and row["count"] >= limit:
            raise ArenaError("Usage budget reached; pending work can be retried after reset.")
        await self.db.execute(
            "INSERT INTO usage(id,count) VALUES(?,1) ON CONFLICT(id) DO UPDATE SET count=count+1",
            (key,),
        )


class Repository:
    def __init__(self, storage):
        self.storage = storage

    @asynccontextmanager
    async def unit(self):
        async with self.storage.transaction() as db:
            yield Unit(db)

    async def match(self, match_id, guild=None):
        async with self.unit() as unit:
            return await unit.match(match_id, guild)

    async def claim(self, claim_id, guild):
        async with self.unit() as unit:
            row = await unit.one("SELECT * FROM claims WHERE id=?", (claim_id,))
            if not row:
                raise ArenaError("Claim not found.")
            await unit.match(row["match_id"], guild)
            return json.loads(row["data"])

    async def jobs(self, now):
        async with self.unit() as unit:
            rows = await unit.rows(
                "SELECT * FROM jobs WHERE state IN ('pending','running') AND due<=? "
                "AND (lease IS NULL OR lease<=?) ORDER BY due,id LIMIT 10",
                (now, now),
            )
            for row in rows:
                await unit.db.execute(
                    "UPDATE jobs SET state='running',lease=?,attempts=attempts+1 WHERE id=?",
                    (now + 180, row["id"]),
                )
                row["data"] = json.loads(row["data"])
            return rows

    async def job_done(self, key):
        async with self.unit() as unit:
            await unit.db.execute("UPDATE jobs SET state='done',lease=NULL WHERE id=?", (key,))

    async def defer_job(self, key, now, seconds=15):
        async with self.unit() as unit:
            await unit.db.execute(
                "UPDATE jobs SET"
                " state='pending',lease=NULL,due=?,attempts=MAX(0,attempts-1) WHERE id=?",
                (now + seconds, key),
            )

    async def job_failed(self, key, now, status, retry=True):
        async with self.unit() as unit:
            row = await unit.one("SELECT attempts FROM jobs WHERE id=?", (key,))
            attempts = row["attempts"]
            await unit.db.execute(
                "UPDATE jobs SET state=?,lease=NULL,due=?,error=? WHERE id=?",
                (
                    "pending" if retry and attempts < 5 else "failed",
                    now + min(3600, 30 * 2**attempts),
                    status,
                    key,
                ),
            )
