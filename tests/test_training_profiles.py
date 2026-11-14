import copy
import tempfile
import unittest
from pathlib import Path

from arena.profiles import ProfileError, Profiles
from arena.store import Store
from arena.training import Training, TrainingError, catalogue


class FakeIntelligence:
    def __init__(self):
        self.calls = []
        self.available = True
        self.grade = {"identification_score": 1, "explanation_score": 2, "accepted_label": "personal attack", "feedback": "The criticism of music preferences does not address the crossing measurements."}
        self.observations = [{"text": "Supports this proposal with measurements.", "theme": "empirical", "approach": "Uses measured evidence.", "evidence_ids": ["101"], "recommendations": ["ad_hominem"]}]
        self.hook = None

    async def complete(self, purpose, payload, settings=None):
        self.calls.append((purpose, payload, settings))
        if self.hook:
            await self.hook(purpose)
        if not self.available:
            raise RuntimeError("Provider unavailable")
        if purpose == "training.grade":
            return copy.deepcopy(self.grade)
        if purpose in {"training.generate", "training.battle"}:
            return {"argument": "Reject the plan because its author wears ugly shoes.", "explanation": "The author's shoes do not address the plan.", "hint": "Do the shoes affect the evidence?", "repair": "Assess the plan's evidence instead."}
        if purpose == "profile.analyze":
            return {"observations": copy.deepcopy(self.observations)}
        raise AssertionError(purpose)


class TrainingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.ai = FakeIntelligence()
        self.training = Training(self.store, self.ai)

    def tearDown(self):
        self.store.close()

    async def test_mixed_puzzle_hides_answer_until_assessment(self):
        session = await self.training.start(1, 2, "mixed")
        self.assertNotIn("puzzle", session)
        self.assertNotIn("source", session)
        self.assertNotIn("expected_label", session)
        self.assertIn("argument", session)
        result = await self.training.answer(1, 2, "Personal attack: 'terrible taste in music' is irrelevant to the crossing measurements.")
        self.assertEqual(result["status"], "graded")
        self.assertEqual(result["accepted_label"], "personal attack")
        self.assertIn("logicallyfallacious.com", result["source"])
        self.assertEqual(self.training.progress(1, 2)["attempts"], 1)

    async def test_label_only_answer_never_counts_as_mastery(self):
        self.ai.grade["explanation_score"] = 0
        await self.training.start(1, 2, fallacy="personal attack")
        await self.training.answer(1, 2, "Ad hominem")
        progress = self.training.progress(1, 2)["by_fallacy"]["ad_hominem"]
        self.assertEqual(progress["identification_accuracy"], 1)
        self.assertEqual(progress["explanation_accuracy"], 0)
        self.assertEqual(progress["mastered"], 0)

    async def test_failed_assessment_records_no_score_and_can_retry(self):
        await self.training.start(1, 2)
        self.ai.available = False
        result = await self.training.answer(1, 2, "A reasoned answer.")
        self.assertEqual(result["status"], "grading_unavailable")
        self.assertEqual(self.training.progress(1, 2)["attempts"], 0)
        self.assertEqual(self.store.get("training_sessions", "1:2")["status"], "active")
        self.ai.available = True
        self.assertEqual((await self.training.answer(1, 2, "A reasoned answer."))["status"], "graded")

    async def test_invalid_or_boolean_score_is_rejected(self):
        await self.training.start(1, 2)
        self.ai.grade["identification_score"] = True
        self.assertEqual((await self.training.answer(1, 2, "A reasoned answer."))["status"], "grading_unavailable")
        self.assertEqual(self.training.progress(1, 2)["attempts"], 0)

    async def test_invalid_accepted_label_is_rejected(self):
        await self.training.start(1, 2)
        self.ai.grade["accepted_label"] = {"untrusted": "object"}
        self.assertEqual((await self.training.answer(1, 2, "A reasoned answer."))["status"], "grading_unavailable")
        self.assertEqual(self.training.progress(1, 2)["attempts"], 0)

    async def test_chosen_aliases_custom_topics_and_repeated_exercises(self):
        first = await self.training.start(1, 2, "chosen", "personal attack")
        self.assertEqual(first["chosen_fallacy"], "Ad hominem")
        await self.training.answer(1, 2, "An irrelevant attack on Mira.")
        second = await self.training.start(1, 2, "chosen", "ad hominem", "hard", "transport")
        self.assertNotEqual(first["argument"], second["argument"])
        self.assertEqual(second["difficulty"], "hard")
        self.assertEqual(second["topic"], "transport")
        self.assertTrue(any(call[0] == "training.generate" for call in self.ai.calls))

    async def test_repair_score_is_separate_and_required(self):
        await self.training.start(1, 2, "repair")
        self.assertEqual((await self.training.answer(1, 2, "Assess the measurements."))["status"], "grading_unavailable")
        self.ai.grade["repair_score"] = 2
        self.assertEqual((await self.training.answer(1, 2, "Assess the measurements."))["repair_score"], 2)

    async def test_battle_continues_and_finishes_after_five_turns(self):
        await self.training.start(1, 2, "battle")
        for turn in range(1, 6):
            result = await self.training.answer(1, 2, "The attack is irrelevant to the proposal.")
            if turn < 5:
                self.assertEqual(result["next_turn"]["turn"], turn + 1)
            else:
                self.assertNotIn("next_turn", result)
        self.assertEqual(self.training.progress(1, 2)["attempts"], 5)
        self.assertEqual(self.store.get("training_sessions", "1:2")["status"], "complete")

    async def test_concurrent_new_exercise_supersedes_inflight_grade(self):
        await self.training.start(1, 2)

        async def replace(purpose):
            if purpose == "training.grade":
                self.ai.hook = None
                await self.training.start(1, 2, "repair")

        self.ai.hook = replace
        result = await self.training.answer(1, 2, "A reasoned answer.")
        self.assertEqual(result["status"], "superseded")
        self.assertEqual(self.training.progress(1, 2)["attempts"], 0)
        self.assertEqual(self.store.get("training_sessions", "1:2")["mode"], "repair")

    async def test_hint_and_history_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arena.sqlite"
            first_store = Store(path)
            first = Training(first_store, self.ai)
            await first.start(1, 2)
            await first.hint(1, 2)
            first_store.close()
            second_store = Store(path)
            second = Training(second_store, self.ai)
            self.assertEqual((await second.hint(1, 2))["hints_used"], 2)
            await second.answer(1, 2, "The preference is irrelevant to the measurements.")
            self.assertEqual(second.progress(1, 2)["recent"][0]["hints_used"], 2)
            self.assertEqual(second.progress(1, 99)["attempts"], 0)
            second_store.close()

    async def test_interrupted_grading_is_recoverable_after_restart(self):
        await self.training.start(1, 2)
        session = self.store.get("training_sessions", "1:2")
        session["status"] = "grading"
        session["grading_id"] = "interrupted-call"
        self.store.put("training_sessions", "1:2", session)
        restarted = Training(self.store, self.ai)
        self.assertEqual((await restarted.answer(1, 2, "The attack is irrelevant to the evidence."))["status"], "graded")

    async def test_sound_mode_includes_valid_arguments(self):
        session = await self.training.start(1, 2, "sound", "sound")
        self.assertIn("Jo", session["argument"])
        self.assertNotIn("expected_label", session)
        result = await self.training.answer(1, 2, "The conclusion follows from the stated membership rule and Jo's membership.")
        self.assertEqual(result["expected_label"], "Valid supported argument")

    async def test_input_validation_and_reference_catalogue(self):
        self.assertEqual(len(catalogue()), 9)
        with self.assertRaises(TrainingError):
            await self.training.start(1, 2, "unknown")
        with self.assertRaises(TrainingError):
            await self.training.start(1, 2, "chosen")
        with self.assertRaises(TrainingError):
            await self.training.start(1, 2, "chosen", "made-up-fallacy")
        with self.assertRaises(TrainingError):
            await self.training.start(1, 2, difficulty="extreme")
        with self.assertRaises(TrainingError):
            await self.training.start(1, 2, "personalized")


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.ai = FakeIntelligence()
        self.profiles = Profiles(self.store, self.ai)
        self.match = {"id": "M1", "guild_id": 1, "participants": [2, 3], "topic": "Safer crossings", "positions": {"2": "Add a crossing"}, "settings": {"profile_insights": True}, "status": "ended", "channel_id": 50, "created_at": 100, "ended_at": 200, "result": {"outcome": "judged", "winner_id": 2}}
        self.store.put("matches", "M1", self.match)
        self.store.put("messages", "101", {"id": "101", "guild_id": 1, "match_id": "M1", "author_id": 2, "content": "Measurements show an increase in vehicles at this crossing.", "url": "https://discord.com/channels/1/50/101", "deleted": False})
        self.store.put("messages", "102", {"id": "102", "guild_id": 1, "match_id": "M1", "author_id": 3, "content": "We should weigh the costs.", "url": "https://discord.com/channels/1/50/102", "deleted": False})

    def tearDown(self):
        self.store.close()

    async def opt_in(self):
        self.profiles.settings(1, 2, {"opt_in": True, "training_recommendations": True})
        return await self.profiles.refresh(self.match)

    async def test_default_private_opt_out_and_no_analysis(self):
        preferences = self.profiles.settings(1, 2)
        self.assertFalse(preferences["opt_in"])
        self.assertEqual(preferences["visibility"], "private")
        await self.profiles.refresh(self.match)
        self.assertEqual(self.ai.calls, [])
        with self.assertRaises(ProfileError):
            await self.profiles.view(1, 2, 3)
        self.assertEqual((await self.profiles.view(1, 2, 2))["record"]["wins"], 1)

    async def test_both_match_and_user_consent_required(self):
        self.profiles.settings(1, 2, {"opt_in": True})
        self.match["settings"]["profile_insights"] = False
        self.assertEqual((await self.profiles.refresh(self.match))["status"], "ineligible")
        self.assertEqual(self.ai.calls, [])

    async def test_only_author_evidence_is_used_with_sample_size(self):
        await self.opt_in()
        profile = await self.profiles.view(1, 2, 2)
        self.assertEqual(profile["sample_size"], 1)
        observation = profile["insights"][0]["observations"][0]
        self.assertEqual(observation["evidence"][0]["message_id"], "101")
        self.assertEqual(observation["sample_size"], 1)
        self.assertEqual(self.ai.calls[0][1]["data"]["messages"][0]["id"], "101")
        self.assertEqual(len(self.ai.calls[0][1]["data"]["messages"]), 1)
        self.assertIn("not personal beliefs", profile["limitations"])

    async def test_profile_retry_reuses_successful_unchanged_analysis(self):
        await self.opt_in()
        self.assertEqual(len(self.ai.calls), 1)
        refreshed = await self.profiles.refresh(self.match)
        self.assertEqual(refreshed["updated"][0]["status"], "unchanged")
        self.assertEqual(len(self.ai.calls), 1)
        message = self.store.get("messages", "101")
        message["content"] += " A later correction changes the sample."
        self.store.put("messages", "101", message)
        await self.profiles.refresh(self.match)
        self.assertEqual(len(self.ai.calls), 2)

    async def test_interests_and_approaches_aggregate_unique_evidence(self):
        self.ai.observations[0]["interests"] = ["technology", "engineering"]
        self.ai.observations.append(copy.deepcopy(self.ai.observations[0]))
        await self.opt_in()
        view = await self.profiles.view(1, 2, 2)
        self.assertEqual(view["interest_evidence_counts"], {"engineering": 1, "technology": 1})
        self.assertEqual(view["approach_evidence_counts"], {"Uses measured evidence.": 1})
        self.assertEqual(view["interests"]["technology"]["sample_size"], 1)
        self.assertEqual(view["interests"]["technology"]["match_count"], 1)
        self.assertEqual(view["interests"]["technology"]["evidence"][0]["message_id"], "101")
        self.assertEqual(view["approaches"]["Uses measured evidence."]["evidence"][0]["url"], "https://discord.com/channels/1/50/101")
        self.assertEqual(self.ai.calls[0][1]["data"]["allowed_interest_categories"], ["ethics", "politics", "technology", "engineering", "science", "art", "culture", "other"])

    async def test_disputed_or_invalid_evidence_is_excluded_from_interest_counts(self):
        self.ai.observations[0]["interests"] = ["art"]
        await self.opt_in()
        view = await self.profiles.view(1, 2, 2)
        insight_id = view["insights"][0]["observations"][0]["id"]
        self.profiles.settings(1, 2, {"correction": {"insight_id": insight_id, "text": "This example does not describe my broader approach."}})
        disputed = await self.profiles.view(1, 2, 2)
        self.assertEqual(disputed["interest_evidence_counts"], {})
        self.assertEqual(disputed["approach_evidence_counts"], {})
        self.profiles.remove_insights(1, 2)
        revoked = await self.profiles.view(1, 2, 2)
        self.assertEqual(revoked["interests"], {})
        self.assertEqual(revoked["approaches"], {})
        self.assertEqual(self.store.list("profile_insights", guild_id=1, user_id=2), [])

    async def test_unsupported_interest_categories_fail_validation(self):
        self.ai.observations[0]["interests"] = ["inferred personality"]
        result = await self.opt_in()
        self.assertEqual(result["updated"][0]["status"], "analysis_unavailable")
        self.assertEqual(self.store.list("profile_insights"), [])

    async def test_missing_interests_remains_backward_compatible(self):
        await self.opt_in()
        view = await self.profiles.view(1, 2, 2)
        self.assertEqual(view["insights"][0]["observations"][0]["interests"], [])
        self.assertEqual(view["interest_evidence_counts"], {})
        self.assertEqual(view["approach_evidence_counts"], {"Uses measured evidence.": 1})

    async def test_fabricated_or_opponent_evidence_is_rejected(self):
        self.ai.observations[0]["evidence_ids"] = ["102"]
        result = await self.opt_in()
        self.assertEqual(result["updated"][0]["status"], "analysis_unavailable")
        self.assertEqual(self.store.list("profile_insights"), [])

    async def test_opt_out_and_removal_purge_generated_records(self):
        await self.opt_in()
        self.assertEqual(len(self.store.list("profile_insights")), 1)
        result = self.profiles.remove_insights(1, 2)
        self.assertEqual(result["status"], "removed")
        self.assertEqual(self.store.list("profile_insights"), [])
        self.assertFalse(self.profiles.settings(1, 2)["opt_in"])
        self.assertIsNotNone(self.store.get("matches", "M1"))

    async def test_revocation_while_provider_runs_cannot_recreate_insight(self):
        self.profiles.settings(1, 2, {"opt_in": True})

        async def revoke(purpose):
            self.profiles.settings(1, 2, {"opt_in": False})

        self.ai.hook = revoke
        result = await self.profiles.refresh(self.match)
        self.assertEqual(result["updated"][0]["status"], "consent_changed")
        self.assertEqual(self.store.list("profile_insights"), [])

    async def test_edits_and_deletions_invalidate_display_and_personalized_practice(self):
        await self.opt_in()
        message = self.store.get("messages", "101")
        message["deleted"] = True
        self.store.put("messages", "101", message)
        self.assertEqual((await self.profiles.view(1, 2, 2))["insights"], [])
        with self.assertRaises(TrainingError):
            await Training(self.store, self.ai).start(1, 2, "personalized")

    async def test_edits_after_excerpt_are_detected(self):
        message = self.store.get("messages", "101")
        message["content"] = "A" * 600 + "original conclusion"
        self.store.put("messages", "101", message)
        await self.opt_in()
        self.assertEqual(len((await self.profiles.view(1, 2, 2))["insights"]), 1)
        message["content"] = "A" * 600 + "revised conclusion"
        self.store.put("messages", "101", message)
        self.assertEqual((await self.profiles.view(1, 2, 2))["insights"], [])

    async def test_owner_correction_suppresses_practice_recommendation(self):
        await self.opt_in()
        insight_id = (await self.profiles.view(1, 2, 2))["insights"][0]["observations"][0]["id"]
        self.profiles.settings(1, 2, {"correction": {"insight_id": insight_id, "text": "The measurements were hypothetical in this exercise."}})
        view = await self.profiles.view(1, 2, 2)
        self.assertTrue(view["insights"][0]["observations"][0]["disputed"])
        self.assertEqual(view["insights"][0]["recommendations"], [])
        with self.assertRaises(ProfileError):
            self.profiles.settings(1, 3, {"correction": {"insight_id": insight_id, "text": "Hijacked correction"}})

    async def test_personalized_review_requires_and_uses_own_recommendations(self):
        await self.opt_in()
        training = Training(self.store, self.ai)
        result = await training.start(1, 2, "personalized")
        self.assertEqual(result["mode"], "personalized")
        self.assertEqual(self.store.get("training_sessions", "1:2")["puzzle"]["id"], "ad_hominem")
        with self.assertRaises(TrainingError):
            await training.start(1, 3, "personalized")

    async def test_public_visibility_is_explicit_and_settings_validate_types(self):
        self.profiles.settings(1, 2, {"visibility": "public"})
        self.assertEqual((await self.profiles.view(1, 2, 3))["user_id"], 2)
        with self.assertRaises(ProfileError):
            self.profiles.settings(1, 2, {"opt_in": "yes"})
        with self.assertRaises(ProfileError):
            self.profiles.settings(1, 2, {"visibility": "friends"})
        with self.assertRaises(ProfileError):
            self.profiles.settings(1, 2, {"psychology": True})


if __name__ == "__main__":
    unittest.main()
