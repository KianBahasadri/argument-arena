import asyncio
import json

import pytest

from argument_arena.assistance import validate_judgment
from argument_arena.competition import leaderboard
from argument_arena.providers import ProviderError
from argument_arena.settings import ArenaError
from tests.helpers import ADMIN, SPECTATOR, A, B, active, drain, judgment, message


async def completed(product, preset="ranked", finish=True):
    match = await active(product.arena, preset=preset)
    await message(product.arena, match, A, match["id"] + "1")
    await message(product.arena, match, B, match["id"] + "2")
    await drain(product)
    if finish:
        await product.arena.action(A, match["id"], "finish")
        await product.arena.action(B, match["id"], "finish")
        await drain(product)
    return match


async def test_judging_breakdown_feedback_and_elo_are_idempotent(product):
    match = await completed(product)
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "judged" and result["winner"] == A.id and result["rated"]
    assert result["rating_changes"][A.id] == [1000, 1016]
    assert result["rating_changes"][B.id] == [1000, 984]
    assert result["report"]["weights"]["reasoning"] == 25
    assert result["report"]["participants"][A.id]["references"] == [match["id"] + "1"]
    await product.arena.judged(match["id"], 2, result["report"])
    await drain(product)
    board = await leaderboard(product.arena.repo, A.guild)
    assert board[0]["rating"] == 1016 and board[0]["wins"] == 1
    assert len(board[0]["matches"]) == 1


async def test_casual_training_and_insufficient_activity_never_change_ratings(product):
    match = await completed(product, "casual")
    assert not (await product.arena.result(match["id"], A.guild))["rated"]
    product.clock.advance(2)
    sparse = await active(product.arena, preset="ranked")
    await product.arena.action(A, sparse["id"], "concede")
    assert not (await product.arena.result(sparse["id"], A.guild))["rated"]
    assert await leaderboard(product.arena.repo, A.guild) == []


async def test_staff_amendment_replays_all_later_matches_and_records_reason(product):
    first = await completed(product)
    product.clock.advance(2)
    second = await completed(product)
    before = (await leaderboard(product.arena.repo, A.guild))[0]["rating"]
    with pytest.raises(ArenaError, match="moderator"):
        await product.arena.correct(
            SPECTATOR, first["id"], "judged", B.id, "A proper review explanation."
        )
    await product.arena.correct(
        ADMIN, first["id"], "judged", B.id, "Reviewed the cited rebuttal and corrected the result."
    )
    board = await leaderboard(product.arena.repo, A.guild)
    assert all(r["rating"] != before for r in board)
    result = await product.arena.result(second["id"], A.guild)
    assert result["rating_changes"][A.id][0] == 984
    async with product.arena.repo.unit() as unit:
        events = await unit.rows("SELECT * FROM events WHERE kind='result_amended'")
    assert len(events) == 1 and "previous" in json.loads(events[0]["data"])


async def test_edits_withdraw_rating_until_review_and_do_not_reclose(product):
    match = await completed(product)
    await product.arena.edit_message(match["id"] + "1", "A changed argument.")
    result = await product.arena.result(match["id"], A.guild)
    assert result["review_needed"] and not result["rated"]
    assert not await leaderboard(product.arena.repo, A.guild)
    await product.arena.correct(
        ADMIN,
        match["id"],
        "inconclusive",
        None,
        "The edited transcript no longer supports the old judgment.",
    )
    assert (await product.arena.result(match["id"], A.guild))["report"] is None


async def test_ranking_filters_repeat_opponent_cap_and_forfeit_records(product):
    await product.arena.setup(ADMIN, {"repeat_opponent_daily": 1})
    first = await completed(product)
    product.clock.advance(2)
    second = await completed(product)
    assert not (await product.arena.result(second["id"], A.guild))["rated"]
    assert len(await leaderboard(product.arena.repo, A.guild, topic="technology", minimum=1)) == 2
    assert not await leaderboard(product.arena.repo, A.guild, topic="art")
    assert not await leaderboard(product.arena.repo, A.guild, since=product.clock())
    assert not await leaderboard(product.arena.repo, A.guild, format_name="other")
    assert not await leaderboard(product.arena.repo, A.guild, minimum=2)
    await product.arena.correct(
        ADMIN,
        first["id"],
        "forfeit",
        A.id,
        "Required speaker did not respond after an observed deadline.",
    )
    assert (await leaderboard(product.arena.repo, A.guild))[1]["forfeits"] == 1


