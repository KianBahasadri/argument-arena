"""Attributed claim graphs, research revisions, moderation and auditable judging."""

import json

from argument_arena.arena import participant
from argument_arena.competition import replay
from argument_arena.curriculum import find_fallacy
from argument_arena.providers import ProviderError, model_response
from argument_arena.repository import encode
from argument_arena.settings import ArenaError, server_defaults

KINDS = {"factual", "value", "opinion", "definition", "prediction", "question"}
RELATIONS = {"supports", "rebuttal", "response", "concession", "revision", "objection"}
VERDICTS = {
    "supported",
    "contradicted",
    "partly supported",
    "disputed",
    "insufficient evidence",
    "not fact-checkable",
}


def text_value(value, maximum=5000):
    if not isinstance(value, str) or len(value) > maximum:
        raise ProviderError("invalid_model_response")
    return value


class Assistance:
    def __init__(self, arena, llm, research):
        self.arena, self.repo = arena, arena.repo
        self.llm, self.research = llm, research

    async def call(self, match, task, data, model="default"):
        now = self.arena.clock()
        async with self.repo.unit() as unit:
            config = await unit.document("guild", match["guild"], server_defaults())
            await unit.use(f"llm:{match['guild']}:{int(now // 86400)}", config["llm_daily"])
            await unit.use(f"llm-match:{match['id']}", config["llm_match"])
        if model == "default":
            model = config["llm_models"].get(task, "default")
        return await self.llm.complete(task, data, model)

    async def claims(self, match_id, guild):
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, guild)
            if not match["settings"]["claims"]["enabled"]:
                raise ArenaError("Public claim tracking is disabled for this match.")
            return [
                json.loads(r["data"])
                for r in await unit.rows(
                    "SELECT data FROM claims WHERE match_id=? ORDER BY id", (match_id,)
                )
            ]

    @model_response
    async def analyze(self, job):
        match = await self.repo.match(job["match_id"])
        settings = match["settings"]
        sequence = job["data"].get("sequence", match["message_count"])
        async with self.repo.unit() as unit:
            message = await unit.one("SELECT * FROM messages WHERE id=?", (job["data"]["message"],))
            existing = await unit.rows(
                "SELECT id,data FROM claims WHERE match_id=?", (match["id"],)
            )
            if await unit.document(
                "analysis_done", f"{job['data']['message']}:{job['data']['revision']}"
            ):
                return
        if not message or message["deleted"] or message["revision"] != job["data"]["revision"]:
            return
        async with self.repo.unit() as unit:
            from argument_arena.profiles import preferences

            prefs = await unit.document(
                "profile_prefs", f"{match['guild']}:{message['author']}", preferences()
            )
        profile_eligible = (
            settings["profiles"]["enabled"]
            and prefs["analysis"]
            and match["created"] >= prefs["since"]
            and match["created"] > prefs["removed_before"]
        )
        if not profile_eligible and not any(
            settings[f]["enabled"]
            for f in (
                "claims",
                "research",
                "on_demand",
                "fallacies",
                "coaching",
                "civility",
                "judging",
                "feedback",
            )
        ):
            return
        data = await self.call(
            match,
            "analyze",
            {
                "message": message,
                "settings": settings,
                "claims": [{"id": c["id"], "data": json.loads(c["data"])} for c in existing],
            },
        )
        extracted = data.get("claims", [])
        if not isinstance(extracted, list) or len(extracted) > 30:
            raise ProviderError("invalid_model_response")
        claims = []
        for index, item in enumerate(extracted, 1):
            if not isinstance(item, dict) or item.get("kind") not in KINDS:
                raise ProviderError("invalid_model_response")
            quote = text_value(item.get("quote"))
            if not quote or quote not in message["content"]:
                raise ProviderError("ungrounded_claim")
            relations = item.get("relations", [])
            if not isinstance(relations, list) or any(
                not isinstance(r, dict)
                or r.get("target") not in {c["id"] for c in existing}
                or r.get("type") not in RELATIONS
                for r in relations
            ):
                raise ProviderError("invalid_claim_relation")
            for tag, allowed in (
                ("approaches", {"evidence", "example", "definition", "principle", "consequence"}),
                (
                    "topics",
                    {
                        "ethics",
                        "politics",
                        "technology",
                        "engineering",
                        "science",
                        "art",
                        "culture",
                        "other",
                    },
                ),
            ):
                tags = item.get(tag, [])
                if not isinstance(tags, list) or any(
                    not isinstance(t, str) or t not in allowed for t in tags
                ):
                    raise ProviderError("invalid_analysis_tags")
            claim_id = f"C{message['id']}-{message['revision']}-{index}"
            claims.append(
                {
                    "id": claim_id,
                    "match": match["id"],
                    "message": message["id"],
                    "author": message["author"],
                    "url": message["url"],
                    "created": message["created"],
                    "quote": quote,
                    "summary": text_value(item.get("summary", quote)),
                    "kind": item["kind"],
                    "revision": message["revision"],
                    "relations": relations,
                    "approaches": item.get("approaches", []),
                    "topics": item.get("topics", []),
                    "stale": False,
                    "status": "pending"
                    if item["kind"] == "factual" and settings["research"]["enabled"]
                    else ("not fact-checkable" if item["kind"] != "factual" else "not_requested"),
                    "history": [],
                    "disputes": [],
                }
            )
        # Validate assistance before writing any of it.
        fallacies = data.get("fallacies", [])
        if not isinstance(fallacies, list) or len(fallacies) > 10:
            raise ProviderError("invalid_model_response")
        for finding in fallacies:
            if (
                not isinstance(finding, dict)
                or not finding.get("quote")
                or finding["quote"] not in message["content"]
            ):
                raise ProviderError("ungrounded_fallacy")
            text_value(finding.get("label"), 100)
            text_value(finding.get("explanation"))
        coaching = text_value(data.get("coaching", ""))
        civility = data.get("civility", {})
        if not isinstance(civility, dict):
            raise ProviderError("invalid_model_response")
        civility_text = text_value(civility.get("message", ""))
        clarification = text_value(data.get("clarification", ""))
        now = self.arena.clock()
        async with self.repo.unit() as unit:
            current = await unit.one(
                "SELECT revision,deleted FROM messages WHERE id=?", (message["id"],)
            )
            if current["revision"] != message["revision"] or current["deleted"]:
                return
            latest_match = await unit.match(match["id"])
            latest_match["analysis_version"] = latest_match.get("analysis_version", 0) + 1
            await unit.save_match(latest_match)
            await unit.save("analysis_done", f"{message['id']}:{message['revision']}", True)
            for claim in claims:
                await unit.db.execute(
                    "INSERT OR IGNORE INTO claims VALUES(?,?,?,?,?)",
                    (claim["id"], match["id"], message["id"], message["revision"], encode(claim)),
                )
                if claim["status"] == "pending":
                    await unit.job(
                        f"research:{claim['id']}:0",
                        "research",
                        match["id"],
                        {"claim": claim["id"], "on_demand": False},
                        now,
                    )
            await unit.event(
                match["id"],
                "analysis",
                None,
                {
                    "message": message["id"],
                    "claims": [c["id"] for c in claims],
                    "fallacies": fallacies if settings["fallacies"]["enabled"] else [],
                },
                now,
            )
            if settings["claims"]["enabled"] and sequence % settings["claims"]["every"] == 0:
                ledger = "\n".join(
                    f"{c['id']} by {c['author']} ({c['kind']}): "
                    f"{c['quote'] if settings['claims']['detail'] == 'full' else c['summary']} "
                    f"{c['url']} [{c['status']}]"
                    for c in claims
                )
                if ledger or clarification:
                    await unit.notice(
                        match,
                        f"claims:{message['id']}:{message['revision']}",
                        f"Claim ledger\n{ledger}\n{clarification}",
                        now,
                    )
            for feature, content in (("fallacies", encode(fallacies)), ("coaching", coaching)):
                if (
                    settings[feature]["enabled"]
                    and content not in ("[]", "")
                    and sequence % settings[feature]["every"] == 0
                ):
                    if feature == "fallacies" and settings[feature]["families"]:
                        selected = [
                            f
                            for f in fallacies
                            if f["label"].casefold()
                            in {v.casefold() for v in settings[feature]["families"]}
                        ]
                        content = encode(selected)
                    await unit.notice(
                        match,
                        f"{feature}:{message['id']}:{message['revision']}",
                        f"Optional {feature}: {content}",
                        now,
                        user=message["author"]
                        if feature == "coaching" and settings[feature]["delivery"] == "private"
                        else None,
                    )
            if settings["civility"]["enabled"] and civility_text:
                await unit.notice(
                    match,
                    f"civility:{message['id']}:{message['revision']}",
                    f"Civility suggestion: {civility_text}",
                    now,
                )
                if (
                    civility.get("escalate")
                    and settings["civility"]["escalation"] == "notify_staff"
                ):
                    await unit.event(
                        match["id"],
                        "staff_review_requested",
                        None,
                        {"message": message["url"], "reason": civility_text},
                        now,
                    )
                    config = await unit.document("guild", match["guild"], server_defaults())
                    if config["announcement"]:
                        await unit.notice(
                            match,
                            f"civility-staff:{message['id']}",
                            f"Staff review requested: {message['url']} — {civility_text}",
                            now,
                            destination=config["announcement"],
                        )
            if (
                settings["live_scores"]["enabled"]
                and sequence % settings["live_scores"]["every"] == 0
            ):
                await unit.job(
                    f"live:{match['id']}:{match['transcript_version']}",
                    "live",
                    match["id"],
                    {},
                    now,
                )

    async def check(self, actor, claim_id):
        async with self.repo.unit() as unit:
            row = await unit.one("SELECT * FROM claims WHERE id=?", (claim_id,))
            if not row:
                raise ArenaError("Claim not found.")
            match = await unit.match(row["match_id"], actor.guild)
            participant(match, actor)
            if not match["settings"]["on_demand"]["enabled"]:
                raise ArenaError("On-demand checking is disabled.")
            claim = json.loads(row["data"])
            if claim["stale"]:
                raise ArenaError("This claim's source changed; use its current revision.")
            if claim["kind"] != "factual":
                claim["status"] = "not fact-checkable"
            else:
                if claim["status"] in {"pending", "researching"}:
                    return claim
                if match["on_demand_count"] >= match["settings"]["on_demand"]["limit"]:
                    raise ArenaError("This match's on-demand request limit is exhausted.")
                match["on_demand_count"] += 1
                match["analysis_version"] = match.get("analysis_version", 0) + 1
                claim["status"] = "pending"
                await unit.job(
                    f"check:{claim_id}:{len(claim['history'])}:{len(claim['disputes'])}",
                    "research",
                    match["id"],
                    {"claim": claim_id, "on_demand": True},
                    self.arena.clock(),
                )
                await unit.save_match(match)
            await unit.db.execute("UPDATE claims SET data=? WHERE id=?", (encode(claim), claim_id))
            return claim

    async def dispute(self, actor, match_id, target, reason, source=None, relation=None):
        if not 10 <= len(reason) <= 3000:
            raise ArenaError("Explain the dispute in 10–3000 characters.")
        if source and (not source.startswith("https://") or len(source) > 2000):
            raise ArenaError("Evidence links must be HTTPS URLs of at most 2000 characters.")
        async with self.repo.unit() as unit:
            match = await unit.match(match_id, actor.guild)
            participant(match, actor)
            row = await unit.one(
                "SELECT data FROM claims WHERE id=? AND match_id=?", (target, match_id)
            )
            dispute = {
                "by": actor.id,
                "reason": reason,
                "source": source,
                "created": self.arena.clock(),
            }
            if row:
                claim = json.loads(row["data"])
                claim["disputes"].append(dispute)
                if relation:
                    other = await unit.one(
                        "SELECT id FROM claims WHERE id=? AND match_id=?", (relation, match_id)
                    )
                    if not other:
                        raise ArenaError("Related claim must belong to this match.")
                    claim["relations"].append(
                        {"target": relation, "type": "objection", "by": actor.id}
                    )
                # Keep the old verdict visibly disputed; on-demand controls rechecks.
                if (
                    match["settings"]["on_demand"]["enabled"]
                    and not claim["stale"]
                    and claim["kind"] == "factual"
                ):
                    if match["on_demand_count"] >= match["settings"]["on_demand"]["limit"]:
                        claim["status"] = "budget_limited"
                    else:
                        match["on_demand_count"] += 1
                        claim["status"] = "pending"
                        await unit.job(
                            f"dispute:{target}:{len(claim['disputes'])}",
                            "research",
                            match_id,
                            {"claim": target, "on_demand": True},
                            self.arena.clock(),
                        )
                else:
                    claim["status"] = "disputed"
                await unit.db.execute(
                    "UPDATE claims SET data=? WHERE id=?", (encode(claim), target)
                )
                match["analysis_version"] = match.get("analysis_version", 0) + 1
                await unit.save_match(match)
            elif target != "result":
                raise ArenaError("Choose a claim ID or 'result'.")
            await unit.event(
                match_id, "dispute", actor.id, {"target": target, **dispute}, self.arena.clock()
            )
            await unit.notice(
                match,
                f"dispute-notice:{match_id}:{target}:{self.arena.clock()}",
                f"Dispute by {actor.id} on {target}: {reason}. Staff can inspect /match audit.",
                self.arena.clock(),
            )
            return (
                "Dispute recorded with correction history. "
                "Recheck pending when enabled and within budget."
            )

    @model_response
    async def research_claim(self, job):
        claim = await self.repo.claim(
            job["data"]["claim"], (await self.repo.match(job["match_id"]))["guild"]
        )
        match = await self.repo.match(claim["match"])
        if claim["stale"] or claim["kind"] != "factual":
            return
        if any(h.get("job") == job["id"] and "verdict" in h for h in claim["history"]):
            return
        options = match["settings"]["on_demand" if job["data"]["on_demand"] else "research"]
        if not options["enabled"]:
            return
        now = self.arena.clock()
        sources = []
        try:
            async with self.repo.unit() as unit:
                config = await unit.document("guild", match["guild"], server_defaults())
                await unit.use(
                    f"research:{match['guild']}:{int(now // 86400)}", config["research_daily"]
                )
                await unit.use(
                    f"research-match:{match['id']}", match["settings"]["research"]["budget"]
                )
            sources = await self.research.search(
                claim["quote"], options["depth"], match["settings"]["research"]["sources"]
            )
            for dispute in claim["disputes"][-5:]:
                if dispute["source"]:
                    page = await self.research.fetch(dispute["source"])
                    page["provenance"] += "; participant-submitted evidence"
                    sources.append(page)
            for i, source in enumerate(sources):
                source["id"] = f"S{i + 1}"
            if sources:
                verdict = await self.call(match, "research", {"claim": claim, "sources": sources})
                if verdict.get("verdict") not in VERDICTS or type(
                    verdict.get("confidence")
                ) not in {int, float}:
                    raise ProviderError("invalid_research_response")
                ids = verdict.get("source_ids")
                if (
                    not isinstance(ids, list)
                    or not set(ids) <= {s["id"] for s in sources}
                    or not 0 <= verdict["confidence"] <= 1
                ):
                    raise ProviderError("invalid_source_references")
                if (
                    verdict["verdict"] not in {"insufficient evidence", "not fact-checkable"}
                    and not ids
                ):
                    raise ProviderError("ungrounded_verdict")
                text_value(verdict.get("explanation"))
            else:
                verdict = {
                    "verdict": "insufficient evidence",
                    "confidence": 0,
                    "source_ids": [],
                    "explanation": "No inspectable sources were retrieved.",
                }
            verdict.update(
                sources=sources,
                researched_at=now,
                by="retrieval + model" if sources else "retrieval",
            )
            await self._research_state(claim, verdict, job)
        except (ProviderError, ArenaError) as error:
            status = "budget_limited" if isinstance(error, ArenaError) else error.status
            await self._research_state(
                claim,
                {
                    "status": status,
                    "researched_at": now,
                    "explanation": "Research unavailable; no factual conclusion.",
                    "sources": sources,
                },
                job,
            )
            if isinstance(error, ProviderError):
                raise

    async def _research_state(self, claim, verdict, job):
        async with self.repo.unit() as unit:
            row = await unit.one("SELECT data FROM claims WHERE id=?", (claim["id"],))
            current = json.loads(row["data"])
            if current["stale"]:
                return
            if any(h.get("job") == job["id"] and "verdict" in h for h in current["history"]):
                return
            verdict["job"] = job["id"]
            current["history"].append(verdict)
            current["status"] = verdict.get("verdict", verdict.get("status", "failed"))
            await unit.db.execute(
                "UPDATE claims SET data=? WHERE id=?", (encode(current), claim["id"])
            )
            match = await unit.match(claim["match"])
            match["analysis_version"] = match.get("analysis_version", 0) + 1
            await unit.save_match(match)
            if match["state"] == "closed":
                result_row = await unit.one(
                    "SELECT data FROM results WHERE match_id=?", (match["id"],)
                )
                result = json.loads(result_row["data"])
                previous = next(
                    (
                        h.get("verdict")
                        for h in reversed(current["history"][:-1])
                        if h.get("verdict")
                    ),
                    None,
                )
                if (
                    result.get("report")
                    and verdict.get("verdict")
                    and verdict["verdict"] != previous
                ):
                    result["review_needed"] = True
                    await unit.db.execute(
                        "UPDATE results SET data=? WHERE match_id=?", (encode(result), match["id"])
                    )
                    await unit.event(
                        match["id"],
                        "evidence_review_needed",
                        None,
                        {"claim": claim["id"], "previous": previous, "current": verdict["verdict"]},
                        self.arena.clock(),
                    )
                    await replay(unit, match["guild"], self.arena.clock())
                    for player in match["players"]:
                        await unit.db.execute(
                            "DELETE FROM documents WHERE kind='insight' AND id=?",
                            (f"{match['guild']}:{player}:{match['id']}",),
                        )
                await unit.job(
                    f"profile-check:{job['id']}:{len(current['history'])}",
                    "profile",
                    match["id"],
                    {},
                    self.arena.clock(),
                )
            correction = match["settings"]["corrections"]
            if (
                correction["enabled"]
                and verdict.get("verdict") in {"contradicted", "partly supported"}
                and verdict["confidence"] >= correction["confidence"]
            ):
                urls = " ".join(
                    s["url"] for s in verdict["sources"] if s["id"] in verdict["source_ids"]
                )
                message = (
                    f"Evidence flag for {claim['id']} by {claim['author']}: {verdict['verdict']}. "
                    f"{verdict['explanation']} Sources: {urls}. Check history includes"
                    f" dates and provenance."
                )
                key = f"correction:{job['id']}"
                await unit.notice(
                    match,
                    key,
                    message,
                    self.arena.clock(),
                    guard={"claim": claim["id"], "check": job["id"]},
                )
                if correction["delivery"] == "batched":
                    await unit.db.execute("UPDATE jobs SET due=due+60 WHERE id=?", (key,))
            if job["data"]["on_demand"]:
                await unit.notice(
                    match,
                    f"check-ready:{job['id']}",
                    f"Check {claim['id']}: {current['status']}. Use /match claims for"
                    f" evidence and history.",
                    self.arena.clock(),
                )

    @model_response
    async def judge(self, job, live=False, feedback_only=False):
        match = await self.repo.match(job["match_id"])
        expected = "closed" if feedback_only else "active" if live else "judging"
        if match["state"] != expected:
            return
        async with self.repo.unit() as unit:
            match = await unit.match(match["id"])
            messages = await unit.rows(
                "SELECT * FROM messages WHERE match_id=? AND deleted=0 ORDER BY created,id",
                (match["id"],),
            )
            claims = [
                json.loads(r["data"])
                for r in await unit.rows("SELECT data FROM claims WHERE match_id=?", (match["id"],))
            ]
            # Do not race queued analysis/research. Failed work is explicitly unassessed.
            pending = await unit.one(
                "SELECT id FROM jobs WHERE match_id=? AND kind IN ('analyze','research') "
                "AND state IN ('pending','running') LIMIT 1",
                (match["id"],),
            )
        if pending:
            raise ProviderError("waiting_for_evidence")
        claims = [c for c in claims if not c["stale"]]
        raw = await self.call(
            match,
            "judge",
            {"match": match, "messages": messages, "claims": claims},
            match["settings"]["judging"]["model"],
        )
        report = validate_judgment(match, messages, claims, raw)
        if live:
            async with self.repo.unit() as unit:
                current = await unit.match(match["id"])
                if current["transcript_version"] != match["transcript_version"] or current.get(
                    "analysis_version", 0
                ) != match.get("analysis_version", 0):
                    return
                await unit.notice(
                    match,
                    f"live-notice:{job['id']}",
                    f"Provisional live scores (separate from final judging): {encode(report)}",
                    self.arena.clock(),
                )
        else:
            if feedback_only:
                async with self.repo.unit() as unit:
                    current = await unit.match(match["id"])
                    if current["transcript_version"] != match["transcript_version"] or current.get(
                        "analysis_version", 0
                    ) != match.get("analysis_version", 0):
                        await unit.job(
                            f"feedback-current:{match['id']}:{current['transcript_version']}:"
                            f"{current.get('analysis_version', 0)}",
                            "feedback",
                            match["id"],
                            {},
                            self.arena.clock(),
                        )
                        return
                    row = await unit.one(
                        "SELECT data FROM results WHERE match_id=?", (match["id"],)
                    )
                    result = json.loads(row["data"])
                    result["feedback"] = report["participants"]
                    await unit.db.execute(
                        "UPDATE results SET data=? WHERE match_id=?", (encode(result), match["id"])
                    )
                    await unit.job(
                        f"profile-feedback:{job['id']}",
                        "profile",
                        match["id"],
                        {},
                        self.arena.clock(),
                    )
            elif not await self.arena.judged(match["id"], match["transcript_version"], report):
                return
            if match["settings"]["feedback"]["enabled"]:
                async with self.repo.unit() as unit:
                    for player, detail in report["participants"].items():
                        payload = (
                            detail
                            if match["settings"]["feedback"]["detail"] == "full"
                            else {
                                "strengths": detail["strengths"],
                                "needs": detail["needs"],
                                "practice": detail["practice"],
                                "training": detail["training"],
                            }
                        )
                        await unit.notice(
                            match,
                            f"feedback:{job['id']}:{player}",
                            f"Feedback for {player}: {encode(payload)}",
                            self.arena.clock(),
                            user=player
                            if match["settings"]["feedback"]["delivery"] == "private"
                            else None,
                        )


