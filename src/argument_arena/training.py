"""Durable original drills, explanation grading and multi-turn training battles."""

import hashlib
import json

from argument_arena.arena import identity
from argument_arena.assistance import text_value
from argument_arena.curriculum import LIBRARY, VARIANTS, find_fallacy
from argument_arena.providers import ProviderError, model_response
from argument_arena.repository import encode
from argument_arena.settings import ArenaError, server_defaults

MODES = {"spot", "selected", "mixed", "battle", "repair", "sound"}


class Training:
    def __init__(self, arena, llm):
        self.arena, self.repo, self.llm = arena, arena.repo, llm

    async def start(
        self, actor, mode="mixed", fallacy=None, difficulty=1, topic="community projects"
    ):
        if (
            actor.bot
            or mode not in MODES
            or difficulty not in {1, 2, 3}
            or not 1 <= len(topic) <= 100
        ):
            raise ArenaError(
                "Choose spot, selected, mixed, battle, repair or sound; difficulty 1–3;"
                " a short topic."
            )
        entry = find_fallacy(fallacy) if fallacy else None
        if fallacy and entry is None:
            raise ArenaError("Unknown fallacy. Use /train library for supported references.")
        if mode == "selected" and entry is None:
            raise ArenaError("Selected practice requires a fallacy name.")
        async with self.repo.unit() as unit:
            active = await unit.one(
                "SELECT id FROM training WHERE guild=? AND user_id=? AND state IN"
                " ('active','grading')",
                (actor.guild, actor.id),
            )
            if active:
                raise ArenaError("Finish the current exercise or use /train stop first.")
            progress = await unit.document(
                "training_progress", f"{actor.guild}:{actor.id}", {"attempts": []}
            )
            if entry is None:
                # Rotate categories deterministically, then revisit weak recent performance.
                counts = {
                    e.name: sum(a["fallacy"] == e.name for a in progress["attempts"])
                    for e in LIBRARY
                }
                entry = min(LIBRARY, key=lambda e: counts[e.name])
                prefs = await unit.document("profile_prefs", f"{actor.guild}:{actor.id}", {})
                if prefs.get("recommendations") and prefs.get("analysis"):
                    observed = await unit.rows("SELECT id,data FROM documents WHERE kind='insight'")
                    suggested = [
                        find_fallacy(name)
                        for row in observed
                        if row["id"].startswith(f"{actor.guild}:{actor.id}:")
                        and not json.loads(row["data"]).get("excluded")
                        for name in json.loads(row["data"]).get("practice", [])
                    ]
                    if (
                        suggested
                        and suggested[-1] is not None
                        and len(progress["attempts"]) % 3 == 0
                    ):
                        entry = suggested[-1]
                elif progress["attempts"] and all(counts.values()):

                    def recent_score(item):
                        samples = [
                            a["score"] for a in progress["attempts"] if a["fallacy"] == item.name
                        ][-5:]
                        return sum(samples) / len(samples)

                    entry = min(LIBRARY, key=recent_score)
            number = len(progress["attempts"])
            sound = mode == "sound" and number % 2 == 0
            exercise = self._exercise(entry, mode, topic, difficulty, sound, number)
            session = {
                "id": identity(),
                "guild": actor.guild,
                "user": actor.id,
                "mode": mode,
                "topic": topic,
                "difficulty": difficulty,
                "turn": 1,
                "hints": 0,
                "exercise": exercise,
                "answers": [],
                "created": self.arena.clock(),
                "state": "active",
                "target_turns": 3 if mode == "battle" else 1,
            }
            await unit.db.execute(
                "INSERT INTO training VALUES(?,?,?,?,?)",
                (session["id"], actor.guild, actor.id, "active", encode(session)),
            )
            return self.public(session)

    def _exercise(self, entry, mode, topic, difficulty, sound, number):
        if sound:
            prompt = (
                f"Every project that exceeds its fixed budget requires a review. The {topic} "
                "project exceeded its fixed budget. Therefore this project requires a review."
            )
            explanation = (
                "The conclusion follows by applying the given universal rule to the stated case."
            )
        else:
            template = entry.example if (number // 3) % 2 == 0 else VARIANTS[entry.name]
            prompt, explanation = template.format(topic=topic), entry.explanation
        prefixes = (
            "At a planning meeting: ",
            "In a letter to the committee: ",
            "During a public forum: ",
        )
        prompt = prefixes[number % len(prefixes)] + prompt
        if difficulty >= 2:
            prompt = "Several people disagree about the timetable. " + prompt
        if difficulty == 3:
            prompt += " The speaker also says the current project has a difficult funding deadline."
        instruction = (
            "Repair the reasoning and explain what you changed."
            if mode == "repair"
            else "Is this reasoning valid or fallacious? Explain why."
            if mode == "sound"
            else "Name the reasoning error, quote the relevant passage, and explain it."
        )
        return {
            "prompt": prompt,
            "instruction": instruction,
            "fallacy": "valid" if sound else entry.name,
            "aliases": list(entry.aliases),
            "explanation": explanation,
            "repair": entry.repair,
            "hint": "Apply the premises carefully to the stated case." if sound else entry.hint,
            "reference": entry.reference,
            "attribution": "Further reading: Bo Bennett, Logically Fallacious.",
            "original": True,
        }

    def public(self, session):
        exercise = session["exercise"]
        result = {k: session[k] for k in ("id", "mode", "difficulty", "turn", "state")}
        result.update(
            prompt=exercise["prompt"],
            instruction=exercise["instruction"],
            attribution=exercise["attribution"],
        )
        if "generation" in exercise:
            result["generation"] = exercise["generation"]
        if session["mode"] == "selected":
            result["reference"] = exercise["reference"]
        if session["answers"]:
            result["last_feedback"] = session["answers"][-1]
        return result

    async def _current(self, unit, actor):
        row = await unit.one(
            "SELECT data FROM training WHERE guild=? AND user_id=? AND state IN"
            " ('active','grading') ORDER BY rowid DESC LIMIT 1",
            (actor.guild, actor.id),
        )
        if not row:
            raise ArenaError("No active training. Use /train start.")
        return json.loads(row["data"])

    async def current(self, actor):
        async with self.repo.unit() as unit:
            return self.public(await self._current(unit, actor))

    async def hint(self, actor):
        async with self.repo.unit() as unit:
            session = await self._current(unit, actor)
            session["hints"] += 1
            await unit.db.execute(
                "UPDATE training SET data=? WHERE id=?", (encode(session), session["id"])
            )
            return session["exercise"]["hint"]

    async def answer(self, actor, answer):
        if not 10 <= len(answer) <= 4000:
            raise ArenaError(
                "Give an explanation in 10–4000 characters, rather than a label alone."
            )
        async with self.repo.unit() as unit:
            session = await self._current(unit, actor)
            if session["state"] == "grading":
                raise ArenaError(
                    "Your answer is awaiting grading. Use /train current or /train retry."
                )
            session["state"], session["pending_answer"] = "grading", answer
            digest = hashlib.sha256(answer.encode()).hexdigest()[:16]
            await unit.db.execute(
                "UPDATE training SET state='grading',data=? WHERE id=?",
                (encode(session), session["id"]),
            )
            await unit.job(
                f"train:{session['id']}:{session['turn']}:{digest}",
                "train_grade",
                None,
                {"session": session["id"]},
                self.arena.clock(),
            )
            return (
                "Answer saved; grading pending. Use /train current for feedback. "
                "Missing providers report unavailable."
            )

    @model_response
    async def grade(self, job):
        async with self.repo.unit() as unit:
            row = await unit.one("SELECT data FROM training WHERE id=?", (job["data"]["session"],))
            session = json.loads(row["data"])
            if session["state"] != "grading" or any(
                a.get("job") == job["id"] for a in session["answers"]
            ):
                return
            config = await unit.document("guild", session["guild"], server_defaults())
            await unit.use(
                f"llm:{session['guild']}:{int(self.arena.clock() // 86400)}", config["llm_daily"]
            )
        grade = await self.llm.complete(
            "grade",
            {
                "exercise": session["exercise"],
                "mode": session["mode"],
                "answer": session["pending_answer"],
                "difficulty": session["difficulty"],
            },
            config["llm_models"]["training"],
        )
        for field in ("identification", "explanation"):
            if type(grade.get(field)) not in {int, float} or not 0 <= grade[field] <= 1:
                raise ProviderError("invalid_training_grade")
        text_value(grade.get("feedback"))
        text_value(grade.get("alternative", ""))
        grade["score"] = 0.3 * grade["identification"] + 0.7 * grade["explanation"]
        grade.update(
            fallacy=session["exercise"]["fallacy"],
            reference=session["exercise"]["reference"],
            teaching=session["exercise"]["explanation"],
            repair=session["exercise"]["repair"],
            answer=session["pending_answer"],
            hints=session["hints"],
            job=job["id"],
            created=self.arena.clock(),
            difficulty=session["difficulty"],
        )
        next_exercise = None
        if session["mode"] == "battle" and session["turn"] < session["target_turns"]:
            entry = LIBRARY[session["turn"] % len(LIBRARY)]
            # A real dynamic bot turn may fail independently; grade still remains durable below.
            next_exercise = self._exercise(
                entry, "battle", session["topic"], session["difficulty"], False, session["turn"]
            )
            try:
                async with self.repo.unit() as unit:
                    await unit.use(
                        f"llm:{session['guild']}:{int(self.arena.clock() // 86400)}",
                        config["llm_daily"],
                    )
                turn = await self.llm.complete(
                    "battle",
                    {
                        "topic": session["topic"],
                        "fallacy": entry.name,
                        "answer": session["pending_answer"],
                        "difficulty": session["difficulty"],
                    },
                    config["llm_models"]["battle"],
                )
                text_value(turn.get("text"), 1500)
                if not turn.get("quote") or turn["quote"] not in turn["text"]:
                    raise ProviderError("ungrounded_battle_turn")
                for field in ("explanation", "repair", "hint"):
                    text_value(turn.get(field))
                next_exercise.update(
                    prompt=turn["text"],
                    explanation=turn["explanation"],
                    repair=turn["repair"],
                    hint=turn["hint"],
                )
            except (ProviderError, ArenaError):
                next_exercise["generation"] = (
                    "Original curriculum fallback; dynamic battle generation unavailable."
                )
        async with self.repo.unit() as unit:
            latest = await unit.one("SELECT data,state FROM training WHERE id=?", (session["id"],))
            current = json.loads(latest["data"])
            if latest["state"] != "grading" or any(
                a.get("job") == job["id"] for a in current["answers"]
            ):
                return
            session["answers"].append(grade)
            session.pop("pending_answer", None)
            if next_exercise:
                session.update(
                    turn=session["turn"] + 1, exercise=next_exercise, state="active", hints=0
                )
            else:
                session["state"] = "complete"
            await unit.db.execute(
                "UPDATE training SET state=?,data=? WHERE id=?",
                (session["state"], encode(session), session["id"]),
            )
            key = f"{session['guild']}:{session['user']}"
            progress = await unit.document("training_progress", key, {"attempts": []})
            progress["attempts"].append(grade)
            await unit.save("training_progress", key, progress)

    async def progress(self, actor):
        async with self.repo.unit() as unit:
            progress = await unit.document(
                "training_progress", f"{actor.guild}:{actor.id}", {"attempts": []}
            )
            latest = await unit.one(
                "SELECT data FROM training WHERE guild=? AND user_id=? ORDER BY rowid DESC LIMIT 1",
                (actor.guild, actor.id),
            )
            attempts = progress["attempts"]
            categories = {}
            for attempt in attempts:
                categories.setdefault(attempt["fallacy"], []).append(attempt)
            scores = {
                name: {
                    "attempts": len(values),
                    "accuracy": sum(a["score"] for a in values) / len(values),
                    "recent": sum(a["score"] for a in values[-5:]) / len(values[-5:]),
                    "hints": sum(a["hints"] for a in values),
                    "identification": sum(a["identification"] for a in values) / len(values),
                    "explanation": sum(a["explanation"] for a in values) / len(values),
                }
                for name, values in categories.items()
            }
            recommendations = sorted(scores, key=lambda name: scores[name]["recent"])
            return {
                "attempts": len(attempts),
                "suggested_difficulty": min(
                    3, 1 + sum(a["score"] >= 0.8 for a in attempts[-10:]) // 4
                ),
                "by_fallacy": scores,
                "recommendations": recommendations[:3] or [e.name for e in LIBRARY[:3]],
                "latest": self.public(json.loads(latest["data"])) if latest else None,
            }

    async def stop(self, actor):
        async with self.repo.unit() as unit:
            session = await self._current(unit, actor)
            session["state"] = "stopped"
            await unit.db.execute(
                "UPDATE training SET state='stopped',data=? WHERE id=?",
                (encode(session), session["id"]),
            )
            return "Training stopped. Completed practice remains in your progress."

    async def retry(self, actor):
        async with self.repo.unit() as unit:
            session = await self._current(unit, actor)
            rows = await unit.rows(
                "SELECT id,data,state,error FROM jobs WHERE kind='train_grade' AND state='failed'"
            )
            for row in rows:
                if json.loads(row["data"])["session"] == session["id"]:
                    await unit.db.execute(
                        "UPDATE jobs SET state='pending',attempts=0,lease=NULL,due=? WHERE id=?",
                        (self.arena.clock(), row["id"]),
                    )
            return (
                "Failed grading queued for retry; provider configuration and budgets still apply."
            )