@pytest.mark.parametrize(
    "a,b,sufficient,expected",
    [(80, 60, True, "judged"), (70, 71, True, "draw"), (90, 20, False, "inconclusive")],
)
async def test_judging_ties_inconclusive_and_value_only_weighting(
    product, a, b, sufficient, expected
):
    match = await active(product.arena)
    messages = [{"id": "100", "author": A.id}, {"id": "101", "author": B.id}]
    report = validate_judgment(
        match, messages, [], judgment(match, messages, a, b, None, sufficient)
    )
    assert report["outcome"] == expected
    assert report["totals"][A.id] == a


async def test_judge_rejects_fabricated_references_and_invalid_scores(product):
    match = await active(product.arena)
    messages = [{"id": "100", "author": A.id}, {"id": "101", "author": B.id}]
    raw = judgment(match, messages)
    raw["participants"][A.id]["references"] = ["invented"]
    with pytest.raises(ProviderError, match="references"):
        validate_judgment(match, messages, [], raw)
    raw = judgment(match, messages)
    raw["participants"][A.id]["scores"]["reasoning"] = 101
    with pytest.raises(ProviderError, match="scores"):
        validate_judgment(match, messages, [], raw)


async def test_judging_detects_edit_during_provider_call(product):
    match = await completed(product, finish=False)
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    original = product.llm.complete
    called, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(task, data, model="default"):
        if task == "judge":
            called.set()
            await proceed.wait()
        return await original(task, data, model)

    product.llm.complete = delayed
    job = {"id": "test-judge", "match_id": match["id"], "data": {}}
    task = asyncio.create_task(product.assistance.judge(job))
    await called.wait()
    await product.arena.edit_message(match["id"] + "1", "A revised official argument.")
    proceed.set()
    await task
    assert (await product.arena.result(match["id"], A.guild))["state"] == "judging"
    async with product.arena.repo.unit() as unit:
        assert await unit.one("SELECT id FROM jobs WHERE id LIKE ?", (f"judge:{match['id']}:3:%",))


async def test_evidence_revision_during_judging_requeues_current_snapshot(product):
    match = await completed(product, finish=False)
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    original = product.llm.complete
    called, proceed = asyncio.Event(), asyncio.Event()

    async def delayed(task, data, model="default"):
        if task == "judge":
            called.set()
            await proceed.wait()
        return await original(task, data, model)

    product.llm.complete = delayed
    task = asyncio.create_task(
        product.assistance.judge({"id": "evidence-race", "match_id": match["id"], "data": {}})
    )
    await called.wait()
    await product.assistance.dispute(
        A, match["id"], f"C{match['id']}1-1-1", "This measurement requires an additional source."
    )
    proceed.set()
    await task
    assert (await product.arena.result(match["id"], A.guild))["state"] == "judging"


async def test_new_contrary_evidence_marks_judged_result_for_review(product):
    match = await completed(product)
    claim_id = f"C{match['id']}1-1-1"
    product.llm.responses["research"] = {
        "verdict": "contradicted",
        "confidence": 0.95,
        "source_ids": ["S1"],
        "explanation": "The corrected primary record contradicts the original claim.",
    }
    await product.assistance.dispute(
        A, match["id"], claim_id, "The source measurement has since been corrected."
    )
    await drain(product)
    result = await product.arena.result(match["id"], A.guild)
    assert result["review_needed"] and not result["rated"]


async def test_staff_can_close_pending_judging_with_an_explicit_reviewed_decision(product):
    match = await completed(product, finish=False)
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    result = await product.arena.close_match(
        ADMIN,
        match["id"],
        "inconclusive",
        None,
        "The judge provider is unavailable; no supported judgment can be made.",
    )
    assert result["report"] is None and result["staff_review"]["actor"] == ADMIN.id
    assert result["outcome"] == "inconclusive" and not result["rated"]