def validate_judgment(match, messages, claims, raw):
    participants = raw.get("participants")
    if not isinstance(participants, dict) or set(participants) != set(match["players"]):
        raise ProviderError("invalid_judging_participants")
    if type(raw.get("sufficient")) is not bool:
        raise ProviderError("invalid_judgment")
    text_value(raw.get("explanation"))
    refs = {m["id"] for m in messages} | {c["id"] for c in claims}
    totals = {}
    for player, detail in participants.items():
        if not isinstance(detail, dict) or not isinstance(detail.get("scores"), dict):
            raise ProviderError("invalid_scores")
        scores, weights = detail["scores"], match["settings"]["judging"]["weights"]
        if set(scores) != set(weights):
            raise ProviderError("invalid_rubric")
        for dimension, value in scores.items():
            if dimension == "accuracy" and value is None:
                continue
            if type(value) not in {int, float} or not 0 <= value <= 100:
                raise ProviderError("invalid_scores")
        references = detail.get("references")
        if not isinstance(references, list) or not set(references) <= refs:
            raise ProviderError("invalid_judgment_references")
        if raw["sufficient"] and (
            not references or not any(m["author"] == player for m in messages)
        ):
            raise ProviderError("ungrounded_judgment")
        text_value(detail.get("explanation"))
        for field in ("strengths", "needs", "unanswered", "practice"):
            if not isinstance(detail.get(field), list) or len(detail[field]) > 20:
                raise ProviderError("invalid_feedback")
            for value in detail[field]:
                text_value(value)
        detail["training"] = [
            {
                "fallacy": entry.name,
                "reference": entry.reference,
                "command": f"/train fallacy name:{entry.name}",
            }
            for name in detail["practice"]
            if (entry := find_fallacy(name))
        ]
        assessed = any(
            c["author"] == player
            and c["kind"] == "factual"
            and not c.get("stale")
            and any(
                h.get("source_ids")
                and h.get("verdict")
                in {"supported", "contradicted", "partly supported", "disputed"}
                for h in c.get("history", [])
            )
            for c in claims
        )
        if not assessed:
            scores["accuracy"] = None
        included = [d for d in weights if scores[d] is not None]
        denominator = sum(weights[d] for d in included)
        if not denominator:
            raise ProviderError("empty_rubric")
        totals[player] = sum(scores[d] * weights[d] for d in included) / denominator
    a, b = match["players"]
    winner = None
    if not raw["sufficient"]:
        outcome = "inconclusive"
    elif abs(totals[a] - totals[b]) <= match["settings"]["judging"]["tie_threshold"]:
        outcome = match["settings"]["judging"]["tie_policy"]
    else:
        outcome, winner = "judged", max(totals, key=totals.get)
    return {
        "outcome": outcome,
        "winner": winner,
        "totals": totals,
        "participants": participants,
        "weights": match["settings"]["judging"]["weights"],
        "rubric": "arena-v1",
        "explanation": raw["explanation"],
        "transcript_version": match["transcript_version"],
        "analysis_version": match.get("analysis_version", 0),
        "accuracy_policy": "Unassessed/value-only accuracy omitted and weights renormalized.",
        "audience": "Excluded from all scores.",
    }
