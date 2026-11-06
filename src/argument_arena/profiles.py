"""Evidence-linked, revocable observations of opted-in managed debate activity only."""

import json

from argument_arena.curriculum import find_fallacy
from argument_arena.settings import ArenaError


def preferences():
    return {
        "analysis": False,
        "visibility": "private",
        "training": False,
        "recommendations": True,
        "since": 0,
        "removed_before": 0,
    }


class Profiles:
    def __init__(self, arena):
        self.arena, self.repo = arena, arena.repo

    async def settings(self, actor, patch=None):
        key = f"{actor.guild}:{actor.id}"
        async with self.repo.unit() as unit:
            prefs = await unit.document("profile_prefs", key, preferences())
            if patch:
                if set(patch) - {"analysis", "visibility", "training", "recommendations"}:
                    raise ArenaError("Unknown profile preference.")
                for name, value in patch.items():
                    if name == "visibility":
                        if value not in {"private", "public"}:
                            raise ArenaError("Choose private or public visibility.")
                    elif type(value) is not bool:
                        raise ArenaError("Profile switches must be true or false.")
                if patch.get("analysis") and not prefs["analysis"]:
                    prefs["since"] = self.arena.clock()
                prefs.update(patch)
                await unit.save("profile_prefs", key, prefs)
            return prefs

    async def generate(self, match_id):
        now = self.arena.clock()
        async with self.repo.unit() as unit:
            match = await unit.match(match_id)
            result_row = await unit.one("SELECT * FROM results WHERE match_id=?", (match_id,))
            if not result_row or not match["settings"]["profiles"]["enabled"]:
                return
            result = json.loads(result_row["data"])
            claims = [
                json.loads(r["data"])
                for r in await unit.rows("SELECT data FROM claims WHERE match_id=?", (match_id,))
            ]
            for player, position in zip(match["players"], match["positions"], strict=True):
                key = f"{match['guild']}:{player}"
                prefs = await unit.document("profile_prefs", key, preferences())
                insight_id = f"{key}:{match_id}"
                if (
                    not prefs["analysis"]
                    or match["created"] < prefs["since"]
                    or match["created"] <= prefs["removed_before"]
                    or result.get("review_needed")
                ):
                    if result.get("review_needed"):
                        await unit.db.execute(
                            "DELETE FROM documents WHERE kind='insight' AND id=?", (insight_id,)
                        )
                    continue
                attributed = [c for c in claims if c["author"] == player and not c["stale"]]
                report = (
                    (result.get("report") or {})
                    .get("participants", result.get("feedback", {}))
                    .get(player, {})
                )
                observations = {
                    "match": match_id,
                    "link": result["link"],
                    "topic": match["topic"],
                    "position": position,
                    "position_policy": "Position argued; does not establish personal belief.",
                    "created": match["created"],
                    "generated": now,
                    "sample_claims": len(attributed),
                    "themes": {
                        kind: sum(c["kind"] == kind for c in attributed)
                        for kind in (
                            "factual",
                            "value",
                            "opinion",
                            "definition",
                            "prediction",
                            "question",
                        )
                    },
                    "evidence": [
                        {
                            "claim": c["id"],
                            "url": c["url"],
                            "quote": c["quote"],
                            "kind": c["kind"],
                            "approaches": c.get("approaches", []),
                            "topics": c.get("topics", []),
                            "status": c["status"],
                        }
                        for c in attributed
                    ],
                    "topic_tags": sorted({t for c in attributed for t in c.get("topics", [])}),
                    "approach": {
                        **{
                            tag: sum(tag in c.get("approaches", []) for c in attributed)
                            for tag in (
                                "evidence",
                                "example",
                                "definition",
                                "principle",
                                "consequence",
                            )
                        },
                        "evidence_linked": sum(
                            bool(c["history"] and c["history"][-1].get("source_ids"))
                            for c in attributed
                        ),
                        "engagement_links": sum(len(c["relations"]) for c in attributed),
                    },
                    "strengths": report.get("strengths", []),
                    "needs": report.get("needs", []),
                    "practice": report.get("practice", []),
                    "scores": report.get("scores", {}),
                    "score_references": report.get("references", []),
                    "outcome": result["outcome"],
                }
                existing = await unit.document("insight", insight_id)
                if existing and "user_correction" in existing:
                    observations["user_correction"] = existing["user_correction"]
                if not (existing and existing.get("excluded")):
                    await unit.save("insight", insight_id, observations)

    async def view(self, actor, user):
        key = f"{actor.guild}:{user}"
        async with self.repo.unit() as unit:
            prefs = await unit.document("profile_prefs", key, preferences())
            if user != actor.id and prefs["visibility"] != "public":
                raise ArenaError("This profile is private.")
            rows = await unit.rows("SELECT id,data FROM documents WHERE kind='insight'")
            insights = [json.loads(r["data"]) for r in rows if r["id"].startswith(key + ":")]
            insights = sorted(
                (i for i in insights if not i.get("excluded")), key=lambda i: i["created"]
            )
            sample = len(insights)
            themes = {
                kind: sum(i["themes"][kind] for i in insights)
                for kind in ("factual", "value", "opinion", "definition", "prediction", "question")
            }
            needs = [need for i in insights for need in i["needs"]]
            practice = [name for i in insights for name in i["practice"] if find_fallacy(name)]
            progress = (
                await unit.document("training_progress", key, {"attempts": []})
                if prefs["training"]
                else None
            )
            competitive = await unit.document("ratings", actor.guild, {})
            result = {
                "current_competitive_rating": competitive.get(user),
                "record_command": "/match history (public records are separate from "
                "generated insights)",
                "user": user,
                "preferences": prefs,
                "sample_matches": sample,
                "sample_claims": sum(i["sample_claims"] for i in insights),
                "history": insights,
                "policy": "Managed opted-in matches only. Assigned positions are not"
                " personal beliefs.",
                "interests": [
                    {
                        "topic": i["topic"],
                        "tags": i.get("topic_tags", []),
                        "link": i["link"],
                        "at": i["created"],
                    }
                    for i in insights
                ],
                "approach": {
                    tag: sum(i["approach"].get(tag, 0) for i in insights)
                    for tag in (
                        "evidence",
                        "example",
                        "definition",
                        "principle",
                        "consequence",
                        "evidence_linked",
                        "engagement_links",
                    )
                }
                if sample >= 3
                else {},
                "themes": themes
                if sample >= 3
                else "At least 3 opted-in matches required for aggregate tendencies.",
                "strengths": [s for i in insights for s in i["strengths"]] if sample >= 3 else [],
                "practice_needs": needs if sample >= 3 else [],
                "recommendations": sorted(set(practice)) if prefs["recommendations"] else [],
                "practice_links": [
                    {
                        "name": entry.name,
                        "reference": entry.reference,
                        "command": f"/train fallacy name:{entry.name}",
                    }
                    for name in sorted(set(practice))
                    if prefs["recommendations"] and (entry := find_fallacy(name))
                ],
                "change_over_time": [
                    {
                        "match": i["match"],
                        "at": i["created"],
                        "scores": i["scores"],
                        "themes": i["themes"],
                        "evidence": i["score_references"],
                    }
                    for i in insights
                ],
                "training": {
                    "attempts": len(progress["attempts"]),
                    "recent": [
                        {
                            k: a[k]
                            for k in ("fallacy", "score", "created", "difficulty", "reference")
                        }
                        for a in progress["attempts"][-10:]
                    ],
                }
                if progress
                else "Not shared",
            }
            return result

    async def correct(self, actor, match_id, note, exclude=False):
        if not 5 <= len(note) <= 2000:
            raise ArenaError("Provide a correction of 5–2000 characters.")
        key = f"{actor.guild}:{actor.id}:{match_id}"
        async with self.repo.unit() as unit:
            insight = await unit.document("insight", key)
            if not insight:
                raise ArenaError("No generated observation for this match.")
            insight["user_correction"] = {"note": note, "at": self.arena.clock(), "by": actor.id}
            insight["excluded"] = exclude
            await unit.save("insight", key, insight)
            return (
                "Your correction is attached to the evidence; "
                "excluded observations leave aggregate analysis."
            )

    async def remove(self, actor):
        key = f"{actor.guild}:{actor.id}"
        async with self.repo.unit() as unit:
            rows = await unit.rows("SELECT id FROM documents WHERE kind='insight'")
            for row in rows:
                if row["id"].startswith(key + ":"):
                    await unit.db.execute(
                        "DELETE FROM documents WHERE kind='insight' AND id=?", (row["id"],)
                    )
            prefs = await unit.document("profile_prefs", key, preferences())
            prefs.update(analysis=False, removed_before=self.arena.clock())
            await unit.save("profile_prefs", key, prefs)
            return (
                "Generated insights removed and future analysis disabled. "
                "Old jobs cannot regenerate them."
            )
