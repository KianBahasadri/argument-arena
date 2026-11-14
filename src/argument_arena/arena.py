"""Durable debate state machine. Discord and provider requests never enter transactions."""

import json
import time
import uuid
from copy import deepcopy

from argument_arena.competition import replay
from argument_arena.repository import Repository, encode
from argument_arena.settings import (
    Actor,
    ArenaError,
    match_settings,
    server_defaults,
    validate_server,
)

OPEN = {"challenge", "starting", "active", "paused", "judging"}


def identity():
    return uuid.uuid4().hex[:12]


def participant(match, actor):
    if actor.id not in match["players"] or actor.bot:
        raise ArenaError("Only the two participants can perform this action.")


def require_staff(actor, config):
    if not actor.staff(config):
        raise ArenaError("Administrator or a configured moderator role required.")


class Arena:
    def __init__(self, storage, clock=time.time):
        self.repo = Repository(storage)
        self.clock = clock

    async def config(self, guild):
        async with self.repo.unit() as unit:
            return await unit.document("guild", guild, server_defaults())

    async def setup(self, actor: Actor, patch: dict):
        if not actor.admin:
            raise ArenaError("Administrator permission required for server configuration.")
        async with self.repo.unit() as unit:
            config = await unit.document("guild", actor.guild, server_defaults())
            for key, value in patch.items():
                if key in {"defaults", "presets", "categories"} and isinstance(value, dict):
                    if key == "defaults":
                        config[key] = match_settings(value, config[key])
                    else:
                        config[key].update(deepcopy(value))
                else:
                    config[key] = deepcopy(value)
            config = validate_server(config)
            await unit.save("guild", actor.guild, config)
            for row in await unit.rows(
                "SELECT id FROM matches WHERE guild=? AND channel IS NOT NULL", (actor.guild,)
            ):
                await unit.job(
                    f"server-permissions:{row['id']}:{self.clock()}",
                    "permissions",
                    row["id"],
                    {},
                    self.clock(),
                )
            await unit.event(f"guild:{actor.guild}", "setup", actor.id, patch, self.clock())
            return config

    async def challenge(self, actor, opponent, topic, positions, origin, preset="default"):
        if actor.bot or opponent == actor.id or not opponent.isdecimal():
            raise ArenaError("Choose another human server member.")
        if (
            not 3 <= len(topic) <= 500
            or len(positions) != 2
            or any(not isinstance(p, str) or not 1 <= len(p) <= 500 for p in positions)
        ):
            raise ArenaError("Supply a topic (3–500 characters) and two positions (1–500 each).")
        now = self.clock()
        async with self.repo.unit() as unit:
            config = await unit.document("guild", actor.guild, server_defaults())
            if not config["categories"]["active"]:
                raise ArenaError("An administrator must run /setup with an active category first.")
            if preset not in config["presets"] and preset != "default":
                raise ArenaError("Unknown preset. View /settings server.")
            recent = await unit.document("challenge_clock", f"{actor.guild}:{actor.id}", 0)
            if now - recent < config["challenge_cooldown"]:
                raise ArenaError("Challenge cooldown active; try again shortly.")
            rows = await unit.rows(
                "SELECT data FROM matches WHERE guild=? AND state!='closed'", (actor.guild,)
            )
            for player in (actor.id, opponent):
                count = sum(player in json.loads(row["data"])["players"] for row in rows)
                if count >= config["max_concurrent"]:
                    raise ArenaError("A participant has reached the concurrent match limit.")
            settings = match_settings(
                config["defaults"] if preset == "default" else config["presets"][preset]
            )
            match = {
                "id": config["match_prefix"] + identity(),
                "guild": actor.guild,
                "players": [actor.id, opponent],
                "topic": topic,
                "positions": positions,
                "origin": origin,
                "state": "challenge",
                "created": now,
                "settings": settings,
                "revision": 1,
                "confirmed": [],
                "channel": None,
                "next": None,
                "deadline": None,
                "remaining": None,
                "turn": 0,
                "turn_counts": {actor.id: 0, opponent: 0},
                "message_count": 0,
                "transcript_version": 0,
                "analysis_version": 0,
                "proposal": None,
                "on_demand_count": 0,
                "research_count": 0,
                "archived": False,
                "vote_until": None,
                "votes": {},
                "rating_policy": {
                    k: config[k] for k in ("rating_initial", "rating_k", "repeat_opponent_daily")
                },
            }
            await unit.save_match(match)
            await unit.save("challenge_clock", f"{actor.guild}:{actor.id}", now)
            await unit.event(match["id"], "challenge", actor.id, match, now)
            await unit.notice(
                match,
                f"challenge:{match['id']}",
                f"Challenge {match['id']}: {topic}. Both members must review "
                "and accept the current revision with /match accept.",
                now,
                destination=config["announcement"],
            )
            return match

    async def settings(self, actor, match_id, patch=None, positions=None):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            if patch is None and positions is None:
                return match
            participant(match, actor)
            if match["state"] != "challenge":
                raise ArenaError("Accepted rules are locked. Start a new match to change them.")
            match["settings"] = match_settings(patch, match["settings"])
            if positions is not None:
                if len(positions) != 2 or any(not 1 <= len(p) <= 500 for p in positions):
                    raise ArenaError("Supply exactly two nonempty positions, up to 500 characters.")
                match["positions"] = positions
            match["revision"] += 1
            match["confirmed"] = []
            await unit.save_match(match)
            await unit.event(
                match_id,
                "settings",
                actor.id,
                {
                    "revision": match["revision"],
                    "settings": match["settings"],
                    "positions": match["positions"],
                },
                self.clock(),
            )
            return match

    async def accept(self, actor, match_id, revision):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            participant(match, actor)
            if match["state"] != "challenge":
                raise ArenaError("This challenge is no longer awaiting acceptance.")
            if revision != match["revision"]:
                raise ArenaError("Settings changed. Review and confirm the current revision.")
            if actor.id not in match["confirmed"]:
                match["confirmed"].append(actor.id)
            if set(match["confirmed"]) == set(match["players"]):
                match["state"] = "starting"
                await unit.job(f"create:{match_id}", "create", match_id, {}, self.clock())
            await unit.save_match(match)
            await unit.event(match_id, "accept", actor.id, {"revision": revision}, self.clock())
            return match

    async def attach_channel(self, match_id, channel):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id)
            if match["state"] != "starting":
                return
            match["channel"] = channel
            match["state"] = "active"
            if match["settings"]["turns"]["enabled"]:
                self._speaker(match, match["players"][match["settings"]["turns"]["first"]])
            await unit.save_match(match)
            await unit.event(match_id, "started", None, {"channel": channel}, self.clock())
            await unit.notice(
                match,
                f"start:{match_id}",
                f"Match {match_id} started. Topic: {match['topic']}\n"
                f"Positions: {match['positions']}\nOrigin: {match['origin']}\n"
                f"Settings revision {match['revision']}: "
                f"{encode(match['settings'])}\nNext: {match['next']}; "
                f"deadline: {match['deadline']}",
                self.clock(),
            )

    def _speaker(self, match, player):
        match["next"] = player
        match["deadline"] = (
            self.clock() + match["settings"]["inactivity"]["hours"] * 3600
            if match["settings"]["inactivity"]["enabled"]
            else None
        )
        match["reminded"] = False

    async def _advance(self, unit, match, player):
        match["turn"] += 1
        match["turn_counts"][player] += 1
        opponent = next(p for p in match["players"] if p != player)
        if match["settings"]["turns"]["enabled"]:
            self._speaker(match, opponent)
        elif match["next"] is None or match["next"] == player:
            match["next"], match["deadline"] = None, None
            match["reminded"] = False
        limits = match["settings"]["limits"]
        if limits["enabled"] and (
            match["turn"] >= limits["rounds"] * 2 or match["message_count"] >= limits["messages"]
        ):
            await self._finish(unit, match)
        else:
            await unit.notice(
                match,
                f"turn:{match['id']}:{match['turn']}",
                f"Turn {match['turn']} complete. Next: {match['next']}; "
                f"deadline: {match['deadline']}. Use /match status for exact time.",
                self.clock(),
            )

    async def message(self, guild, channel, message_id, author, content, url, created, bot=False):
        if bot or not content.strip():
            return False
        async with self.repo.unit() as unit:
            row = await unit.one(
                "SELECT data FROM matches WHERE guild=? AND channel=?", (guild, channel)
            )
            if not row:
                return False  # Threads have different IDs and cannot enter the transcript.
            match = json.loads(row["data"])
            if match["state"] != "active" or author not in match["players"]:
                return False
            if await unit.one("SELECT id FROM messages WHERE id=?", (message_id,)):
                return False
            limits = match["settings"]["limits"]
            if limits["enabled"] and len(content) > limits["characters"]:
                await unit.notice(
                    match,
                    f"length:{message_id}",
                    "Message exceeds the agreed length limit; it was excluded. "
                    "Resubmit a shorter turn.",
                    self.clock(),
                )
                return False
            turns = match["settings"]["turns"]
            if turns["enabled"] and match["next"] != author:
                await unit.notice(
                    match,
                    f"order:{message_id}",
                    "Out-of-turn message excluded. The required speaker and "
                    "deadline are unchanged.",
                    self.clock(),
                )
                return False
            await unit.db.execute(
                "INSERT INTO messages(id,match_id,author,content,url,created) VALUES(?,?,?,?,?,?)",
                (message_id, match["id"], author, content, url, created),
            )
            await unit.db.execute(
                "INSERT INTO message_versions VALUES(?,1,?,0,?)",
                (message_id, content, self.clock()),
            )
            match["message_count"] += 1
            match["transcript_version"] += 1
            await unit.job(
                f"analyze:{message_id}:1",
                "analyze",
                match["id"],
                {"message": message_id, "revision": 1, "sequence": match["message_count"]},
                self.clock(),
            )
            if turns["structure"] == "message" or not turns["enabled"]:
                await self._advance(unit, match, author)
            elif limits["enabled"] and match["message_count"] >= limits["messages"]:
                await self._finish(unit, match)
            await unit.save_match(match)
            return True

    async def submit(self, actor, match_id):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            participant(match, actor)
            if match["state"] != "active" or match["next"] != actor.id:
                raise ArenaError("You are not the required speaker in an active match.")
            if match["settings"]["turns"]["structure"] != "submit":
                raise ArenaError("This match advances automatically on a qualifying message.")
            row = await unit.one(
                "SELECT id FROM messages WHERE match_id=? AND author=? "
                "AND deleted=0 ORDER BY created DESC LIMIT 1",
                (match_id, actor.id),
            )
            if not row or row["id"] in match.get("submitted", []):
                raise ArenaError("Post a new official message before submitting your turn.")
            match.setdefault("submitted", []).append(row["id"])
            await self._advance(unit, match, actor.id)
            await unit.save_match(match)
            return match

    async def edit_message(self, message_id, content=None, deleted=False):
        async with self.repo.unit() as unit:
            row = await unit.one("SELECT * FROM messages WHERE id=?", (message_id,))
            if not row or (
                deleted == bool(row["deleted"]) and (content is None or content == row["content"])
            ):
                return
            revision = row["revision"] + 1
            content = row["content"] if content is None else content
            await unit.db.execute(
                "UPDATE messages SET content=?,deleted=?,revision=? WHERE id=?",
                (content, int(deleted), revision, message_id),
            )
            await unit.db.execute(
                "INSERT INTO message_versions VALUES(?,?,?,?,?)",
                (message_id, revision, content, int(deleted), self.clock()),
            )
            match = await unit.match(row["match_id"])
            match["transcript_version"] += 1
            for claim in await unit.rows(
                "SELECT id,data FROM claims WHERE message_id=?", (message_id,)
            ):
                data = json.loads(claim["data"])
                data["stale"] = True
                data["status"] = "source_deleted" if deleted else "source_edited"
                await unit.db.execute(
                    "UPDATE claims SET data=? WHERE id=?", (encode(data), claim["id"])
                )
            if not deleted:
                await unit.job(
                    f"analyze:{message_id}:{revision}",
                    "analyze",
                    match["id"],
                    {"message": message_id, "revision": revision},
                    self.clock(),
                )
            await unit.event(
                match["id"],
                "message_changed",
                row["author"],
                {"message": message_id, "revision": revision, "deleted": deleted},
                self.clock(),
            )
            result_row = await unit.one("SELECT data FROM results WHERE match_id=?", (match["id"],))
            if result_row:
                result = json.loads(result_row["data"])
                result["review_needed"] = True
                for player in match["players"]:
                    await unit.db.execute(
                        "DELETE FROM documents WHERE kind='insight' AND id=?",
                        (f"{match['guild']}:{player}:{match['id']}",),
                    )
                await unit.db.execute(
                    "UPDATE results SET data=? WHERE match_id=?", (encode(result), match["id"])
                )
                await replay(unit, match["guild"], self.clock())
            await unit.save_match(match)
            await unit.notice(
                match,
                f"edited:{message_id}:{revision}",
                "Official message changed or deleted. Previous claims/checks are "
                "marked stale; completed results require staff review. Clocks do not reset.",
                self.clock(),
            )

    async def action(self, actor, match_id, action, data=None):
        data = data or {}
        now = self.clock()
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            config = await unit.document("guild", actor.guild, server_defaults())
            staff = actor.staff(config)
            if not staff:
                participant(match, actor)
            if match["state"] == "closed":
                raise ArenaError("Match already closed; use staff correction for result review.")
            if action == "decline":
                participant(match, actor)
                if match["state"] != "challenge":
                    raise ArenaError("Only pending challenges can be declined.")
                await self._close(unit, match, "cancelled", None, "Challenge declined")
            elif action == "concede":
                participant(match, actor)
                if match["state"] not in {"active", "paused"}:
                    raise ArenaError("Concession requires an active or paused match.")
                await self._close(
                    unit,
                    match,
                    "concession",
                    next(p for p in match["players"] if p != actor.id),
                    "Conceded",
                )
            elif action in {"pause", "resume", "extend", "draw", "finish", "cancel", "request"}:
                allowed = {
                    "resume": {"paused"},
                    "pause": {"active"},
                    "request": {"active"},
                    "extend": {"active", "paused"},
                    "finish": {"active", "paused"},
                    "draw": {"active", "paused"},
                    "cancel": OPEN,
                }
                if match["state"] not in allowed[action]:
                    raise ArenaError(f"Cannot {action} a {match['state']} match.")
                if action == "extend" and (
                    type(data.get("hours")) is not int or not 1 <= data["hours"] <= 168
                ):
                    raise ArenaError("Extension hours must be an integer from 1 to 168.")
                if action == "request" and (
                    match["settings"]["turns"]["enabled"]
                    or data.get("speaker") not in match["players"]
                ):
                    raise ArenaError(
                        "Flexible matches require an explicit participant response request."
                    )
                proposal = match["proposal"]
                if not staff and not (
                    proposal
                    and proposal["action"] == action
                    and proposal["data"] == data
                    and proposal["by"] != actor.id
                ):
                    match["proposal"] = {"action": action, "data": data, "by": actor.id}
                    await unit.notice(
                        match,
                        f"proposal:{match_id}:{identity()}",
                        f"{actor.id} proposes {action}: {data}. The opponent must "
                        "issue the identical action to agree.",
                        now,
                    )
                else:
                    match["proposal"] = None
                    if action == "pause":
                        match["remaining"] = (
                            max(0, match["deadline"] - now) if match["deadline"] else None
                        )
                        match["deadline"] = None
                        match["state"] = "paused"
                    elif action == "resume":
                        match["state"] = "active"
                        match["deadline"] = (
                            now + match["remaining"] if match["remaining"] is not None else None
                        )
                    elif action == "extend":
                        if match["deadline"] is not None:
                            match["deadline"] += data["hours"] * 3600
                        elif match["remaining"] is not None:
                            match["remaining"] += data["hours"] * 3600
                        else:
                            raise ArenaError("No response deadline to extend.")
                        match["reminded"] = False
                    elif action == "request":
                        self._speaker(match, data["speaker"])
                    elif action == "finish":
                        await self._finish(unit, match)
                    else:
                        await self._close(
                            unit,
                            match,
                            "draw" if action == "draw" else "cancelled",
                            None,
                            "Agreed or staff action",
                        )
            else:
                raise ArenaError("Unknown lifecycle action.")
            await unit.save_match(match)
            if match["channel"]:
                await unit.job(
                    f"permissions:{match_id}:{now}:{match['state']}",
                    "permissions",
                    match_id,
                    {},
                    now,
                )
            await unit.event(
                match_id,
                action,
                actor.id,
                {"data": data, "staff": staff, "pending": match["proposal"] is not None},
                now,
            )
            return match

    async def _finish(self, unit, match):
        match["deadline"] = None
        if match["settings"]["judging"]["enabled"]:
            match["state"] = "judging"
            await unit.job(
                f"freeze:{match['id']}:{match['transcript_version']}",
                "permissions",
                match["id"],
                {},
                self.clock(),
            )
            await unit.job(
                f"judge:{match['id']}:{match['transcript_version']}:"
                f"{match.get('analysis_version', 0)}",
                "judge",
                match["id"],
                {},
                self.clock(),
            )
        else:
            await self._close(unit, match, "inconclusive", None, "Finished without judging")

    async def _close(self, unit, match, outcome, winner, reason, report=None):
        if match["state"] == "closed":
            return
        match["state"], match["next"], match["deadline"] = "closed", None, None
        match["proposal"] = None
        now = self.clock()
        match["vote_until"] = now + match["settings"]["audience"]["hours"] * 3600
        result = {
            "outcome": outcome,
            "winner": winner,
            "reason": reason,
            "report": report,
            "review_needed": False,
            "rated": False,
            "link": (
                f"https://discord.com/channels/{match['guild']}/{match['channel']}"
                if match["channel"]
                else match["origin"]
            ),
            "factual_truth": "No procedural or judging outcome proves a claim true.",
        }
        await unit.save_match(match)
        await unit.db.execute(
            "INSERT OR IGNORE INTO results VALUES(?,?,?,?,?)",
            (match["id"], match["guild"], now, 1, encode(result)),
        )
        await unit.event(match["id"], "closed", None, result, now)
        await replay(unit, match["guild"], now)
        await unit.notice(
            match,
            f"result:{match['id']}",
            f"Result {match['id']}: {outcome}; winner: {winner or 'none'}. {reason}. "
            "Use /match result for the report, evidence and rating changes. "
            "This result does not establish factual truth; audience votes are separate.",
            now,
        )
        config = await unit.document("guild", match["guild"], server_defaults())
        if config["results"]:
            await unit.notice(
                match,
                f"result-channel:{match['id']}",
                f"Result {match['id']}: {outcome}; winner {winner or 'none'}. {result['link']}",
                now,
                destination=config["results"],
            )
        # Closing always locks ordinary main-channel messages, even without automatic movement.
        await unit.job(
            f"close-channel:{match['id']}",
            "archive",
            match["id"],
            {"move": match["settings"]["archive"]["enabled"]},
            now,
        )
        await unit.job(f"profile:{match['id']}:1", "profile", match["id"], {}, now)
        if report is None and outcome != "cancelled" and match["settings"]["feedback"]["enabled"]:
            await unit.job(
                f"feedback-only:{match['id']}:{match['transcript_version']}",
                "feedback",
                match["id"],
                {},
                now,
            )

    async def judged(self, match_id, version, report):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id)
            if match["state"] != "judging":
                return False
            if match["transcript_version"] != version or match.get(
                "analysis_version", 0
            ) != report.get("analysis_version", 0):
                await unit.job(
                    f"judge:{match_id}:{match['transcript_version']}:"
                    f"{match.get('analysis_version', 0)}",
                    "judge",
                    match_id,
                    {},
                    self.clock(),
                )
                return False
            await self._close(
                unit,
                match,
                report["outcome"],
                report["winner"],
                "Accepted rubric: arena-v1",
                report,
            )
            return True

    async def correct(self, actor, match_id, outcome, winner, reason):
        if outcome not in {"judged", "draw", "concession", "forfeit", "cancelled", "inconclusive"}:
            raise ArenaError("Invalid outcome.")
        if len(reason.strip()) < 10:
            raise ArenaError("Give a review explanation of at least ten characters.")
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            config = await unit.document("guild", actor.guild, server_defaults())
            require_staff(actor, config)
            row = await unit.one("SELECT * FROM results WHERE match_id=?", (match_id,))
            if not row or (winner is not None and winner not in match["players"]):
                raise ArenaError("Choose a completed match and one of its participants.")
            if (outcome in {"draw", "cancelled", "inconclusive"}) != (winner is None):
                raise ArenaError(
                    "Wins require a winner; draws, cancellations and inconclusive results do not."
                )
            result = json.loads(row["data"])
            await unit.event(
                match_id,
                "result_amended",
                actor.id,
                {"previous": result, "reason": reason},
                self.clock(),
            )
            if result.get("review_needed"):
                result["report"] = None
                result.pop("feedback", None)
            result.update(
                outcome=outcome,
                winner=winner,
                reason=reason,
                review_needed=False,
                staff_review={"actor": actor.id, "at": self.clock()},
            )
            await unit.db.execute(
                "UPDATE results SET revision=revision+1,data=? WHERE match_id=?",
                (encode(result), match_id),
            )
            await replay(unit, actor.guild, self.clock())
            await unit.job(
                f"correct-archive:{match_id}:{row['revision'] + 1}",
                "archive",
                match_id,
                {"move": match["settings"]["archive"]["enabled"]},
                self.clock(),
            )
            await unit.job(
                f"profile:{match_id}:{row['revision'] + 1}", "profile", match_id, {}, self.clock()
            )
            await unit.notice(
                match,
                f"corrected:{match_id}:{row['revision'] + 1}",
                f"Staff amended result: {outcome}; winner {winner}. {reason}. "
                "Ratings have been replayed consistently.",
                self.clock(),
            )
            return result

    async def close_match(self, actor, match_id, outcome, winner, reason):
        if outcome not in {"judged", "draw", "concession", "forfeit", "cancelled", "inconclusive"}:
            raise ArenaError("Invalid outcome.")
        if len(reason.strip()) < 10:
            raise ArenaError("Give a staff review explanation of at least ten characters.")
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            config = await unit.document("guild", actor.guild, server_defaults())
            require_staff(actor, config)
            if match["state"] not in {"active", "paused", "judging"}:
                raise ArenaError("Staff closure requires an active, paused or judging match.")
            if winner is not None and winner not in match["players"]:
                raise ArenaError("Winner must be a participant.")
            if (outcome in {"draw", "cancelled", "inconclusive"}) != (winner is None):
                raise ArenaError("Choose a winner for decisive outcomes only.")
            await self._close(unit, match, outcome, winner, f"Staff review: {reason}")
            row = await unit.one("SELECT data FROM results WHERE match_id=?", (match_id,))
            result = json.loads(row["data"])
            result["staff_review"] = {"actor": actor.id, "at": self.clock()}
            await unit.db.execute(
                "UPDATE results SET data=? WHERE match_id=?", (encode(result), match_id)
            )
            await unit.event(
                match_id,
                "staff_closed",
                actor.id,
                {"outcome": outcome, "winner": winner, "reason": reason},
                self.clock(),
            )
            return result

    async def channel_missing(self, channel):
        async with self.repo.unit() as unit:
            row = await unit.one("SELECT data FROM matches WHERE channel=?", (channel,))
            if not row:
                return
            match = json.loads(row["data"])
            if match.get("channel_unavailable"):
                return
            match["channel_unavailable"] = True
            if match["state"] == "active":
                match["remaining"] = (
                    max(0, match["deadline"] - self.clock()) if match["deadline"] else None
                )
                match["deadline"], match["state"] = None, "paused"
                match["proposal"] = None
            await unit.save_match(match)
            await unit.event(
                match["id"],
                "channel_unavailable",
                None,
                {"policy": "Response clock paused; staff must resolve missing channel."},
                self.clock(),
            )

    async def tick(self, connected):
        """Conservatively compensate the full unobserved interval before checking clocks."""
        now = self.clock()
        async with self.repo.unit() as unit:
            previous = await unit.document("worker", "clock")
            if previous is None:
                earliest = await unit.one(
                    "SELECT MIN(created) AS at FROM matches WHERE state='active'"
                )
                previous = {
                    "at": earliest["at"] if earliest["at"] is not None else now,
                    "connected": False,
                }
            gap = max(0, now - previous["at"])
            outage = not connected or not previous["connected"] or gap > 60
            await unit.save("worker", "clock", {"at": now, "connected": connected})
            for row in await unit.rows(
                "SELECT data FROM matches WHERE state IN ('active','challenge')"
            ):
                match = json.loads(row["data"])
                if match["state"] == "challenge":
                    if now - match["created"] > 7 * 86400:
                        await self._close(
                            unit, match, "cancelled", None, "Challenge expired after 7 days"
                        )
                elif match["deadline"] is not None:
                    if outage:
                        match["deadline"] += gap
                        if gap > 60:
                            await unit.event(
                                match["id"], "outage_extension", None, {"seconds": gap}, now
                            )
                    if connected and not outage:
                        if now >= match["deadline"]:
                            winner = next(p for p in match["players"] if p != match["next"])
                            await self._close(
                                unit, match, "forfeit", winner, "Required response overdue"
                            )
                        elif match["settings"]["reminders"]["enabled"] and not match.get(
                            "reminded"
                        ):
                            if (
                                now
                                >= match["deadline"]
                                - match["settings"]["reminders"]["before_hours"] * 3600
                            ):
                                match["reminded"] = True
                                await unit.notice(
                                    match,
                                    f"reminder:{match['id']}:{match['turn']}:{match['deadline']}",
                                    f"Response due from {match['next']} at"
                                    f" {match['deadline']} UTC epoch.",
                                    now,
                                    user=match["next"]
                                    if match["settings"]["reminders"]["delivery"] == "private"
                                    else None,
                                )
                await unit.save_match(match)

    async def result(self, match_id, guild):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, guild)
            row = await unit.one("SELECT data FROM results WHERE match_id=?", (match_id,))
            if not row:
                return {
                    "state": match["state"],
                    "message": "No completed result; judging may be pending or unavailable.",
                }
            data = json.loads(row["data"])
            data["audience_votes"] = {
                p: list(match["votes"].values()).count(p) for p in match["players"]
            }
            return data

    async def history(self, guild, user, topic="", since=0):
        records = []
        stats = {
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "forfeits": 0,
            "cancelled": 0,
            "inconclusive": 0,
        }
        async with self.repo.unit() as unit:
            for row in await unit.rows(
                "SELECT data FROM matches WHERE guild=? AND created>=? ORDER BY created DESC,id",
                (guild, since),
            ):
                match = json.loads(row["data"])
                if (
                    user not in match["players"]
                    or topic.casefold() not in match["topic"].casefold()
                ):
                    continue
                result_row = await unit.one(
                    "SELECT data FROM results WHERE match_id=?", (match["id"],)
                )
                result = json.loads(result_row["data"]) if result_row else {}
                outcome, winner = result.get("outcome"), result.get("winner")
                if outcome in {"cancelled", "inconclusive"}:
                    stats[outcome] += 1
                elif outcome:
                    stats[
                        "draws" if winner is None else "wins" if winner == user else "losses"
                    ] += 1
                    if outcome == "forfeit" and winner != user:
                        stats["forfeits"] += 1
                records.append(
                    {
                        "match": match["id"],
                        "state": match["state"],
                        "topic": match["topic"],
                        "positions": match["positions"],
                        "created": match["created"],
                        "outcome": outcome,
                        "winner": winner,
                        "rated": result.get("rated", False),
                        "link": result.get(
                            "link",
                            f"https://discord.com/channels/{guild}/{match['channel']}"
                            if match["channel"]
                            else match["origin"],
                        ),
                        "rating_change": result.get("rating_changes", {}).get(user),
                    }
                )
        return {
            "user": user,
            "statistics": stats,
            "matches": records,
            "policy": "Public managed-match record, separate from optional generated "
            "profile analysis.",
        }

    async def vote(self, actor, match_id, player):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            settings = match["settings"]["audience"]
            if actor.bot or not settings["enabled"] or player not in match["players"]:
                raise ArenaError("Audience voting is disabled or the choice is invalid.")
            if settings["eligibility"] == "spectators" and actor.id in match["players"]:
                raise ArenaError("This poll is for spectators.")
            if match["state"] != "closed" or self.clock() > match["vote_until"]:
                raise ArenaError(
                    "Audience voting opens after closure for the agreed voting window."
                )
            match["votes"][actor.id] = player
            await unit.save_match(match)
            return "Audience vote saved separately from judging and ratings."

    async def retry(self, actor, match_id):
        async with self.repo.unit() as unit:
            await unit.match(match_id, actor.guild)
            config = await unit.document("guild", actor.guild, server_defaults())
            require_staff(actor, config)
            await unit.db.execute(
                "UPDATE jobs SET state='pending',due=?,lease=NULL,attempts=0 "
                "WHERE match_id=? AND state='failed'",
                (self.clock(), match_id),
            )
            return "Failed jobs queued for retry. Usage budgets still apply."
