"""Single supervised durable worker. Fatal storage errors fail readiness and stop the process."""

import asyncio
import logging

import discord

from argument_arena.providers import ProviderError
from argument_arena.settings import ArenaError

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, client, arena, assistance, training, profiles, gateway):
        self.client, self.arena, self.repo = client, arena, arena.repo
        self.assistance, self.training, self.profiles, self.gateway = (
            assistance,
            training,
            profiles,
            gateway,
        )
        self.reconcile_needed = True

    async def run(self):
        while True:
            await self.once()
            await asyncio.sleep(15)

    async def once(self):
        connected = self.client.gateway_ready and self.client.is_ready()
        if connected and self.reconcile_needed:
            await self.arena.tick(False)
            try:
                await self.gateway.reconcile()
            except (discord.HTTPException, ProviderError):
                logger.warning("reconciliation_unavailable")
                return  # Never forfeit before reconciling a missing interval.
            self.reconcile_needed = False
        await self.arena.tick(connected)
        if not connected:
            self.reconcile_needed = True
            return
        for job in await self.repo.jobs(self.arena.clock()):
            try:
                await self.dispatch(job)
            except ProviderError as error:
                if error.status == "waiting_for_evidence":
                    await self.repo.defer_job(job["id"], self.arena.clock())
                    continue
                await self.repo.job_failed(job["id"], self.arena.clock(), error.status, error.retry)
                logger.warning("provider_job_unavailable")
            except ArenaError:
                await self.repo.job_failed(
                    job["id"], self.arena.clock(), "budget_or_policy_limit", False
                )
            except discord.HTTPException as error:
                await self.repo.job_failed(
                    job["id"],
                    self.arena.clock(),
                    "discord_unavailable",
                    error.status == 429 or error.status >= 500,
                )
                if error.status == 429 or error.status >= 500:
                    self.reconcile_needed = True
                    await self.arena.tick(False)
                logger.warning("discord_job_unavailable")
            else:
                await self.repo.job_done(job["id"])

    async def dispatch(self, job):
        match job["kind"]:
            case "create":
                await self.gateway.create(job)
            case "archive":
                await self.gateway.archive(job)
            case "permissions":
                await self.gateway.permissions(job)
            case "notice":
                await self.gateway.notice(job)
            case "analyze":
                await self.assistance.analyze(job)
            case "research":
                await self.assistance.research_claim(job)
            case "judge" | "live":
                await self.assistance.judge(job, live=job["kind"] == "live")
            case "feedback":
                await self.assistance.judge(job, feedback_only=True)
            case "train_grade":
                await self.training.grade(job)
            case "profile":
                await self.profiles.generate(job["match_id"])
            case _:
                raise ProviderError("unknown_job_kind", retry=False)
