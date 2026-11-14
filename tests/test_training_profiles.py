import json

import pytest

from argument_arena.curriculum import LIBRARY
from argument_arena.providers import ProviderError
from argument_arena.settings import ArenaError
from tests.helpers import SPECTATOR, A, B, active, drain, message
from tests.test_competition import completed


@pytest.mark.parametrize("mode", ["spot", "selected", "mixed", "battle", "repair", "sound"])
async def test_all_training_modes_original_references_and_durable_grading(product, mode):
    session = await product.training.start(
        A,
        mode,
        "false dichotomy" if mode == "selected" else None,
        difficulty=2,
        topic="urban gardens",
    )
    assert "urban gardens" in session["prompt"] and "Bo Bennett" in session["attribution"]
    assert "fallacy" not in session
    hint = await product.training.hint(A)
    assert hint
    await product.training.answer(
        A, "The offered alternatives exclude partial changes; the conclusion is unsupported."
    )
    await drain(product)
    progress = await product.training.progress(A)
    assert progress["attempts"] == 1 and progress["latest"]["last_feedback"]["hints"] == 1
    feedback = progress["latest"]["last_feedback"]
    assert feedback["identification"] == 1 and feedback["explanation"] == 0.9
    assert feedback["reference"].startswith("https://www.logicallyfallacious.com/logicalfallacies/")
    if mode == "battle":
        assert progress["latest"]["turn"] == 2 and progress["latest"]["state"] == "active"
        for _ in range(2):
            await product.training.answer(
                A, "The conclusion skips relevant alternatives and needs independent evidence."
            )
            await drain(product)
        assert (await product.training.progress(A))["latest"]["state"] == "complete"
    else:
        assert progress["latest"]["state"] == "complete"
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT * FROM rating_changes")


async def test_explanations_and_alternative_labels_are_supplied_to_grader(product):
    await product.training.start(A, "selected", "false dilemma")
    explanation = (
        "A false dichotomy: it omits revisions, delay and partial adoption, "
        "so these are not exhaustive choices."
    )
    await product.training.answer(A, explanation)
    await drain(product)
    task, data, _ = next(call for call in product.llm.calls if call[0] == "grade")
    assert task == "grade" and data["answer"] == explanation
    assert "false dichotomy" in data["exercise"]["aliases"]
    progress = await product.training.progress(A)
    assert progress["attempts"] == 1
    # Replaying the durable grade job does not double progress.
    async with product.arena.repo.unit() as unit:
        row = await unit.one("SELECT * FROM jobs WHERE kind='train_grade'")
    row["data"] = json.loads(row["data"])
    await product.training.grade(row)
    assert (await product.training.progress(A))["attempts"] == 1


async def test_training_unavailable_failure_retry_and_ownership(product):
    await product.training.start(A)
    with pytest.raises(ArenaError, match="No active"):
        await product.training.hint(B)
    with pytest.raises(ArenaError, match="current exercise"):
        await product.training.start(A)
    product.llm.responses["grade"] = ProviderError("not_configured", retry=False)
    await product.training.answer(A, "A full explanation of the reasoning error in the example.")
    await product.worker.once()
    assert (await product.training.progress(A))["latest"]["state"] == "grading"
    assert (await product.training.progress(A))["attempts"] == 0
    async with product.arena.repo.unit() as unit:
        job = await unit.one("SELECT state,error FROM jobs WHERE kind='train_grade'")
    assert job == {"state": "failed", "error": "not_configured"}
    product.llm.responses.pop("grade")
    await product.training.retry(A)
    await drain(product)
    assert (await product.training.progress(A))["attempts"] == 1


async def test_hints_difficulty_valid_examples_and_recommendations(product):
    with pytest.raises(ArenaError):
        await product.training.start(A, difficulty=9)
    for _ in range(2):
        session = await product.training.start(A, "sound", difficulty=3)
        assert session["difficulty"] == 3
        await product.training.answer(
            A, "The premise must independently justify the conclusion; these terms need analysis."
        )
        await drain(product)
    progress = await product.training.progress(A)
    assert "valid" in progress["by_fallacy"] and len(progress["by_fallacy"]) == 2
    assert len(progress["recommendations"]) == 2
    assert len(LIBRARY) > 8


async def test_profile_requires_both_user_and_match_consent_and_visibility(product):
    match = await completed(product, "casual")
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
    with pytest.raises(ArenaError, match="private"):
        await product.profiles.view(SPECTATOR, A.id)
    await product.profiles.settings(A, {"analysis": True})
    product.clock.advance(2)
    disabled = await active(
        product.arena, {"profiles": {"enabled": False}, "judging": {"enabled": False}}
    )
    await message(product.arena, disabled, message_id="300")
    await product.arena.action(A, disabled["id"], "concede")
    await drain(product)
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
    product.clock.advance(2)
    enabled = await completed(product, "casual")
    profile = await product.profiles.view(A, A.id)
    assert profile["sample_matches"] == 1 and profile["sample_claims"] == 1
    assert profile["history"][0]["match"] == enabled["id"]
    assert "personal belief" in profile["history"][0]["position_policy"]
    assert "At least 3" in profile["themes"]
    assert (await product.profiles.view(B, B.id))["sample_matches"] == 0
    await product.profiles.settings(A, {"visibility": "public"})
    assert (await product.profiles.view(SPECTATOR, A.id))["sample_matches"] == 1
    assert match["id"] != enabled["id"]


async def test_profile_evidence_sample_sizes_changes_correction_and_removal(product):
    await product.profiles.settings(A, {"analysis": True, "visibility": "public"})
    matches = []
    for _ in range(3):
        product.clock.advance(2)
        matches.append(await completed(product, "casual"))
    profile = await product.profiles.view(A, A.id)
    assert profile["sample_matches"] == 3 and profile["themes"]["factual"] == 3
    assert all(i["evidence"][0]["url"] and i["sample_claims"] == 1 for i in profile["history"])
    assert len(profile["change_over_time"]) == 3 and profile["recommendations"] == ["Straw man"]
    await product.profiles.correct(
        A,
        matches[0]["id"],
        "This was an assigned position and should not be generalized.",
        exclude=True,
    )
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 2
    await product.profiles.generate(matches[0]["id"])
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 2
    await product.profiles.remove(A)
    for match in matches:
        await product.profiles.generate(match["id"])
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
    assert not (await product.profiles.settings(A))["analysis"]
    await product.profiles.settings(A, {"analysis": True})
    for match in matches:
        await product.profiles.generate(match["id"])
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT * FROM documents WHERE kind='insight'")


async def test_disabling_future_profile_analysis_and_edits_remove_stale_insights(product):
    await product.profiles.settings(A, {"analysis": True})
    match = await completed(product)
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 1
    await product.arena.edit_message(match["id"] + "1", "A different argument after completion.")
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
    await product.profiles.settings(A, {"analysis": False})
    product.clock.advance(2)
    await completed(product, "casual")
    assert (await product.profiles.view(A, A.id))["sample_matches"] == 0
