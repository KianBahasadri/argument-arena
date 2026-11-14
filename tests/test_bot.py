"""Transport tests use real domain rules and mocked Discord delivery; no network."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from arena.__main__ import database_lock
from arena.bot import (
    ArenaBot, ArenaCommands, DomainError, JobDeferred, MatchView,
    parse_patch, permission_overwrites,
)
from arena.config import Config
from arena.store import Store


class Entity:
    def __init__(self, ident):
        self.id = ident
        self.roles = []
        self.bot = False
        self.guild_permissions = SimpleNamespace(administrator=False)


class Response:
    def __init__(self):
        self.done = False
        self.send_message = AsyncMock(side_effect=self.sent)
        self.defer = AsyncMock(side_effect=self.sent)
        self.send_modal = AsyncMock(side_effect=self.sent)

    def is_done(self):
        return self.done

    async def sent(self, *args, **kwargs):
        self.done = True


def guild_fixture():
    members = {uid: Entity(uid) for uid in (11, 22, 33)}
    guild = SimpleNamespace(id=100, default_role=Entity(1), me=Entity(2),
                            get_member=members.get, get_role=lambda uid: None,
                            get_channel=lambda uid: None)
    return guild, members


def interaction_fixture(guild, member, channel_id=900):
    return SimpleNamespace(guild=guild, guild_id=guild.id, user=member,
                           channel_id=channel_id, id=12345, response=Response(),
                           followup=SimpleNamespace(send=AsyncMock()))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")
        self.bot = ArenaBot(Config(database_path=":memory:", guild_id=100), self.store)
        self.commands = ArenaCommands(self.bot)
        self.guild, self.members = guild_fixture()
        self.interaction = interaction_fixture(self.guild, self.members[11])
        self.match = self.bot.arena.challenge(100, 11, 22, "Test debate", now=1000)
        self.match_id = self.match["id"]

    async def asyncTearDown(self):
        await self.bot.close()

    def activate(self, settings=None):
        if settings:
            self.bot.arena.propose_settings(self.match_id, 11, settings)
        self.bot.arena.accept(self.match_id, 22)
        self.match = self.bot.arena.activate(self.match_id, 900, now=1000)
        return self.match

    def test_patch_rejects_expressions_lists_and_oversize_data(self):
        self.assertEqual(parse_patch('{"coaching": true}'), {"coaching": True})
        for value in ('__import__("os")', '[]', '{"x":"' + 'a' * 8100 + '"}'):
            with self.assertRaises(DomainError):
                parse_patch(value)

    def test_match_access_is_server_and_participant_scoped(self):
        self.assertEqual(self.bot.checked_match(self.interaction, self.match_id)["id"], self.match_id)
        outsider = interaction_fixture(self.guild, self.members[33])
        with self.assertRaises(DomainError):
            self.bot.checked_match(outsider, self.match_id, participant=True)
        self.interaction.guild_id = 200
        with self.assertRaises(DomainError):
            self.bot.checked_match(self.interaction, self.match_id)

    def test_permissions_separate_main_channel_threads_and_turns(self):
        match = self.activate()
        mapping = permission_overwrites(self.guild, match)
        self.assertFalse(mapping[self.guild.default_role].send_messages)
        self.assertTrue(mapping[self.guild.default_role].send_messages_in_threads)
        self.assertTrue(mapping[self.guild.default_role].use_application_commands)
        self.assertTrue(mapping[self.members[11]].send_messages)
        self.assertFalse(mapping[self.members[22]].send_messages)
        match["settings"].update(discussion_threads=False, spectator_reactions=False)
        mapping = permission_overwrites(self.guild, match)
        self.assertFalse(mapping[self.guild.default_role].create_public_threads)
        self.assertFalse(mapping[self.guild.default_role].add_reactions)
        self.assertFalse(mapping[self.guild.default_role].send_messages_in_threads)

    def test_archival_and_pause_close_debater_posting(self):
        match = self.activate()
        match["settings"]["archive_threads"] = True
        mapping = permission_overwrites(self.guild, match, closed=True)
        self.assertFalse(mapping[self.members[11]].send_messages)
        self.assertFalse(mapping[self.guild.default_role].send_messages_in_threads)
        match["status"] = "paused"
        self.assertFalse(permission_overwrites(self.guild, match)[self.members[11]].send_messages)

    def test_member_objects_fetched_without_cache_get_overwrites(self):
        match = self.activate()
        self.guild.get_member = lambda uid: None
        mapping = permission_overwrites(self.guild, match, members=self.members)
        self.assertTrue(mapping[self.members[11]].send_messages)

    async def test_persistent_controls_include_every_boolean_setting(self):
        from arena.core import DEFAULT_SETTINGS
        view = MatchView(self.bot, self.match_id)
        self.assertTrue(view.is_persistent())
        select = next(item for item in view.children if isinstance(item, discord.ui.Select))
        self.assertEqual({option.value for option in select.options},
                         {key for key, value in DEFAULT_SETTINGS.items() if isinstance(value, bool)})
        self.assertLessEqual(len(select.options), 25)
        self.assertLessEqual(len(self.commands.match.commands), 25)

    async def test_submit_defers_before_discord_permission_calls(self):
        self.activate()
        self.bot.arena.record_message(self.match_id, 11, 555, "Argument", "https://discord.com/message")
        async def apply(*args, **kwargs):
            self.assertTrue(self.interaction.response.is_done())
        self.bot.apply_permissions = AsyncMock(side_effect=apply)
        self.bot.announce = AsyncMock()
        await self.commands.submit.callback(self.commands, self.interaction, self.match_id)
        self.assertEqual(self.bot.arena.get_match(self.match_id)["next_speaker_id"], 22)

    async def test_on_demand_uses_search_and_enforces_match_limit(self):
        self.activate({"on_demand_limit": 1})
        claim = {"id": "C1", "storage_key": f"{self.match_id}:C1", "match_id": self.match_id,
                 "kind": "empirical", "check_status": "unchecked"}
        self.store.put("claims", claim["storage_key"], claim)
        await self.commands.check.callback(self.commands, self.interaction, "C1", self.match_id)
        jobs = self.store.list("jobs")
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["sources"])
        self.assertEqual(jobs[0]["requested_by"], 11)
        with self.assertRaises(DomainError):
            await self.commands.check.callback(self.commands, self.interaction, "C1", self.match_id)

    async def test_judging_defers_until_evidence_jobs_finish(self):
        self.activate()
        match = self.bot.arena.get_match(self.match_id)
        match["status"] = "judging"
        self.store.put("matches", self.match_id, match)
        self.bot.enqueue("analyze", "555", match_id=self.match_id, message_id="555")
        self.bot.intelligence.judge = AsyncMock()
        with self.assertRaises(JobDeferred):
            await self.bot.process_job({"kind": "judge", "match_id": self.match_id})
        self.bot.intelligence.judge.assert_not_awaited()
        self.assertEqual(self.bot.arena.get_match(self.match_id)["status"], "judging")

    async def test_stale_judgment_cannot_end_match(self):
        self.activate()
        match = self.bot.arena.get_match(self.match_id)
        match["status"] = "judging"
        self.store.put("matches", self.match_id, match)
        self.bot.intelligence.judge = AsyncMock(return_value={"status": "stale", "outcome": "inconclusive"})
        with self.assertRaises(JobDeferred):
            await self.bot.process_job({"kind": "judge", "match_id": self.match_id})
        self.assertEqual(self.bot.arena.get_match(self.match_id)["status"], "judging")

    async def test_private_coaching_and_disabled_claims_do_not_publish(self):
        match = self.activate({"claim_tracking": False, "coaching": True, "coaching_delivery": "private"})
        await self.bot.publish_analysis(match, {"status": "complete", "author_id": 11,
            "claims": [{"original": "private ledger content"}],
            "feedback": [{"kind": "coaching", "quote": "quote", "explanation": "private coaching"}],
            "clarifications": []})
        outbox = self.store.list("analysis_outbox")
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["recipient_id"], 11)
        self.assertNotIn("claims", outbox[0]["report"])

    async def test_notification_interval_batches_reports(self):
        match = self.activate({"notification_interval": 60})
        self.bot.queue_report(match, {"clarifications": ["A?"]})
        self.bot.queue_report(match, {"clarifications": ["B?"]})
        destination = SimpleNamespace(send=AsyncMock())
        self.bot.get_channel = lambda uid: destination
        await self.bot.flush_analysis()
        destination.send.assert_not_awaited()
        for item in self.store.list("analysis_outbox"):
            item["created_at"] -= 61
            self.store.put("analysis_outbox", item["id"], item)
        await self.bot.flush_analysis()
        self.assertEqual(destination.send.await_count, 1)
        content = destination.send.call_args.args[0]
        self.assertIn("A?", content)
        self.assertIn("B?", content)
        self.assertTrue(all(item["status"] == "sent" for item in self.store.list("analysis_outbox")))

    async def test_result_retrieval_redacts_other_participants_feedback(self):
        self.activate()
        self.bot.arena.end(self.match_id, "judged", 11, report={"feedback": {"11": "first private", "22": "second private"}})
        await self.commands.result.callback(self.commands, self.interaction, self.match_id)
        rendered = self.interaction.response.send_message.call_args.kwargs["content"]
        self.assertIn("first private", rendered)
        self.assertNotIn("second private", rendered)
        outsider = interaction_fixture(self.guild, self.members[33])
        await self.commands.result.callback(self.commands, outsider, self.match_id)
        rendered = outsider.response.send_message.call_args.kwargs["content"]
        self.assertNotIn("first private", rendered)
        self.assertNotIn("second private", rendered)

    async def test_archive_keeps_explicit_overwrites(self):
        match = self.activate()
        category = MagicMock(spec=discord.CategoryChannel)
        channel = SimpleNamespace(edit=AsyncMock(), threads=[])
        self.guild.get_channel = lambda uid: channel if uid == 900 else category
        self.bot.get_guild = lambda uid: self.guild
        await self.bot.apply_permissions(match, closed=True, category_id=888)
        kwargs = channel.edit.call_args.kwargs
        self.assertFalse(kwargs["sync_permissions"])
        self.assertIn(self.guild.default_role, kwargs["overwrites"])
        self.assertFalse(kwargs["overwrites"][self.members[11]].send_messages)

    async def test_offline_edit_and_deletion_are_reconciled(self):
        self.activate()
        self.bot.arena.record_message(self.match_id, 11, 555, "Old text", "https://discord.com/555")
        self.bot.arena.record_message(self.match_id, 11, 556, "Deleted text", "https://discord.com/556")
        self.bot.arena.end(self.match_id, "draw")
        async def history(**kwargs):
            yield SimpleNamespace(id=555, content="Edited text")
        channel = SimpleNamespace(history=history)
        self.bot.get_channel = lambda uid: channel
        await self.bot.recover_history()
        self.assertEqual(self.store.get("messages", "555")["content"], "Edited text")
        self.assertTrue(self.store.get("messages", "556")["deleted"])
        self.assertTrue(self.bot.arena.get_match(self.match_id)["result"]["evidence_stale"])

    async def test_vote_window_and_eligibility_are_enforced(self):
        match = self.activate({"audience_voting": True, "audience_eligibility": "nonparticipants"})
        with self.assertRaises(DomainError):
            await self.commands.vote.callback(self.commands, self.interaction, self.members[22], self.match_id)
        spectator = interaction_fixture(self.guild, self.members[33])
        with self.assertRaisesRegex(DomainError, "window"):
            await self.commands.vote.callback(self.commands, spectator, self.members[22], self.match_id)
        match["started_at"] = __import__("time").time()
        self.store.put("matches", self.match_id, match)
        self.guild.get_channel = lambda uid: SimpleNamespace(permissions_for=lambda user: SimpleNamespace(view_channel=True))
        await self.commands.vote.callback(self.commands, spectator, self.members[22], self.match_id)
        self.assertEqual(len(self.store.list("votes")), 1)

    def test_failed_durable_delivery_can_be_requeued(self):
        self.store.put("jobs", "close:key", {"id": "close:key", "status": "failed", "retry_at": 0})
        self.bot.enqueue("close", "key", match_id=self.match_id)
        self.assertEqual(self.store.get("jobs", "close:key")["status"], "pending")

    async def test_edit_discards_pending_analysis_and_notifies_for_sent_analysis(self):
        match = self.activate({"notification_interval": 0})
        message = self.bot.arena.record_message(self.match_id, 11, 555, "Original evidence", "https://discord.com/555")
        report = {"id": message["id"], "status": "complete", "clarifications": ["Question about original evidence?"]}
        self.bot.queue_report(match, report)
        channel = SimpleNamespace(send=AsyncMock())
        self.bot.get_channel = lambda uid: channel
        await self.bot.flush_analysis()
        self.assertEqual(channel.send.await_count, 1)
        self.bot.queue_report(match, report)
        await self.bot.on_raw_message_edit(SimpleNamespace(message_id=555, data={"content": "Changed evidence"}))
        await self.bot.flush_analysis()
        self.assertEqual(channel.send.await_count, 1)
        self.assertTrue(all(item["status"] == "stale" for item in self.store.list("analysis_outbox")))
        notifications = [job for job in self.store.list("jobs") if job["kind"] == "notify"]
        self.assertEqual(len(notifications), 1)
        self.assertIn("stale", notifications[0]["text"])

    async def test_live_scores_do_not_reveal_private_feedback(self):
        match = self.activate({"live_scores": True, "notification_interval": 0})
        await self.bot.publish_analysis(match, {"provisional_scores": {"scores": {}, "feedback": {"11": "private note"}}})
        destination = SimpleNamespace(send=AsyncMock())
        self.bot.get_channel = lambda uid: destination
        await self.bot.flush_analysis()
        self.assertNotIn("private note", destination.send.call_args.args[0])

    async def test_staff_correction_during_publication_is_never_overwritten(self):
        self.activate()
        match = self.bot.arena.end(self.match_id, "draw")
        corrected = False
        async def send(*args, **kwargs):
            nonlocal corrected
            if not corrected:
                corrected = True
                self.bot.arena.correct_result(self.match_id, 99, 22, "Review correction")
        self.bot.get_channel = lambda uid: SimpleNamespace(send=AsyncMock(side_effect=send))
        self.bot.apply_permissions = AsyncMock()
        with self.assertRaises(JobDeferred):
            await self.bot.close_match(match)
        current = self.bot.arena.get_match(self.match_id)
        self.assertEqual(current["result"]["winner_id"], 22)
        self.assertFalse(current.get("discord_closed", False))
        self.assertFalse(current.get("result_published", False))

    async def test_opening_marker_does_not_overwrite_concurrent_rule_agreement(self):
        self.bot.arena.configure(100, 99, active_category_id=888)
        self.bot.arena.accept(self.match_id, 22)
        match = self.bot.arena.get_match(self.match_id)
        category = MagicMock(spec=discord.CategoryChannel)
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 900
        channel.topic = f"Argument Arena match {self.match_id}"
        channel.send = AsyncMock()
        self.guild.text_channels = [channel]
        self.guild.get_channel = lambda uid: category if uid == 888 else channel if uid == 900 else None
        self.bot.get_guild = lambda uid: self.guild
        async def apply(*args, **kwargs):
            self.bot.arena.propose_settings(self.match_id, 11, {"discussion_threads": False})
            self.bot.arena.accept(self.match_id, 22)
        self.bot.apply_permissions = AsyncMock(side_effect=apply)
        await self.bot.ensure_channel(match)
        self.assertFalse(self.bot.arena.get_match(self.match_id)["settings"]["discussion_threads"])
        self.assertTrue(self.bot.arena.get_match(self.match_id)["opening_sent"])

    async def test_disconnect_removes_readiness_marker(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"HEALTH_DIRECTORY": directory}):
            ready = Path(directory) / "arena-ready"
            ready.write_text("1")
            self.bot._recovered = True
            await self.bot.on_disconnect()
            self.assertFalse(ready.exists())
            self.assertFalse(self.bot._recovered)


class ProcessLockTests(unittest.TestCase):
    def test_second_process_cannot_own_same_database(self):
        with TemporaryDirectory() as directory:
            path = str(Path(directory) / "arena.sqlite3")
            with database_lock(path):
                with self.assertRaises(SystemExit):
                    with database_lock(path):
                        self.fail("The second owner acquired the database")
            with database_lock(path):
                pass
