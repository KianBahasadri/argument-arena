"""Deterministic chronological Elo replay, including corrections and repeat limits."""

import json

from argument_arena.repository import encode


async def replay(unit, guild, now):
    rows = await unit.rows(
        "SELECT * FROM results WHERE guild=? ORDER BY created,match_id", (guild,)
    )
    ratings, repeats = {}, {}
    for row in rows:
        result = json.loads(row["data"])
        match = await unit.match(row["match_id"])
        policy = match["rating_policy"]
        pair = (tuple(sorted(match["players"])), int(row["created"] // 86400))
        eligible = (
            match["settings"]["ranked"]["enabled"]
            and result["outcome"] in {"judged", "draw", "concession", "forfeit"}
            and not result.get("review_needed")
            and all(match["turn_counts"].get(p, 0) >= 1 for p in match["players"])
            and repeats.get(pair, 0) < policy["repeat_opponent_daily"]
        )
        old = await unit.rows("SELECT * FROM rating_changes WHERE match_id=?", (match["id"],))
        previous = {r["user_id"]: (r["before"], r["after"]) for r in old}
        await unit.db.execute("DELETE FROM rating_changes WHERE match_id=?", (match["id"],))
        changes = {}
        if eligible:
            repeats[pair] = repeats.get(pair, 0) + 1
            a, b = match["players"]
            ra, rb = (ratings.get(p, policy["rating_initial"]) for p in (a, b))
            score = 0.5 if result["winner"] is None else float(result["winner"] == a)
            exponent = max(-100, min(100, (rb - ra) / 400))
            delta = policy["rating_k"] * (score - 1 / (1 + 10**exponent))
            for player, before, after in ((a, ra, ra + delta), (b, rb, rb - delta)):
                ratings[player] = after
                changes[player] = (before, after)
                await unit.db.execute(
                    "INSERT INTO rating_changes VALUES(?,?,?,?,?)",
                    (
                        match["id"],
                        player,
                        before,
                        after,
                        f"Elo replay; result revision {row['revision']}; {result['outcome']}",
                    ),
                )
        result["rated"] = eligible
        result["rating_changes"] = changes
        await unit.db.execute(
            "UPDATE results SET data=? WHERE match_id=?", (encode(result), match["id"])
        )
        if previous != changes:
            await unit.event(
                match["id"], "rating_correction", None, {"before": previous, "after": changes}, now
            )
    await unit.save("ratings", guild, ratings)


async def leaderboard(repo, guild, topic="", since=0, format_name="", minimum=1):
    async with repo.unit() as unit:
        rows = await unit.rows("SELECT * FROM results WHERE guild=? AND created>=?", (guild, since))
        ratings = await unit.document("ratings", guild, {})
        records = {}
        for row in rows:
            match = await unit.match(row["match_id"])
            result = json.loads(row["data"])
            if not result.get("rated") or topic.casefold() not in match["topic"].casefold():
                continue
            if format_name and match["settings"]["ranked"]["preset"] != format_name:
                continue
            for player in match["players"]:
                record = records.setdefault(
                    player,
                    {
                        "user": player,
                        "rating": ratings[player],
                        "wins": 0,
                        "losses": 0,
                        "draws": 0,
                        "forfeits": 0,
                        "matches": [],
                    },
                )
                record["matches"].append(result["link"])
                label = (
                    "draws"
                    if result["winner"] is None
                    else ("wins" if result["winner"] == player else "losses")
                )
                record[label] += 1
                if result["outcome"] == "forfeit" and result["winner"] != player:
                    record["forfeits"] += 1
        return sorted(
            (r for r in records.values() if len(r["matches"]) >= minimum),
            key=lambda r: (-r["rating"], r["user"]),
        )
