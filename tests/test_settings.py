from copy import deepcopy

import pytest

from argument_arena.settings import (
    DEFAULTS,
    ArenaError,
    match_settings,
    ranked_settings,
    server_defaults,
    validate_server,
)


def test_complete_materialized_settings_and_independent_research():
    settings = match_settings({"research": {"enabled": False}, "claims": {"enabled": False}})
    assert len(settings) == 20 and all(type(v["enabled"]) is bool for v in settings.values())
    assert not settings["corrections"]["enabled"]
    assert settings["on_demand"]["enabled"]
    assert settings["inactivity"]["hours"] == 24
    assert match_settings()["research"]["enabled"]
    settings["judging"]["weights"]["reasoning"] = 0
    assert DEFAULTS["judging"]["weights"]["reasoning"] == 25


@pytest.mark.parametrize(
    "patch",
    [
        {"invented": {}},
        {"research": {"unknown": 1}},
        {"research": True},
        {"claims": {"enabled": "false"}},
        {"turns": {"first": 2}},
        {"research": {"depth": 11}},
        {"coaching": {"delivery": "somewhere"}},
        {"judging": {"weights": {"reasoning": 100}}},
        {"limits": {"rounds": 0}},
        {"corrections": {"confidence": 1.1}},
        {"inactivity": {"hours": 1}},
        {"judging": {"rubric": "invented"}},
        {"reactions": {"allowed": [123]}},
        {"ranked": {"enabled": True}},
    ],
)
def test_invalid_settings_are_rejected(patch):
    with pytest.raises(ArenaError):
        match_settings(patch)


@pytest.mark.parametrize("feature", list(DEFAULTS))
def test_every_optional_feature_can_be_controlled(feature):
    settings = (
        match_settings({feature: {"enabled": not DEFAULTS[feature]["enabled"]}})
        if feature != "ranked"
        else match_settings(ranked_settings())
    )
    assert feature in settings


def test_ranked_preset_and_dependency_normalization():
    ranked = match_settings(ranked_settings())
    assert ranked["ranked"]["enabled"]
    assert not match_settings({"judging": {"enabled": False}}, ranked)["ranked"]["enabled"]
    with pytest.raises(ArenaError, match="shared"):
        match_settings({"coaching": {"enabled": True}}, ranked)


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_concurrent", 0),
        ("rating_k", "32"),
        ("channel_name", "missing-id"),
        ("moderator_roles", [123]),
        ("llm_models", {"analyze": ""}),
        ("bad_key", True),
    ],
)
def test_server_validation(key, value):
    config = deepcopy(server_defaults())
    config[key] = value
    with pytest.raises(ArenaError):
        validate_server(config)
