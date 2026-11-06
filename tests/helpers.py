import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

from argument_arena.arena import Arena
from argument_arena.assistance import Assistance
from argument_arena.profiles import Profiles
from argument_arena.settings import WEIGHTS, Actor
from argument_arena.training import Training
from argument_arena.worker import Worker

A = Actor("10", "123")
B = Actor("20", "123")
SPECTATOR = Actor("30", "123")
ADMIN = Actor("40", "123", admin=True)
STAFF = Actor("50", "123", roles=("7",))


class Clock:
    now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.responses = {}

    async def complete(self, task, data, model="default"):
        self.calls.append((task, copy.deepcopy(data), model))
        if task in self.responses:
            result = self.responses[task]
            if isinstance(result, Exception):
                raise result
            return copy.deepcopy(result(data) if callable(result) else result)
        if task == "analyze":
            return {
                "claims": [
                    {
                        "quote": data["message"]["content"],
                        "summary": "Attributed statement",
                        "kind": "factual",
                        "relations": [],
                    }
                ],
                "fallacies": [],
                "coaching": "State a testable premise and address the opposing evidence.",
                "civility": {"message": "", "escalate": False},
                "clarification": "",
            }
        if task == "research":
            return {
                "verdict": "supported",
                "confidence": 0.95,
                "explanation": "The supplied primary record directly supports the bounded claim.",
                "source_ids": [data["sources"][0]["id"]],
            }
        if task == "judge":
            return judgment(
                data["match"],
                data["messages"],
                sufficient=all(
                    any(m["author"] == p for m in data["messages"])
                    for p in data["match"]["players"]
                ),
            )
        if task == "grade":
            return {
                "identification": 1.0,
                "explanation": 0.9,
                "feedback": "You explained why the premise does not support the conclusion.",
                "alternative": "An overlapping label is reasonable with this explanation.",
            }
        if task == "battle":
            return {
                "text": "Either approve all of my plan or you oppose every improvement.",
                "quote": "Either approve all of my plan",
                "explanation": "Alternatives were excluded.",
                "repair": "Consider a narrower proposal.",
                "hint": "Are these all the choices?",
            }
        raise AssertionError(task)


def judgment(match, messages, a=80, b=60, accuracy=None, sufficient=True):
    return {
        "sufficient": sufficient,
        "explanation": "Reasons are assessed under the accepted rubric.",
        "participants": {
            p: {
                "scores": {d: accuracy if d == "accuracy" else score for d in WEIGHTS},
                "references": [m["id"] for m in messages if m["author"] == p],
                "explanation": "The cited passage develops a premise and addresses the objection.",
                "strengths": ["Clear premise with a specific example."],
                "needs": ["Address the opposing example directly."],
                "unanswered": ["The scope objection remains open."],
                "practice": ["Straw man"],
            }
            for p, score in zip(match["players"], (a, b), strict=True)
        },
    }


class FakeResearch:
    def __init__(self):
        self.calls = []
        self.sources = [
            {
                "url": "https://records.example.org/report",
                "title": "Primary record",
                "text": "The measured value is 12 in the defined sample.",
                "published": "2026-01-01",
                "retrieved": 1_800_000_001,
                "sha256": "a" * 64,
                "provenance": "HTTPS page retrieval",
                "last_modified": None,
            }
        ]
        self.error = None

    async def search(self, query, depth, preferred):
        self.calls.append((query, depth, preferred))
        if self.error:
            raise self.error
        return copy.deepcopy(self.sources[:depth])

    async def fetch(self, url):
        source = copy.deepcopy(self.sources[0])
        source["url"] = url
        return source


def services(storage, clock):
    arena = Arena(storage, clock)
    llm, research = FakeLLM(), FakeResearch()
    assistance, training, profiles = (
        Assistance(arena, llm, research),
        Training(arena, llm),
        Profiles(arena),
    )
    gateway = SimpleNamespace(
        create=AsyncMock(),
        archive=AsyncMock(),
        notice=AsyncMock(),
        reconcile=AsyncMock(),
        permissions=AsyncMock(),
    )
    client = SimpleNamespace(gateway_ready=True, is_ready=lambda: True)
    worker = Worker(client, arena, assistance, training, profiles, gateway)
    return SimpleNamespace(
        arena=arena,
        llm=llm,
        research=research,
        assistance=assistance,
        training=training,
        profiles=profiles,
        gateway=gateway,
        worker=worker,
        clock=clock,
    )


async def configure(arena):
    await arena.setup(
        ADMIN,
        {
            "categories": {"active": "1", "completed": "2", "forfeited": "3", "cancelled": "4"},
            "moderator_roles": ["7"],
            "challenge_cooldown": 1,
        },
    )


async def pending(arena, patch=None, preset="casual"):
    match = await arena.challenge(
        A,
        B.id,
        "Technology and public evidence",
        ["Support the trial", "Oppose the trial"],
        "https://discord.com/channels/123/999",
        preset,
    )
    if patch:
        match = await arena.settings(A, match["id"], patch)
    return match


async def active(arena, patch=None, preset="casual"):
    match = await pending(arena, patch, preset)
    await arena.accept(A, match["id"], match["revision"])
    await arena.accept(B, match["id"], match["revision"])
    await arena.attach_channel(match["id"], str(int(match["id"], 16)))
    return await arena.repo.match(match["id"])


async def message(arena, match, author=A, message_id="100", content="The measured value is 12."):
    return await arena.message(
        A.guild,
        match["channel"],
        message_id,
        author.id,
        content,
        f"https://discord.com/channels/123/{match['channel']}/{message_id}",
        arena.clock(),
    )


async def drain(bundle, limit=30):
    for _ in range(limit):
        jobs = await bundle.arena.repo.jobs(bundle.clock())
        if not jobs:
            return
        for job in jobs:
            from argument_arena.providers import ProviderError

            try:
                await bundle.worker.dispatch(job)
            except ProviderError as error:
                if error.status != "waiting_for_evidence":
                    raise
                await bundle.arena.repo.defer_job(job["id"], bundle.clock(), seconds=0)
            else:
                await bundle.arena.repo.job_done(job["id"])
    raise AssertionError("Jobs did not drain")
