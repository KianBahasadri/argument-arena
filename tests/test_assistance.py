import json

import pytest

from argument_arena.providers import ProviderError
from argument_arena.settings import ArenaError
from tests.helpers import A, B, active, drain, message


async def test_attributed_claims_sources_and_correction_history(product):
    match = await active(product.arena)
    await message(product.arena, match)
    await drain(product)
    claim = (await product.assistance.claims(match["id"], A.guild))[0]
    assert claim["id"] == "C100-1-1" and claim["author"] == A.id
    assert claim["quote"] == "The measured value is 12." and claim["url"].endswith("/100")
    check = claim["history"][0]
    assert claim["status"] == "supported" and check["sources"][0]["published"] == "2026-01-01"
    assert check["sources"][0]["sha256"] and check["source_ids"] == ["S1"]
    product.llm.responses["research"] = {
        "verdict": "contradicted",
        "confidence": 0.96,
        "source_ids": ["S1"],
        "explanation": "A corrected primary record reports a different measurement.",
    }
    await product.assistance.dispute(
        A,
        match["id"],
        claim["id"],
        "The scope of this measurement was misread.",
        "https://records.example.org/correction",
    )
    await drain(product)
    corrected = await product.arena.repo.claim(claim["id"], A.guild)
    assert corrected["status"] == "contradicted" and len(corrected["history"]) == 2
    assert corrected["history"][-1]["sources"][-1]["url"].endswith("/correction")
    async with product.arena.repo.unit() as unit:
        notices = await unit.rows("SELECT due FROM jobs WHERE id LIKE 'correction:%'")
    assert len(notices) == 1 and notices[0]["due"] == product.clock() + 60


async def test_on_demand_independent_of_background_and_visibility(product):
    match = await active(
        product.arena, {"research": {"enabled": False}, "claims": {"enabled": False}}
    )
    await message(product.arena, match)
    await drain(product)
    assert product.research.calls == []
    with pytest.raises(ArenaError, match="disabled"):
        await product.assistance.claims(match["id"], A.guild)
    claim = await product.arena.repo.claim("C100-1-1", A.guild)
    assert claim["status"] == "not_requested"
    await product.assistance.check(A, claim["id"])
    await product.assistance.check(A, claim["id"])  # pending request is idempotent
    await drain(product)
    assert (await product.arena.repo.claim(claim["id"], A.guild))["status"] == "supported"
    assert len(product.research.calls) == 1


@pytest.mark.parametrize("kind", ["value", "opinion", "definition", "prediction", "question"])
async def test_nonfactual_claims_are_not_researched(product, kind):
    match = await active(product.arena)
    product.llm.responses["analyze"] = {"claims": [{"quote": "This policy is good.", "kind": kind}]}
    await message(product.arena, match, content="This policy is good.")
    await drain(product)
    claim = await product.assistance.check(A, "C100-1-1")
    assert claim["status"] == "not fact-checkable" and not product.research.calls


async def test_missing_sources_never_become_a_factual_correction(product):
    match = await active(product.arena)
    product.research.sources = []
    await message(product.arena, match)
    await drain(product)
    claim = await product.arena.repo.claim("C100-1-1", A.guild)
    assert claim["status"] == "insufficient evidence"
    assert not any(task == "research" for task, _, _ in product.llm.calls)
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM jobs WHERE id LIKE 'correction:%'")


async def test_research_outage_and_budget_status_are_honest(product):
    match = await active(product.arena, {"research": {"budget": 1}})
    product.research.error = ProviderError("rate_limited")
    await message(product.arena, match)
    await product.worker.once()
    await product.worker.once()
    claim = await product.arena.repo.claim("C100-1-1", A.guild)
    assert claim["status"] == "rate_limited" and "verdict" not in claim["history"][-1]
    product.research.error = None
    await product.assistance.check(A, claim["id"])
    await drain(product)
    claim = await product.arena.repo.claim(claim["id"], A.guild)
    assert claim["status"] == "budget_limited"


async def test_edited_deleted_claims_are_stale_and_never_silently_reused(product):
    match = await active(product.arena)
    await message(product.arena, match)
    await drain(product)
    await product.arena.edit_message("100", "The measured value is 13.")
    with pytest.raises(ArenaError, match="source changed"):
        await product.assistance.check(A, "C100-1-1")
    await drain(product)
    claims = await product.assistance.claims(match["id"], A.guild)
    assert len(claims) == 2 and claims[0]["stale"]
    assert claims[1]["id"] == "C100-2-1" and not claims[1]["stale"]
    await product.arena.edit_message("100", deleted=True)
    assert (await product.arena.repo.claim("C100-2-1", A.guild))["stale"]


@pytest.mark.parametrize(
    "response,status",
    [
        ({"claims": [{"quote": "Invented wording", "kind": "factual"}]}, "ungrounded_claim"),
        (
            {"claims": [{"quote": "The measured value is 12.", "kind": "invented"}]},
            "invalid_model_response",
        ),
        (
            {
                "claims": [
                    {
                        "quote": "The measured value is 12.",
                        "kind": "factual",
                        "relations": [{"target": "other-match", "type": "supports"}],
                    }
                ]
            },
            "invalid_claim_relation",
        ),
        (
            {"fallacies": [{"quote": "invented", "label": "fallacy", "explanation": "reason"}]},
            "ungrounded_fallacy",
        ),
    ],
)
async def test_extraction_rejects_ungrounded_provider_output(product, response, status):
    match = await active(product.arena)
    await message(product.arena, match)
    product.llm.responses["analyze"] = response
    with pytest.raises(ProviderError, match=status):
        await drain(product)
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM claims")


async def test_claim_graph_moderation_coaching_and_frequency(product):
    match = await active(
        product.arena,
        {
            "research": {"enabled": False},
            "fallacies": {"enabled": True, "every": 1},
            "coaching": {"enabled": True, "every": 1},
            "live_scores": {"enabled": True, "every": 2},
        },
    )
    product.llm.responses["analyze"] = lambda data: {
        "claims": [
            {
                "quote": data["message"]["content"],
                "kind": "factual",
                "relations": []
                if data["message"]["id"] == "100"
                else [{"target": "C100-1-1", "type": "rebuttal"}],
            }
        ],
        "fallacies": [
            {
                "quote": data["message"]["content"],
                "label": "Hasty generalization",
                "explanation": "This small sample cannot establish the city-wide claim.",
            }
        ],
        "coaching": "Define the relevant population.",
        "civility": {"message": "Address the premise, not the person.", "escalate": True},
    }
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    await drain(product)
    claim = await product.arena.repo.claim("C101-1-1", A.guild)
    assert claim["relations"] == [{"target": "C100-1-1", "type": "rebuttal"}]
    async with product.arena.repo.unit() as unit:
        notices = await unit.rows("SELECT id,data FROM jobs WHERE kind='notice'")
    private = [json.loads(r["data"]) for r in notices if r["id"].startswith("coaching:")]
    assert {r["user"] for r in private} == {A.id, B.id}
    assert len([r for r in notices if r["id"].startswith("live-notice:")]) == 1
