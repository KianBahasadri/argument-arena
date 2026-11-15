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
            raise ArenaError(
                "The settings patch contains an unknown match feature or is not an object. "
                "Open Features from your current match or challenge setup and choose a "
                "supported feature from its menu. Advanced policy patches must use the "
                "documented feature names."
            )
        for feature, values in patch.items():
            if not isinstance(values, dict) or set(values) - set(DEFAULTS[feature]):
                raise ArenaError(
                    f"The {feature} settings contain an unknown parameter or are not an object. "
                    "Open this feature from the Features menu and choose a supported parameter. "
                    "For an advanced patch, use the documented parameter names for this feature."
                )
            result[feature].update(deepcopy(values))
    for feature, values in result.items():
        for key, value in values.items():
            expected = DEFAULTS[feature][key]
            if type(value) is not type(expected) and not (
                isinstance(expected, float) and type(value) in {int, float}
            ):
                expected_type = {
                    bool: "true or false (without quotation marks)",
                    int: "a whole number",
                    float: "a number",
                    str: "text",
                    list: "a list of text values",
                    dict: "an object containing the documented fields",
                }[type(expected)]
                raise ArenaError(
                    f"Invalid type for {feature}.{key}: use {expected_type}. "
                    "Reopen the feature's parameter menu or correct that field in the "
                    "advanced policy patch before saving."
                )
            if (feature, key) in ENUMS and value not in ENUMS[feature, key]:
                choices = ", ".join(sorted(ENUMS[feature, key]))
                raise ArenaError(
                    f"Invalid choice for {feature}.{key}. Supported values: {choices}. "
                    "Reopen the feature's parameter menu and select one of those options."
                )
            if isinstance(value, str) and (not value or len(value) > 100):
                raise ArenaError(
                    f"The {feature}.{key} value must contain 1–100 characters. "
                    "Reopen the parameter form and enter a shorter, nonempty value. "
                    "For judging's model, use default to keep the operator's OpenCode Go model."
                )
            if isinstance(value, list) and (
                len(value) > 25 or any(not isinstance(v, str) or len(v) > 200 for v in value)
            ):
                raise ArenaError(
                    f"The {feature}.{key} list allows at most 25 text entries, each no longer "
                    "than 200 characters. Reopen the parameter form and put one entry on "
                    "each line. In advanced server settings, enter one text value per entry."
                )
            if type(value) in {int, float} and not 0 <= value <= 10000:
                raise ArenaError(
                    f"The {feature}.{key} value is outside its allowed range of 0–10000. "
                    "Reopen the parameter form and enter a value in that range; durations, "
                    "frequencies, depths and limits must also be greater than zero."
                )
            if key in {"every", "depth", "hours", "rounds", "messages", "characters"} and value < 1:
                raise ArenaError(
                    f"The {feature}.{key} value must be greater than zero. "
                    "Enter at least 1 in the parameter form. To stop using the feature, "
                    "turn it off in Features instead of setting its duration or limit to zero."
                )
    if result["turns"]["first"] not in (0, 1):
        raise ArenaError(
            "The first speaker must be the challenger (0) or opponent (1). Open Features → "
            "Turn order → First and choose one of the two participants from the menu, then "
            "review the updated summary."
        )
    if result["research"]["depth"] > 10 or result["on_demand"]["depth"] > 10:
        raise ArenaError(
            "Research depth must be a whole number from 1 to 10. It controls how many sources"
            " a research or fact-check request considers. Open Features → Cited research or "
            "Fact-check requests and correct Depth before saving."
        )
    if not 0 <= result["corrections"]["confidence"] <= 1:
        raise ArenaError(
            "Correction confidence must be a number from 0 to 1; for example, 0.85 means 85% "
            "confidence. Open Features → Factual corrections → Confidence and enter a value "
            "in that range."
        )
    weights = result["judging"]["weights"]
    if set(weights) != set(WEIGHTS) or any(type(v) is not int or v < 0 for v in weights.values()):
        raise ArenaError(
            "Judging requires six nonnegative whole-number weights: reasoning, evidence, "
            "accuracy, engagement, clarity and rules. Open Features → Final judging → Weights"
            " and enter all six in that order, separated by spaces. They must total 100; for "
            "example, 25 20 15 20 10 10."
        )
    if sum(weights.values()) != 100:
        raise ArenaError(
            "Judging weights must sum to 100 so every match uses a complete scoring rubric. "
            "Open Features → Final judging → Weights and enter all six whole-number weights "
            "together; for example, 25 20 15 20 10 10."
        )
    if result["judging"]["rubric"] != "arena-v1":
        raise ArenaError(
            "The supported judging rubric is arena-v1. Restore that rubric in the policy "
            "patch; custom rubric names are not implemented. To adjust scoring, use Features "
            "→ Final judging → Weights and keep all six weights totaling 100."
        )
    if not result["research"]["enabled"]:
        result["corrections"]["enabled"] = False
    if not result["judging"]["enabled"]:
        result["ranked"]["enabled"] = False
    if result["reminders"]["enabled"] and result["inactivity"]["enabled"]:
        if result["reminders"]["before_hours"] >= result["inactivity"]["hours"]:
            raise ArenaError(
                "The reminder lead time must be shorter than the response window, otherwise "
                "the reminder would be due before the turn begins. In Features, reduce "
                "Deadline reminders → Before hours or increase Response deadline → Hours. For"
                " example, use a 2-hour reminder with a 24-hour response window."
            )
    if result["ranked"]["enabled"]:
        required = ranked_settings()
        for feature in ("judging", "coaching", "live_scores", "turns", "inactivity", "limits"):
            if result[feature] != required[feature]:
                raise ArenaError(
                    f"Ranked-v1 requires the shared {feature} configuration so rated matches "
                    "use consistent rules. Choose the ranked preset again to restore those "
                    "values, or turn ranked play off before customizing this feature."
                )
        if result["ranked"]["preset"] != "ranked-v1":
            raise ArenaError(
                "Ranked play supports the shared ranked-v1 preset so rated matches use "
                "consistent rules. Choose the ranked preset in the challenge menu, or turn "
                "ranked play off before customizing its required rules."
            )
    return result


