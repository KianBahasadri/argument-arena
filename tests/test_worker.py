import asyncio

from argument_arena.providers import ProviderError
from argument_arena.repository import Repository
from argument_arena.storage import MIGRATIONS, Storage
from tests.helpers import ADMIN, A, B, active, message


async def test_jobs_survive_restart_reclaim_expired_lease_and_retry_caps(product):
    match = await active(product.arena)
    async with product.arena.repo.unit() as unit:
        await unit.db.execute("UPDATE jobs SET state='done'")
        await unit.job(
            "recover",
            "analyze",
            match["id"],
            {"message": "missing", "revision": 1},
            product.clock(),
        )
    jobs = await product.arena.repo.jobs(product.clock())
    assert len(jobs) == 1
    repo = Repository(product.arena.repo.storage)
    assert await repo.jobs(product.clock()) == []
    product.clock.advance(181)
    reclaimed = await repo.jobs(product.clock())
    assert reclaimed[0]["id"] == "recover"
    for _ in range(5):
        await repo.job_failed("recover", product.clock(), "rate_limited")
        product.clock.advance(3601)
        await repo.jobs(product.clock())
    async with repo.unit() as unit:
        row = await unit.one("SELECT state,error FROM jobs WHERE id='recover'")
    assert row == {"state": "failed", "error": "rate_limited"}
    await product.arena.retry(ADMIN, match["id"])
    await product.worker.once()
    async with repo.unit() as unit:
        assert (await unit.one("SELECT state FROM jobs WHERE id='recover'"))["state"] == "done"


async def test_worker_never_forfeits_until_reconciliation_succeeds(product):
    match = await active(product.arena)
    product.clock.advance(172800)
    product.gateway.reconcile.side_effect = ProviderError("network_failed")
    await product.worker.once()
    assert (await product.arena.repo.match(match["id"]))["state"] == "active"
    assert product.worker.reconcile_needed
    product.gateway.reconcile.side_effect = None
    await product.worker.once()
    assert not product.worker.reconcile_needed
    assert (await product.arena.repo.match(match["id"]))["deadline"] > product.clock()
    product.worker.client.gateway_ready = False
    product.clock.advance(30)
    await product.worker.once()
    assert product.worker.reconcile_needed


async def test_worker_records_malformed_provider_failure_without_crashing(product):
    match = await active(product.arena)
    await message(product.arena, match)
    product.llm.responses["analyze"] = {
        "claims": [{"kind": [], "quote": "The measured value is 12."}]
    }
    await product.worker.once()
    async with product.arena.repo.unit() as unit:
        row = await unit.one("SELECT state,error FROM jobs WHERE kind='analyze'")
    assert row["error"] == "invalid_model_response" and row["state"] == "pending"


async def test_foundation_upgrade_migrates_product_atomically_and_preserves_existing_settings(
    tmp_path,
):
    path = tmp_path / "upgrade.sqlite3"
    async with Storage(path, MIGRATIONS[:1]) as storage:
        await storage.put("guild:123", "existing", {"kept": True})
    async with Storage(path) as storage:
        assert await storage.get("guild:123", "existing") == {"kept": True}
        async with storage.transaction() as db:
            assert (await (await db.execute("SELECT count(*) FROM matches")).fetchone())[0] == 0
    async with Storage(path) as storage:
        assert await storage.get("guild:123", "existing") == {"kept": True}


async def test_competing_end_actions_produce_one_result(product):
    match = await active(product.arena)
    outcomes = await asyncio.gather(
        product.arena.action(A, match["id"], "concede"),
        product.arena.action(B, match["id"], "concede"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ValueError) for result in outcomes) == 1
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT * FROM results")) == 1
