import tempfile
import unittest
from pathlib import Path

from arena.core import Arena, DEFAULT_SETTINGS, DomainError, validate_settings
from arena.store import Store


class ArenaTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.arena = Arena(self.store)
        self.now = 1000

    def tearDown(self):
        self.store.close()

    def match(self, guild=1, users=(10, 20), ranked=False):
        match = self.arena.challenge(guild, *users, "A topic", now=self.now,
                                     preset="ranked" if ranked else "casual")
        self.arena.accept(match["id"], users[1])
        return self.arena.activate(match["id"], 99, now=self.now)

    def test_settings_dependencies_and_ranked_rubric(self):
        self.assertFalse(validate_settings({"background_research": False})["factual_corrections"])
        self.assertFalse(validate_settings({"judging": False, "ranked": True})["ranked"])
        for patch in ({"response_hours": float("nan")}, {"unknown": True}, {"judging": "true"},
                      {"ranked": True, "weights": {"reasoning": 100}}, {"length_limit": 0}):
            with self.assertRaises(DomainError):
                validate_settings(patch)
        self.assertEqual(set(validate_settings({})), set(DEFAULT_SETTINGS))

    def test_mutual_acceptance_and_proposals_reset_consent(self):
        match = self.arena.challenge(1, 10, 20, "Topic", now=1000)
        self.arena.propose_settings(match["id"], 20, {"coaching": True})
        self.assertEqual(self.arena.accept(match["id"], 20)["status"], "pending")
        match = self.arena.accept(match["id"], 10)
        self.assertEqual(match["status"], "ready")
        self.arena.activate(match["id"], 99, now=1000)
        match = self.arena.propose_settings(match["id"], 20, {"coaching": False})
        self.assertTrue(match["settings"]["coaching"])
        match = self.arena.accept(match["id"], 10)
        self.assertFalse(match["settings"]["coaching"])
        self.assertEqual(match["status"], "active")
        with self.assertRaises(DomainError):
            self.arena.accept(match["id"], 30)

    def test_only_official_required_speaker_advances_deadline(self):
        match = self.match()
        with self.assertRaises(DomainError):
            self.arena.record_message(match["id"], 30, 1, "spectator", "url", now=1020)
        with self.assertRaises(DomainError):
            self.arena.record_message(match["id"], 20, 2, "wrong turn", "url", now=1020)
        with self.assertRaises(DomainError):
            self.arena.submit(match["id"], 10, now=1020)
        message = self.arena.record_message(match["id"], 10, 3, "argument", "url", now=1020)
        self.assertEqual(message, self.arena.record_message(match["id"], 10, 3, "duplicate", "url"))
        self.assertEqual(self.arena.get_match(match["id"])["deadline"], match["deadline"])
        match = self.arena.submit(match["id"], 10, now=1030)
        self.assertEqual(match["next_speaker_id"], 20)
        self.assertEqual(match["deadline"], 1030 + 86400)

    def test_mutual_pause_resume_extension(self):
        match = self.match()
        self.assertEqual(self.arena.request_action(match["id"], 10, "pause", now=1020)["status"], "active")
        paused = self.arena.request_action(match["id"], 20, "pause", now=1030)
        self.assertEqual(paused["status"], "paused")
        self.arena.request_action(match["id"], 10, "resume", now=1100)
        resumed = self.arena.request_action(match["id"], 20, "resume", now=1110)
        self.assertEqual(resumed["deadline"], match["deadline"] + 80)
        extended = self.arena.request_action(match["id"], 999, "extend", staff=True, hours=2, now=1120)
        self.assertEqual(extended["deadline"], resumed["deadline"] + 7200)

    def test_timeout_exactly_once_and_outage_compensation(self):
        match = self.match()
        self.store.put("system", "heartbeat", {"time": match["deadline"] - 10})
        self.assertEqual(self.arena.due(match["deadline"])[0]["kind"], "ended")
        self.assertEqual(self.arena.due(match["deadline"] + 1), [])
        self.assertEqual(self.arena.get_match(match["id"])["result"]["winner_id"], 20)
        self.now += 100
        other = self.match(guild=2)
        recovered = self.arena.due(other["deadline"] + 500)
        self.assertEqual(recovered[0]["kind"], "recovered")
        self.assertEqual(self.arena.get_match(other["id"])["status"], "active")

    def test_reminder_once_and_opt_out_of_forfeits(self):
        match = self.match()
        self.store.put("system", "heartbeat", {"time": match["deadline"] - 30})
        self.assertEqual(self.arena.due(match["deadline"] - 20)[0]["kind"], "reminder")
        self.assertEqual(self.arena.due(match["deadline"] - 10), [])
        match["settings"]["inactivity_forfeits"] = False
        self.store.put("matches", match["id"], match)
        self.arena.due(match["deadline"])
        self.assertEqual(self.arena.get_match(match["id"])["status"], "active")

    def test_round_limits_end_in_judging(self):
        match = self.match()
        match["settings"].update(limits=True, round_limit=1)
        self.store.put("matches", match["id"], match)
        for number, user in enumerate((10, 20)):
            self.arena.record_message(match["id"], user, number, "Argument", "url")
            match = self.arena.submit(match["id"], user)
        self.assertEqual(match["status"], "judging")

    def test_rankings_replay_after_staff_result_correction(self):
        match = self.match(ranked=True)
        self.arena.end(match["id"], "judged", 10)
        self.assertEqual(self.arena.leaderboard(1)[0]["user_id"], 10)
        self.now += 100
        other = self.match(ranked=True)
        self.arena.end(other["id"], "judged", 10)
        corrected = self.arena.correct_result(match["id"], 999, 20, "Review evidence")
        self.assertEqual(len(corrected["result_history"]), 1)
        ratings = self.store.list("ratings", guild_id=1)
        self.assertAlmostEqual(sum(r["rating"] for r in ratings), 2400)
        self.assertTrue(self.store.list("events", match_id=match["id"]))

    def test_server_limits_and_preset_validation(self):
        self.arena.configure(1, 999, max_concurrent=1)
        self.match()
        with self.assertRaises(DomainError):
            self.arena.challenge(1, 30, 40, "Topic", now=2000)
        with self.assertRaises(DomainError):
            self.arena.configure(1, 999, defaults={"response_hours": 0})

    def test_server_json_shapes_and_format_filter(self):
        for patch in ({"presets": []}, {"channel_template": 1}, {"moderator_role_ids": None},
                      {"defaults": False}):
            with self.assertRaises(DomainError):
                self.arena.configure(1, 999, **patch)
        match = self.match(ranked=True)
        self.arena.end(match["id"], "judged", 10)
        self.assertEqual(len(self.arena.leaderboard(1, preset="ranked")), 2)
        self.assertEqual(self.arena.leaderboard(1, preset="casual"), [])
        self.assertEqual(self.arena.leaderboard(1, min_matches=2), [])

    def test_recorded_message_replay_remains_idempotent_after_finish(self):
        match = self.match()
        message = self.arena.record_message(match["id"], 10, 5, "A valid argument", "url", now=1005)
        self.arena.end(match["id"], "concession", 20)
        self.assertEqual(self.arena.record_message(match["id"], 10, 5, "replayed", "url"), message)

    def test_atomic_rollback_and_durable_backup(self):
        with self.assertRaises(RuntimeError):
            with self.store.atomic():
                self.store.put("example", "a", {"value": 1})
                with self.store.atomic():
                    self.store.put("example", "b", {"value": 2})
                raise RuntimeError("rollback")
        self.assertEqual(self.store.list("example"), [])
        with tempfile.TemporaryDirectory() as directory:
            self.store.put("example", "a", {"value": 1})
            path = Path(directory) / "backup.sqlite3"
            self.store.backup(path)
            copy = Store(path)
            self.assertEqual(copy.get("example", "a")["value"], 1)
            copy.close()


if __name__ == "__main__":
    unittest.main()