def ranked_settings() -> dict:
    settings = deepcopy(DEFAULTS)
    settings["ranked"]["enabled"] = True
    settings["limits"].update(enabled=True, rounds=10, messages=100, characters=4000)
    return settings


def server_defaults() -> dict[str, Any]:
    return {
        "categories": {"active": None, "completed": None, "cancelled": None},
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
        raise ArenaError(
            "The server policy has an unsupported field or is missing required settings. "
            "Reopen `/admin` → Advanced server policy and use a patch with documented setting"
            " names. For ordinary setup, use Set up routes, Output channels and moderator "
            "roles, or Default match features instead."
        )
    # Older saved policies had a separate forfeited route. Keep every other saved
    # choice; all forfeits now share Completed without rewriting stored records.
    if isinstance(config["categories"], dict):
        config["categories"].pop("forfeited", None)
    if not isinstance(config["categories"], dict) or set(config["categories"]) != {
        "active",
        "completed",
        "cancelled",
    }:
        raise ArenaError(
            "The category routes must contain Active, Completed and Cancelled. Open `/admin` "
            "→ Set up routes, choose a Discord category in each dropdown and click Save "
            "routes. One category can serve all three; Completed also holds forfeited "
            "matches."
        )
    if not isinstance(config["moderator_roles"], list) or len(config["moderator_roles"]) > 25:
        raise ArenaError(
            "You can configure at most 25 moderator roles, supplied as a list of role IDs. "
            "Open `/admin` → Output channels and moderator roles and select the roles that "
            "should manage matches. Server-wide configuration still requires Administrator "
            "permission."
        )
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
            raise ArenaError(
                "Category, channel and role IDs must be valid Discord IDs written as strings "
                "of digits, or null for an unset optional channel. Use the native pickers in "
                "`/admin` for normal setup. In advanced server settings, write each ID as digits. "
                "A category name or channel mention is not an ID."
            )
    if not isinstance(config["channel_name"], str) or "{id}" not in config["channel_name"]:
        raise ArenaError(
            "The channel_name template must include {id} so every match gets its own channel "
            "name. In `/admin` → Advanced server policy, use a template such as match-{id}. "
            "Only lowercase letters, digits and hyphens are allowed around the placeholder."
        )
    if config["channel_name"].replace("{id}", "1").strip("abcdefghijklmnopqrstuvwxyz0123456789-"):
        raise ArenaError(
            "The match channel name contains unsupported characters. In `/admin` → Advanced "
            "server policy, use only lowercase letters, digits, hyphens and the required {id}"
            " placeholder; for example, match-{id}. Remove spaces, punctuation and uppercase "
            "letters."
        )
    prefix = config["match_prefix"]
    if (
        not isinstance(prefix, str)
        or len(prefix) > 12
        or prefix.strip("abcdefghijklmnopqrstuvwxyz0123456789-")
    ):
        raise ArenaError(
            "The match prefix must be empty or contain at most 12 lowercase letters, digits "
            "or hyphens. In `/admin` → Advanced server policy, shorten match_prefix and "
            "remove spaces or other punctuation before saving."
        )
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
            raise ArenaError(
                f"The server setting {key} must be a whole number from 1 to 100000. "
                "Open `/admin` → Advanced server policy and correct that value, using "
                "digits without quotation marks, units or commas."
            )
    models = config["llm_models"]
    if not isinstance(models, dict) or set(models) != {"analyze", "research", "training", "battle"}:
        raise ArenaError(
            "The model policy must define analyze, research, training and battle. Set every "
            "entry to default in `/admin` → Advanced server policy so all AI features use the"
            " operator-selected MiniMax M3.1 Flash model through OpenCode Go."
        )
    if any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in models.values()):
        raise ArenaError(
            "Each model setting must be a nonempty string of at most 100 characters. Use "
            "default for every model role and judging so all features use MiniMax M3.1 Flash "
            "through OpenCode Go; selecting another model will not enable it."
        )
    config["defaults"] = match_settings(config["defaults"])
    if not isinstance(config["presets"], dict) or len(config["presets"]) > 20:
        raise ArenaError(
            "The preset configuration must be an object containing at most 20 named presets. "
            "In `/admin` → Advanced server policy, remove extra presets or correct the object"
            " structure before saving. Each preset uses the documented match-feature "
            "settings."
        )
    for name, preset in config["presets"].items():
        if not name or len(name) > 40:
            raise ArenaError(
                "Each preset needs a name of 1–40 characters. In `/admin` → Advanced server "
                "policy, replace empty names or shorten long ones, then save the presets "
                "again. Members will choose these names in challenge setup."
            )
        config["presets"][name] = match_settings(preset)
    return config
