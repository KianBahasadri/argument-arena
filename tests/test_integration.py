"""Exercise service boundaries without contacting Discord or paid providers."""

import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from arena.bot import ArenaBot
from arena.core import Arena, DomainError
from arena.profiles import Profiles
from arena.store import Store
from arena.training import Training


class ScenarioProvider:
    def __init__(self):
        self.judgments = 0

    async def judge(self, match, messages, claims, provisional=False):
        self.judgments += 1
        assert not provisional
        assert {message["author_id"] for message in messages if not message.get("deleted")} == set(match["participants"])
        return {"status": "complete", "outcome": "judged", "winner_id": match["participants"][0],
                "scores": {str(uid): {"reasoning": 8 if index == 0 else 6} for index, uid in enumerate(match["participants"])},
                "explanation": "The first participant supplied the stronger reasoning in this test fixture.",
                "evidence": [message["id"] for message in messages], "feedback": {}}

    async def complete(self, purpose, payload, settings=None):
        if purpose == "profile.analyze":
            messages = payload["data"]["messages"]
            return {"observations": [{"text": "This match uses empirical evidence.", "theme": "empirical",
                                      "approach": "Refers to measured results.", "evidence_ids": [messages[0]["id"]],
                                      "recommendations": ["hasty_generalization"]}]}
        if purpose == "training.grade":
            return {"identification_score": 1, "explanation_score": 2,
                    "accepted_label": "hasty generalization", "feedback": "The sample does not justify the universal conclusion."}
        raise AssertionError(purpose)


class FullMatchIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.arena = Arena(self.store)
        self.provider = ScenarioProvider()
        self.profiles = Profiles(self.store, self.provider)
        self.now = time.time()

    def tearDown(self):
        self.store.close()

    def start_match(self, guild_id=1, ranked=True):
        self.arena.configure(guild_id, 999, defaults={"profile_insights": True},
                             active_category_id=100, completed_category_id=200,
                             forfeited_category_id=300, cancelled_category_id=400)
        match = self.arena.challenge(guild_id, 10, 20, "Does the new crossing reduce delays?",
                                     positions={"10": "Support", "20": "Oppose"},
                                     origin_url=f"https://discord.com/channels/{guild_id}/50/51",
                                     now=self.now, preset="ranked" if ranked else "casual")
        self.assertEqual(match["confirmations"], [10])
        self.assertEqual(match["status"], "pending")
        self.assertEqual(self.arena.accept(match["id"], 20)["status"], "ready")
        return self.arena.activate(match["id"], 101, now=self.now)

    def add_round(self, match, first_message_id=1001):
        for offset, user_id in enumerate(match["participants"]):
            now = self.now + offset + 1
            content = "A survey of comparable crossings supports my position." if offset == 0 else "We must examine whether those crossings are representative."
            self.arena.record_message(match["id"], user_id, first_message_id + offset, content,
                                      f"https://discord.com/channels/{match['guild_id']}/101/{first_message_id + offset}", now=now)
            match = self.arena.submit(match["id"], user_id, now=now + 0.1)
        return match

    async def test_challenge_turns_judgment_rankings_profile_and_personalized_training(self):
        self.profiles.settings(1, 10, {"opt_in": True, "training_recommendations": True})
        match = self.add_round(self.start_match())
        proposed = self.arena.request_action(match["id"], 10, "finish", now=self.now + 10)
        self.assertEqual(proposed["status"], "active")
        judging = self.arena.request_action(match["id"], 20, "finish", now=self.now + 11)
        self.assertEqual(judging["status"], "judging")
        worker = SimpleNamespace(arena=self.arena, store=self.store, intelligence=self.provider)
        await ArenaBot.process_job(worker, {"kind": "judge", "match_id": match["id"]})
        ended = self.arena.get_match(match["id"])
        self.assertEqual(ended["status"], "ended")
        self.assertEqual(ended["result"]["winner_id"], 10)
        self.assertEqual(self.arena.leaderboard(1)[0]["user_id"], 10)
        self.assertEqual(self.arena.leaderboard(1)[0]["rating"], 1216)
        self.assertEqual(self.arena.leaderboard(1)[1]["rating"], 1184)
        await self.profiles.refresh(ended)
        profile = await self.profiles.view(1, 10, 10)
        self.assertEqual(profile["record"]["wins"], 1)
        self.assertEqual(profile["history"][0]["argued_position"], "Support")
        self.assertEqual(profile["insights"][0]["observations"][0]["evidence"][0]["message_id"], "1001")
        self.assertEqual((await self.profiles.view(1, 20, 20))["insights"], [])
        training = Training(self.store, self.provider)
        session = await training.start(1, 10, "personalized")
        self.assertEqual(session["mode"], "personalized")
        await training.answer(1, 10, "The two visitors are not a representative sample of every museum visitor.")
        self.assertEqual(training.progress(1, 10)["attempts"], 1)
        self.assertEqual(self.arena.leaderboard(1)[0]["rating"], 1216)
        # Duplicate job delivery cannot assign a second result or rating change.
        await ArenaBot.process_job(worker, {"kind": "judge", "match_id": match["id"]})
        self.assertEqual(self.provider.judgments, 1)
        self.assertEqual(self.arena.leaderboard(1)[0]["rating"], 1216)

    async def test_correction_replays_ratings_and_updates_profile_record(self):
        match = self.start_match()
        self.arena.end(match["id"], "judged", 10)
        self.assertEqual((await self.profiles.view(1, 10, 10))["record"]["wins"], 1)
        corrected = self.arena.correct_result(match["id"], 999, 20, "The referee reviewed the cited evidence.")
        self.assertEqual(corrected["result_history"][0]["winner_id"], 10)
        self.assertEqual(self.arena.leaderboard(1)[0]["user_id"], 20)
        self.assertEqual((await self.profiles.view(1, 10, 10))["record"]["losses"], 1)
        self.assertEqual((await self.profiles.view(1, 20, 20))["record"]["wins"], 1)

    async def test_casual_results_and_training_are_separate_from_ranked_ratings(self):
        match = self.start_match(ranked=False)
        ended = self.arena.request_action(match["id"], 20, "concede")
        self.assertEqual(ended["result"]["outcome"], "concession")
        self.assertEqual((await self.profiles.view(1, 10, 10))["record"]["wins"], 1)
        self.assertEqual(self.arena.leaderboard(1), [])
        self.assertEqual(self.store.list("ratings"), [])

    async def test_guilds_keep_results_consents_and_profiles_separate(self):
        first = self.start_match(guild_id=1)
        second = self.start_match(guild_id=2)
        self.arena.end(first["id"], "judged", 10)
        self.arena.end(second["id"], "judged", 20)
        self.profiles.settings(1, 10, {"opt_in": True})
        self.assertFalse(self.profiles.settings(2, 10)["opt_in"])
        self.assertEqual(self.arena.leaderboard(1)[0]["user_id"], 10)
        self.assertEqual(self.arena.leaderboard(2)[0]["user_id"], 20)
        self.assertEqual(len((await self.profiles.view(1, 10, 10))["history"]), 1)

    async def test_restart_preserves_transcript_agreement_turn_and_outage_grace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arena.sqlite3"
            original = Store(path)
            arena = Arena(original)
            match = arena.challenge(1, 10, 20, "A durable debate", now=self.now)
            arena.accept(match["id"], 20)
            match = arena.activate(match["id"], 101, now=self.now)
            arena.record_message(match["id"], 10, 2001, "First turn argument", "https://discord.com/channels/1/101/2001", now=self.now + 5)
            match = arena.submit(match["id"], 10, now=self.now + 10)
            arena.propose_settings(match["id"], 10, {"coaching": True})
            original.put("system", "heartbeat", {"time": self.now + 20})
            original.close()
            restarted_store = Store(path)
            restarted = Arena(restarted_store)
            restored = restarted.get_match(match["id"])
            self.assertEqual(restored["next_speaker_id"], 20)
            self.assertFalse(restored["settings"]["coaching"])
            self.assertEqual(restored["settings_proposal"]["confirmations"], [10])
            events = restarted.recover(now=self.now + 620)
            self.assertEqual(events[0]["seconds"], 600)
            compensated = restarted.get_match(match["id"])
            self.assertEqual(compensated["deadline"], match["deadline"] + 600)
            self.assertEqual(restarted_store.get("messages", "2001")["content"], "First turn argument")
            self.assertTrue(restarted.accept(match["id"], 20)["settings"]["coaching"])
            restarted_store.close()

    async def test_participants_cannot_change_finished_match_via_leftover_proposal(self):
        match = self.start_match(ranked=False)
        self.arena.propose_settings(match["id"], 10, {"ranked": True})
        self.arena.request_action(match["id"], 10, "concede")
        with self.assertRaises(DomainError):
            self.arena.accept(match["id"], 20)
        self.assertFalse(self.arena.get_match(match["id"])["settings"]["ranked"])

    async def test_profile_history_never_exposes_private_judgment_report(self):
        match = self.start_match()
        report = {"feedback": {"10": "First participant's private coaching", "20": "Second participant's private coaching"}, "explanation": "A provider could also put private details here."}
        self.arena.end(match["id"], "judged", 10, report=report)
        self.profiles.settings(1, 10, {"visibility": "public"})
        for viewer_id in (10, 20, 999):
            profile = await self.profiles.view(1, 10, viewer_id)
            result = profile["history"][0]["result"]
            self.assertEqual(set(result), {"outcome", "winner_id", "rating_changes"})
            self.assertNotIn("private", str(profile))
        self.assertEqual(self.arena.get_match(match["id"])["result"]["report"], report)

    async def test_late_submission_cannot_escape_timeout_scheduler(self):
        match = self.start_match()
        self.arena.record_message(match["id"], 10, 3001, "A timely argument", "https://discord.com/channels/1/101/3001", now=self.now + 1)
        self.store.put("system", "heartbeat", {"time": match["deadline"] - 1})
        with self.assertRaises(DomainError):
            self.arena.submit(match["id"], 10, now=match["deadline"] + 1)
        self.assertEqual(self.arena.get_match(match["id"])["next_speaker_id"], 10)


if __name__ == "__main__":
    unittest.main()
