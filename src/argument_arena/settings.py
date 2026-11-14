"""Validated, fully materialized match and server policy; no secrets live here."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class ArenaError(ValueError):
    """Safe, actionable text suitable for an ephemeral interaction response."""


@dataclass(frozen=True)
class Actor:
    id: str
    guild: str
    roles: tuple[str, ...] = ()
    admin: bool = False
    bot: bool = False

    def staff(self, config: dict) -> bool:
        return self.admin or bool(set(self.roles) & set(config.get("moderator_roles", [])))


WEIGHTS = {
    "reasoning": 25,
    "evidence": 20,
    "accuracy": 15,
    "engagement": 20,
    "clarity": 10,
    "rules": 10,
}
DEFAULTS = {
    "claims": {"enabled": True, "every": 1, "detail": "full"},
    "research": {"enabled": True, "depth": 3, "sources": [], "budget": 20},
    "corrections": {"enabled": True, "confidence": 0.85, "delivery": "batched"},
    "on_demand": {"enabled": True, "limit": 10, "depth": 3},
    "fallacies": {"enabled": False, "families": [], "every": 3},
    "coaching": {"enabled": False, "delivery": "private", "every": 3},
    "civility": {"enabled": True, "strictness": "normal", "escalation": "notify_staff"},
    "live_scores": {"enabled": False, "every": 5},
    "judging": {
        "enabled": True,
        "rubric": "arena-v1",
        "weights": WEIGHTS,
        "model": "default",
        "tie_threshold": 3.0,
        "tie_policy": "draw",
    },
    "feedback": {"enabled": True, "detail": "full", "delivery": "public"},
    "turns": {"enabled": True, "first": 0, "structure": "message"},
    "inactivity": {"enabled": True, "hours": 24},
    "reminders": {"enabled": True, "before_hours": 2, "delivery": "channel"},
    "limits": {"enabled": False, "rounds": 10, "messages": 100, "characters": 4000},
    "reactions": {"enabled": True, "allowed": []},
    "threads": {"enabled": True, "create": True, "close_after": False},
    "audience": {"enabled": False, "hours": 24, "eligibility": "spectators"},
    "ranked": {"enabled": False, "preset": "ranked-v1"},
    "profiles": {"enabled": True},
    "archive": {"enabled": True, "lock_threads": False},
}
ENUMS = {
    ("claims", "detail"): {"full", "summary"},
    ("corrections", "delivery"): {"immediate", "batched"},
    ("coaching", "delivery"): {"public", "private"},
    ("civility", "strictness"): {"gentle", "normal", "strict"},
    ("civility", "escalation"): {"remind", "notify_staff"},
    ("judging", "tie_policy"): {"draw", "inconclusive"},
    ("feedback", "detail"): {"full", "summary"},
    ("feedback", "delivery"): {"public", "private"},
    ("turns", "structure"): {"message", "submit"},
    ("reminders", "delivery"): {"channel", "private"},
    ("audience", "eligibility"): {"spectators", "members"},
}


def match_settings(patch: dict | None = None, base: dict | None = None) -> dict:
    result = deepcopy(DEFAULTS if base is None else base)
    if patch is not None:
        if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
            raise ArenaError("Unknown match feature; view /match settings for available controls.")
        for feature, values in patch.items():
            if not isinstance(values, dict) or set(values) - set(DEFAULTS[feature]):
                raise ArenaError(f"Unknown parameters for {feature}.")
            result[feature].update(deepcopy(values))
    for feature, values in result.items():
        for key, value in values.items():
            expected = DEFAULTS[feature][key]
            if type(value) is not type(expected) and not (
                isinstance(expected, float) and type(value) in {int, float}
            ):
                raise ArenaError(f"Invalid type for {feature}.{key}.")
            if (feature, key) in ENUMS and value not in ENUMS[feature, key]:
                raise ArenaError(f"Invalid choice for {feature}.{key}.")
            if isinstance(value, str) and (not value or len(value) > 100):
                raise ArenaError(f"Invalid text for {feature}.{key}.")
            if isinstance(value, list) and (
                len(value) > 25 or any(not isinstance(v, str) or len(v) > 200 for v in value)
            ):
                raise ArenaError(f"Invalid list for {feature}.{key}.")
            if type(value) in {int, float} and not 0 <= value <= 10000:
                raise ArenaError(f"Out of range: {feature}.{key}.")
            if key in {"every", "depth", "hours", "rounds", "messages", "characters"} and value < 1:
                raise ArenaError(f"{feature}.{key} must be positive.")
    if result["turns"]["first"] not in (0, 1):
        raise ArenaError("turns.first must be participant 0 or 1.")
    if result["research"]["depth"] > 10 or result["on_demand"]["depth"] > 10:
        raise ArenaError("Research depth must be between 1 and 10.")
    if not 0 <= result["corrections"]["confidence"] <= 1:
        raise ArenaError("Correction confidence must be between zero and one.")
    weights = result["judging"]["weights"]
    if set(weights) != set(WEIGHTS) or any(type(v) is not int or v < 0 for v in weights.values()):
        raise ArenaError("Judging requires nonnegative integer weights for all six dimensions.")
    if sum(weights.values()) != 100:
        raise ArenaError("Judging weights must sum to 100.")
    if result["judging"]["rubric"] != "arena-v1":
        raise ArenaError("Supported rubric: arena-v1. Adjust dimension weights explicitly.")
    if not result["research"]["enabled"]:
        result["corrections"]["enabled"] = False
    if not result["judging"]["enabled"]:
        result["ranked"]["enabled"] = False
    if result["reminders"]["enabled"] and result["inactivity"]["enabled"]:
        if result["reminders"]["before_hours"] >= result["inactivity"]["hours"]:
            raise ArenaError("Reminder lead time must be shorter than the response window.")
    if result["ranked"]["enabled"]:
        required = ranked_settings()
        for feature in ("judging", "coaching", "live_scores", "turns", "inactivity", "limits"):
            if result[feature] != required[feature]:
                raise ArenaError(f"Ranked-v1 requires the shared {feature} configuration.")
        if result["ranked"]["preset"] != "ranked-v1":
            raise ArenaError("Unsupported ranked preset.")
    return result


def ranked_settings() -> dict:
    settings = deepcopy(DEFAULTS)
    settings["ranked"]["enabled"] = True
    settings["limits"].update(enabled=True, rounds=10, messages=100, characters=4000)
    return settings


def server_defaults() -> dict[str, Any]:
    return {
        "categories": {"active": None, "completed": None, "forfeited": None, "cancelled": None},
        "announcement": None,
        "results": None,
        "moderator_roles": [],
        "channel_name": "match-{id}",
        "match_prefix": "",
        "max_concurrent": 3,
        "challenge_cooldown": 60,
        "research_daily": 100,
        "llm_daily": 200,
        "llm_match": 100,
        "llm_models": {
            "analyze": "default",
            "research": "default",
            "training": "default",
            "battle": "default",
        },
        "rating_initial": 1000,
        "rating_k": 32,
        "repeat_opponent_daily": 3,
        "defaults": deepcopy(DEFAULTS),
        "presets": {
            "casual": deepcopy(DEFAULTS),
            "ranked": ranked_settings(),
            "research-off": match_settings({"research": {"enabled": False}}),
            "coaching": match_settings({"coaching": {"enabled": True}}),
        },
    }


def validate_server(config: dict) -> dict:
    if not isinstance(config, dict) or set(config) != set(server_defaults()):
        raise ArenaError("Unknown server settings.")
    if not isinstance(config["categories"], dict) or set(config["categories"]) != {
        "active",
        "completed",
        "forfeited",
        "cancelled",
    }:
        raise ArenaError("Configure all four category routes.")
    if not isinstance(config["moderator_roles"], list) or len(config["moderator_roles"]) > 25:
        raise ArenaError("Configure at most 25 moderator role IDs.")
    for value in [
        *config["categories"].values(),
        config["announcement"],
        config["results"],
        *config["moderator_roles"],
    ]:
        if value is not None and (
            not isinstance(value, str)
            or not value.isascii()
            or not value.isdecimal()
            or not 0 < int(value) < 2**64
        ):
            raise ArenaError("Category, channel and role IDs must be strings of digits.")
    if not isinstance(config["channel_name"], str) or "{id}" not in config["channel_name"]:
        raise ArenaError("channel_name must contain {id}.")
    if config["channel_name"].replace("{id}", "1").strip("abcdefghijklmnopqrstuvwxyz0123456789-"):
        raise ArenaError("Channel names support lowercase letters, digits, hyphens and {id}.")
    prefix = config["match_prefix"]
    if (
        not isinstance(prefix, str)
        or len(prefix) > 12
        or prefix.strip("abcdefghijklmnopqrstuvwxyz0123456789-")
    ):
        raise ArenaError("Match prefixes use at most 12 lowercase letters, digits or hyphens.")
    for key in (
        "max_concurrent",
        "challenge_cooldown",
        "research_daily",
        "llm_daily",
        "llm_match",
        "rating_initial",
        "rating_k",
        "repeat_opponent_daily",
    ):
        if type(config[key]) is not int or not 1 <= config[key] <= 100000:
            raise ArenaError(f"{key} must be a positive integer up to 100000.")
    models = config["llm_models"]
    if not isinstance(models, dict) or set(models) != {"analyze", "research", "training", "battle"}:
        raise ArenaError("Configure analyze, research, training and battle model names.")
    if any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in models.values()):
        raise ArenaError("Model names must be nonempty strings up to 100 characters.")
    config["defaults"] = match_settings(config["defaults"])
    if not isinstance(config["presets"], dict) or len(config["presets"]) > 20:
        raise ArenaError("At most 20 named presets are allowed.")
    for name, preset in config["presets"].items():
        if not name or len(name) > 40:
            raise ArenaError("Preset names must contain 1–40 characters.")
        config["presets"][name] = match_settings(preset)
    return config
