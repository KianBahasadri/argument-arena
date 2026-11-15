"""Synthetic UI examples, never model evaluations or requests to an inference service."""

import hashlib

from argument_arena.config import DEFAULT_LLM_MODEL
from argument_arena.providers import ProviderError
from argument_arena.settings import WEIGHTS


class SampleAI:
    def __init__(self):
        self.unavailable = False

    async def complete(self, task, data, model="default"):
        if model not in {"default", DEFAULT_LLM_MODEL}:
            raise ProviderError("model_not_enabled", retry=False)
        if self.unavailable:
            raise ProviderError("not_configured", retry=False)
        if task == "analyze":
            return {
                "claims": [
                    {
                        "quote": data["message"]["content"],
                        "summary": "Sample claim for UI preview",
                        "kind": "factual",
                        "relations": [],
                    }
                ],
                "fallacies": [],
                "coaching": "Sample coaching: explain how the evidence supports your premise.",
                "civility": {"message": "", "escalate": False},
                "clarification": "",
            }
        if task == "research":
            return {
                "verdict": "insufficient evidence",
                "confidence": 0,
                "explanation": "Sample result only. No websites were searched and no real "
                "evidence was assessed.",
                "source_ids": [],
            }
        if task == "judge":
            return {
                "sufficient": all(
                    any(m["author"] == p for m in data["messages"])
                    for p in data["match"]["players"]
                ),
                "explanation": "Sample judgment for preview. Both participants receive fixed "
                "example scores; this does not assess their arguments.",
                "participants": {
                    p: {
                        "scores": dict.fromkeys(WEIGHTS, 70),
                        "references": [m["id"] for m in data["messages"] if m["author"] == p],
                        "explanation": "Sample reasoning summary for the result layout.",
                        "strengths": ["Sample strength: a clear premise."],
                        "needs": ["Sample suggestion: address the opposing evidence."],
                        "unanswered": [],
                        "practice": ["Straw man"],
                    }
                    for p in data["match"]["players"]
                },
            }
        if task == "grade":
            return {
                "identification": 0.5,
                "explanation": 0.5,
                "feedback": "Sample feedback with a fixed 50% score. Your answer has not "
                "been evaluated by an AI.",
                "alternative": "The live bot uses MiniMax M3.1 Flash through OpenCode Go "
                "for actual grading.",
            }
        if task == "battle":
            return {
                "text": "Either accept every part of my plan or you oppose all progress.",
                "quote": "Either accept every part of my plan",
                "explanation": "Sample turn: the argument excludes other possible choices.",
                "repair": "Consider the individual proposals and their evidence.",
                "hint": "Are there more than two choices?",
            }
        raise ProviderError("unknown_task", retry=False)


class SampleResearch:
    def __init__(self, ai, clock):
        self.ai, self.clock = ai, clock

    async def fetch(self, url):
        if self.ai.unavailable:
            raise ProviderError("not_configured", retry=False)
        content = "Synthetic source for testing the evidence interface. This is not real evidence."
        return {
            "url": url,
            "title": "Sample source — not retrieved from the web",
            "text": content,
            "published": None,
            "retrieved": self.clock(),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "provenance": "Offline playground fixture; no network request",
            "last_modified": None,
        }

    async def search(self, query, depth, preferred):
        return [await self.fetch("https://playground.invalid/sample-source")]
