import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest
from discord import app_commands

from argument_arena.admin_ui import OutputsView, RoutesView, show_admin
from argument_arena.client import ArenaClient
from argument_arena.config import Config
from argument_arena.help_ui import HELP, show_help
from argument_arena.match_ui import (
    Draft,
    DraftView,
    MatchView,
    available_actions,
    filtered_result,
    show_claims,
    show_match,
    show_picker,
    show_staff,
    staff_outcome,
    summary,
)
from argument_arena.member_ui import (
    ProfileView,
    TrainingView,
    profile_preferences,
    show_leaderboard,
    show_profile,
    show_training,
    training_current,
    training_difficulty,
)
from argument_arena.providers import ProviderError
from argument_arena.settings import DEFAULTS, WEIGHTS, Actor, ArenaError
from argument_arena.settings_ui import FeatureView, SettingsTarget, parameters, show_settings
from argument_arena.ui import Panel, parse_json
from tests.helpers import ADMIN, STAFF, A, B, active, drain, message, pending


def interaction(user=10, admin=False, guild=123, channel=999, roles=()):
    request = SimpleNamespace(
        guild_id=guild,
        channel_id=channel,
        channel=SimpleNamespace(id=channel, parent_id=None),
        user=SimpleNamespace(id=user, bot=False, roles=[SimpleNamespace(id=r) for r in roles]),
        permissions=discord.Permissions(administrator=admin),
        response=SimpleNamespace(
            is_done=Mock(return_value=False),
            send_message=AsyncMock(),
            send_modal=AsyncMock(),
            defer=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )

    async def done(*args, **kwargs):
        request.response.is_done.return_value = True

    request.response.defer.side_effect = done
    request.response.send_modal.side_effect = done
    request.response.send_message.side_effect = done
    return request


def packet(request):
    call = request.followup.send.call_args or request.response.send_message.call_args
    assert call.kwargs["ephemeral"] is True
    assert call.kwargs["allowed_mentions"].everyone is False
    return call


def view(request):
    return packet(request).kwargs["view"]


def content(request):
    call = packet(request)
    if "file" in call.kwargs:
        return call.kwargs["file"].fp.read().decode()
    if "embed" in call.kwargs:
        return str(call.kwargs["embed"].to_dict())
    return call.args[0]


async def choose(panel, request, value, index=0):
    selector = [item for item in panel.children if isinstance(item, discord.ui.Select)][index]
    assert value in [option.value for option in selector.options]
    selector._values = [value]
    await selector.callback(request)


async def submit_form(form, request, **values):
    for key, value in values.items():
        form.inputs[key]._value = value
    await form.on_submit(request)


@pytest.fixture
async def client(product, tmp_path):
    async with ArenaClient(Config(123, tmp_path / "token"), product.arena.repo.storage) as result:
        result.arena = product.arena
        result.assistance = product.assistance
        result.training = product.training
        result.profiles = product.profiles
        result.gateway = product.gateway
        yield result


def draft(client):
    return Draft(
        client,
        A.id,
        B.id,
        "https://discord.com/channels/123/888",
        deepcopy(DEFAULTS),
        {"default": deepcopy(DEFAULTS)},
        topic="Keep a public record",
        positions=["For", "Against"],
    )


async def test_registered_surface_is_seven_guild_only_commands_with_one_required_argument(client):
    commands = client.tree.get_commands(guild=client.guild)
    assert {c.name for c in commands} == {
        "challenge",
        "match",
        "train",
        "profile",
        "leaderboard",
        "admin",
        "help",
    }
    assert not any(isinstance(c, app_commands.Group) for c in commands)
    for command in commands:
        schema = command.to_dict(client.tree)
        assert schema["dm_permission"] is False
        assert command.guild_only
        assert [p["name"] for p in schema["options"]] == (
            ["member"] if command.name == "challenge" else []
        )
    assert commands[0].parameters[0].required


@pytest.mark.parametrize("channel", [999, 888])
async def test_challenge_modal_uses_defaults_and_retains_channel_or_thread_origin(
    client, product, channel
):
    await product.arena.setup(ADMIN, {"defaults": {"inactivity": {"hours": 48}}})
    request = interaction(channel=channel)
    member = SimpleNamespace(id=20, bot=False, guild=SimpleNamespace(id=123))
    command = client.tree.get_command("challenge", guild=client.guild)
    await command._do_call(request, {"member": member})
    form = request.response.send_modal.call_args.args[0]
    submitted = interaction(channel=channel)
    await submit_form(
        form,
        submitted,
        topic="A shared public record",
        first="Publish it",
        second="Keep it private",
    )
    panel = view(submitted)
    assert isinstance(panel, DraftView)
    assert panel.draft.settings["inactivity"]["hours"] == 48
    assert panel.draft.origin.endswith(f"/{channel}")
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM matches")
        assert not await unit.rows("SELECT id FROM jobs")
    await panel.send(interaction(channel=channel))
    async with product.arena.repo.unit() as unit:
        rows = await unit.rows("SELECT id FROM matches")
        assert len(rows) == 1
        assert not await unit.rows("SELECT id FROM jobs WHERE kind='create'")
    match = await product.arena.repo.match(rows[0]["id"])
    assert match["origin"].endswith(f"/{channel}")
    assert match["confirmed"] == [] and match["channel"] is None
    assert match["settings"]["inactivity"]["hours"] == 48


async def test_draft_validation_cancel_expiry_and_double_send_leave_no_active_channel(
    client, product
):
    proposal = draft(client)
    panel = DraftView(proposal)
    form_request = interaction()
    await panel.edit(form_request)
    form = form_request.response.send_modal.call_args.args[0]
    invalid = interaction()
    await submit_form(form, invalid, topic="x", first="Yes", second="No")
    assert "3–500" in content(invalid)
    assert proposal.topic == "Keep a public record"
    await panel.cancel(interaction())
    with pytest.raises(ArenaError, match="cancelled"):
        await panel.send(interaction())
    expired = draft(client)
    expired.created -= 901
    with pytest.raises(ArenaError, match="expired"):
        expired.check()
    async with product.arena.repo.unit() as unit:
        assert not await unit.rows("SELECT id FROM matches")
    proposal = draft(client)
    results = await asyncio.gather(
        DraftView(proposal).send(interaction()),
        DraftView(proposal).send(interaction()),
        return_exceptions=True,
    )
    assert sum(isinstance(result, ArenaError) for result in results) == 1
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM matches")) == 1
        assert not await unit.rows("SELECT id FROM jobs WHERE kind='create'")


async def test_draft_features_are_typed_and_dependencies_and_ranked_rules_apply(client):
    proposal = draft(client)
    target = SettingsTarget(client, A.id, draft=proposal)
    request = interaction()
    await show_settings(request, target)
    assert {o.value for o in view(request).children[0].options} == set(DEFAULTS)
    feature = FeatureView(target, proposal.snapshot(), "research", True)
    await feature.toggle(interaction())
    assert not proposal.settings["research"]["enabled"]
    assert not proposal.settings["corrections"]["enabled"]
    feature = FeatureView(target, proposal.snapshot(), "inactivity", True)
    request = interaction()
    await feature.parameter(request, "hours")
    await submit_form(request.response.send_modal.call_args.args[0], interaction(), value="48")
    assert proposal.settings["inactivity"]["hours"] == 48
    ranked = FeatureView(target, proposal.snapshot(), "ranked", True)
    await ranked.toggle(interaction())
    assert proposal.settings["ranked"]["enabled"]
    assert proposal.settings["inactivity"]["hours"] == 24
    assert proposal.settings["limits"]["enabled"]
    # All six weights can be changed atomically without JSON or an invalid intermediate sum.
    await ranked.toggle(interaction())
    judge = FeatureView(target, proposal.snapshot(), "judging", True)
    request = interaction()
    await judge.parameter(request, "weights")
    await submit_form(
        request.response.send_modal.call_args.args[0], interaction(), value="30 15 15 20 10 10"
    )
    assert proposal.settings["judging"]["weights"]["reasoning"] == 30
    assert sum(proposal.settings["judging"]["weights"].values()) == 100
    model_request = interaction()
    await judge.parameter(model_request, "model")
    assert len(view(model_request).children[0].options) == 1
    assert dict(parameters(DEFAULTS["judging"]))[("weights",)] == WEIGHTS


async def test_negotiation_rejects_stale_confirmation_and_requires_both_on_same_revision(
    client, product
):
    match = await pending(product.arena)
    config = await product.arena.config(A.guild)
    a_view = MatchView(client, match, A, config)
    await a_view.selected(interaction(), "accept")
    assert (await product.arena.repo.match(match["id"]))["confirmed"] == [A.id]
    b_view = MatchView(client, match, B, config)
    edit = interaction(20)
    await b_view.selected(edit, "edit")
    await submit_form(
        edit.response.send_modal.call_args.args[0],
        interaction(20),
        topic="A revised topic",
        first="For",
        second="Against",
    )
    current = await product.arena.repo.match(match["id"])
    assert current["revision"] == 2 and current["confirmed"] == []
    with pytest.raises(ArenaError, match="Settings changed"):
        await a_view.selected(interaction(), "accept")
    await MatchView(client, current, A, config).selected(interaction(), "accept")
    assert (await product.arena.repo.match(match["id"]))["state"] == "challenge"
    await MatchView(client, current, B, config).selected(interaction(20), "accept")
    current = await product.arena.repo.match(match["id"])
    assert current["state"] == "starting" and current["channel"] is None
    async with product.arena.repo.unit() as unit:
        assert len(await unit.rows("SELECT id FROM jobs WHERE kind='create'")) == 1


async def test_settings_forms_reject_other_owner_guild_and_stale_revision(client, product):
    match = await pending(product.arena)
    target = SettingsTarget(client, A.id, match_id=match["id"])
    feature = FeatureView(target, match, "inactivity", True)
    request = interaction()
    await feature.parameter(request, "hours")
    form = request.response.send_modal.call_args.args[0]
    for denied in (interaction(30), interaction(guild=456)):
        await submit_form(form, denied, value="72")
        assert "panel" in content(denied)
    await product.arena.settings(B, match["id"], {"inactivity": {"hours": 48}})
    stale = interaction()
    await submit_form(form, stale, value="72")
    assert "Settings changed" in content(stale)
    assert (await product.arena.repo.match(match["id"]))["settings"]["inactivity"]["hours"] == 48


@pytest.mark.parametrize(
    "action,outcome", [("finish", "inconclusive"), ("draw", "draw"), ("cancel", "cancelled")]
)
async def test_mutual_endings_are_distinct_and_require_opponent_agreement(
    client, product, action, outcome
):
    match = await active(product.arena, {"judging": {"enabled": False}})
    config = await product.arena.config(A.guild)
    request = interaction()
    await MatchView(client, match, A, config).selected(request, action)
    await view(request).confirm(interaction())
    current = await product.arena.repo.match(match["id"])
    assert current["state"] == "active"
    assert current["proposal"]["action"] == action
    await MatchView(client, current, B, config).selected(interaction(20), "agree")
    assert (await product.arena.result(match["id"], A.guild))["outcome"] == outcome


async def test_concession_is_immediate_only_after_explicit_confirmation(client, product):
    match = await active(product.arena)
    request = interaction()
    await MatchView(client, match, A, await product.arena.config(A.guild)).selected(
        request, "concede"
    )
    assert (await product.arena.repo.match(match["id"]))["state"] == "active"
    assert "Immediate loss" in content(request)
    await view(request).confirm(interaction())
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "concession" and result["winner"] == B.id
    duplicate = interaction()
    await view(request).confirm(duplicate)
    assert "already been used" in content(duplicate)


async def test_stale_pending_proposal_cannot_be_agreed(client, product):
    match = await active(product.arena)
    await product.arena.action(A, match["id"], "pause")
    current = await product.arena.repo.match(match["id"])
    b_panel = MatchView(client, current, B, await product.arena.config(A.guild))
    await product.arena.action(A, match["id"], "draw")
    with pytest.raises(ArenaError, match="proposal changed"):
        await b_panel.selected(interaction(20), "agree")
    assert (await product.arena.repo.match(match["id"]))["state"] == "active"
    with pytest.raises(ArenaError, match="proposal changed"):
        await product.arena.action(B, match["id"], "pause", expected_proposal=current["proposal"])


async def test_lifecycle_menus_preserve_clock_and_extension_agreement(client, product):
    match = await active(product.arena, {"turns": {"structure": "submit"}})
    config = await product.arena.config(A.guild)
    await message(product.arena, match)
    await MatchView(client, match, A, config).selected(interaction(), "submit")
    match = await product.arena.repo.match(match["id"])
    assert match["next"] == B.id
    await MatchView(client, match, A, config).selected(interaction(), "pause")
    match = await product.arena.repo.match(match["id"])
    await MatchView(client, match, B, config).selected(interaction(20), "agree")
    match = await product.arena.repo.match(match["id"])
    assert match["state"] == "paused" and match["deadline"] is None
    original = match["remaining"]
    request = interaction()
    await MatchView(client, match, A, config).selected(request, "extend")
    await submit_form(request.response.send_modal.call_args.args[0], interaction(), hours="12")
    match = await product.arena.repo.match(match["id"])
    await MatchView(client, match, B, config).selected(interaction(20), "agree")
    match = await product.arena.repo.match(match["id"])
    assert match["remaining"] == original + 12 * 3600
    await MatchView(client, match, A, config).selected(interaction(), "resume")
    match = await product.arena.repo.match(match["id"])
    await MatchView(client, match, B, config).selected(interaction(20), "agree")
    match = await product.arena.repo.match(match["id"])
    assert match["deadline"] == product.clock() + original + 12 * 3600


async def test_flexible_speaker_request_and_audience_vote_use_member_selection(client, product):
    match = await active(
        product.arena, {"turns": {"enabled": False}, "audience": {"enabled": True}}
    )
    config = await product.arena.config(A.guild)
    assert match["next"] is None and match["deadline"] is None
    request = interaction()
    await MatchView(client, match, A, config).selected(request, "request")
    await choose(view(request), interaction(), B.id)
    match = await product.arena.repo.match(match["id"])
    await MatchView(client, match, B, config).selected(interaction(20), "agree")
    match = await product.arena.repo.match(match["id"])
    assert match["next"] == B.id and match["deadline"] == product.clock() + 24 * 3600
    await product.arena.action(A, match["id"], "concede")
    match = await product.arena.repo.match(match["id"])
    spectator = Actor("30", A.guild)
    vote = interaction(30)
    await MatchView(client, match, spectator, config).selected(vote, "vote")
    await choose(view(vote), interaction(30), A.id)
    result = await product.arena.result(match["id"], A.guild)
    assert result["audience_votes"][A.id] == 1 and result["winner"] == B.id


async def test_draft_preset_and_stale_review_do_not_send_old_configuration(client, product):
    proposal = draft(client)
    proposal.presets["slow"] = deepcopy(DEFAULTS)
    proposal.presets["slow"]["inactivity"]["hours"] = 48
    original = DraftView(proposal)
    request = interaction()
    await original.preset(request, "slow")
    assert proposal.settings["inactivity"]["hours"] == 48
    with pytest.raises(ArenaError, match="draft changed"):
        await original.send(interaction())
    await view(request).send(interaction())
    async with product.arena.repo.unit() as unit:
        rows = await unit.rows("SELECT data FROM matches")
    assert len(rows) == 1 and json.loads(rows[0]["data"])["settings"]["inactivity"]["hours"] == 48


async def test_moderation_outcome_forms_recheck_authority_and_record_decisions(client, product):
    match = await active(product.arena)
    request = interaction(50, roles=(7,))
    await show_staff(request, client, match)
    outcomes = interaction(50, roles=(7,))
    await staff_outcome(outcomes, view(request), match)
    reason = interaction(50, roles=(7,))
    await choose(view(outcomes), reason, "inconclusive")
    form = reason.response.send_modal.call_args.args[0]
    denied = interaction(50)
    await submit_form(form, denied, reason="The evidence is not sufficient for a decision.")
    assert "moderator" in content(denied)
    assert (await product.arena.repo.match(match["id"]))["state"] == "active"
    await submit_form(
        form, interaction(50, roles=(7,)), reason="The evidence is not sufficient for a decision."
    )
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "inconclusive" and result["staff_review"]["actor"] == STAFF.id


async def test_every_feature_can_be_inspected_and_parameters_have_valid_ui_components(client):
    proposal = draft(client)
    target = SettingsTarget(client, A.id, draft=proposal)
    for feature, values in proposal.settings.items():
        controls = FeatureView(target, proposal.snapshot(), feature, True)
        assert len(controls.to_components()) <= 5
        for path, _value in parameters(values):
            request = interaction()
            await controls.parameter(request, ".".join(path))
            if request.response.send_modal.called:
                form = request.response.send_modal.call_args.args[0]
                assert len(form.children) <= 5
                assert all(len(child.to_component_dict()["label"]) <= 45 for child in form.children)
            else:
                options = view(request).children[0].options
                assert 1 <= len(options) <= 25
        request = interaction()
        await controls.details(request)
        assert feature in content(request)


async def test_state_and_permissions_control_actions_and_server_admin_enforces_at_execution(
    client, product
):
    match = await active(product.arena, {"turns": {"structure": "submit"}})
    config = await product.arena.config(A.guild)
    assert "submit" in available_actions(match, A, config, product.clock())
    assert "submit" not in available_actions(match, B, config, product.clock())
    spectator = Actor("30", "123")
    assert not set(available_actions(match, spectator, config, product.clock())) & {
        "pause",
        "cancel",
        "concede",
        "staff",
    }
    assert "staff" in available_actions(match, STAFF, config, product.clock())
    with pytest.raises(ArenaError, match="moderator"):
        await show_admin(interaction(30), client)
    admin_request = interaction(40, True)
    await show_admin(admin_request, client)
    denied = interaction(40)
    with pytest.raises(ArenaError, match="moderator"):
        await choose(view(admin_request), denied, "routes")
    admin_request = interaction(40, True)
    await show_admin(admin_request, client)
    advanced = interaction(40, True)
    await choose(view(admin_request), advanced, "advanced")
    revoked = interaction(40)
    await submit_form(
        advanced.response.send_modal.call_args.args[0], revoked, patch='{"max_concurrent": 9}'
    )
    assert "Administrator" in content(revoked)
    assert (await product.arena.config(A.guild))["max_concurrent"] == 3
    moderator = interaction(50, roles=(7,))
    await show_admin(moderator, client)
    assert [o.value for o in view(moderator).children[0].options] == ["moderate"]


async def test_routes_and_outputs_use_native_pickers_and_preserve_unedited_fields(client, product):
    panel = RoutesView(client, "40")
    assert len(panel.to_components()) == 4
    for index, picker in enumerate(panel.children[:3]):
        picker._values = [SimpleNamespace(id=index + 11, guild=SimpleNamespace(id=123))]
        await picker.callback(interaction(40, True))
    await panel.save(interaction(40, True))
    config = await product.arena.config(A.guild)
    assert config["categories"]["active"] == "11"
    assert config["categories"] == {"active": "11", "completed": "12", "cancelled": "13"}
    outputs = OutputsView(client, "40")
    outputs.children[0]._values = [SimpleNamespace(id=55, guild=SimpleNamespace(id=123))]
    await outputs.children[0].callback(interaction(40, True))
    await outputs.save(interaction(40, True))
    config = await product.arena.config(A.guild)
    assert config["announcement"] == "55" and config["moderator_roles"] == ["7"]


async def test_match_picker_paginates_and_current_match_opens_inside_discussion_thread(
    client, product
):
    match = await active(product.arena)
    async with product.arena.repo.unit() as unit:
        for i in range(25):
            copy = deepcopy(match)
            copy.update(id=f"other-{i}", topic=f"Debate {i}", channel=None)
            await unit.save_match(copy)
    request = interaction()
    await show_picker(request, client)
    assert len(view(request).children[0].options) == 20
    second = interaction()
    await view(request).next_page(second)
    assert len(view(second).children[0].options) == 6
    thread = interaction(channel=888)
    thread.channel.parent_id = int(match["channel"])
    await client.tree.get_command("match", guild=client.guild)._do_call(thread, {})
    assert isinstance(view(thread), MatchView)
    assert view(thread).match["id"] == match["id"]


async def test_private_feedback_remains_filtered_in_results(client, product):
    match = await active(product.arena, {"feedback": {"delivery": "private"}})
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    await drain(product)
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    await drain(product)
    spectator = json.dumps(await filtered_result(client, match, "30"))
    owner = json.dumps(await filtered_result(client, match, A.id))
    assert '"strengths"' not in spectator and '"scores"' in spectator
    assert '"strengths"' in owner


async def test_claim_navigation_rechecks_permissions_and_supports_fact_checks(client, product):
    match = await active(product.arena)
    await message(product.arena, match)
    await drain(product)
    request = interaction()
    await show_claims(request, client, match)
    claim_id = view(request).children[0].options[0].value
    selected = interaction()
    await choose(view(request), selected, claim_id)
    assert "Fact-check this claim" in [b.label for b in view(selected).children]
    spectator = interaction(30)
    await show_claims(spectator, client, match)
    details = interaction(30)
    await choose(view(spectator), details, claim_id)
    assert not view(details).children


async def test_training_entire_form_flow_and_progress_are_owner_scoped(client, product):
    request = interaction()
    await show_training(request, client)
    start = interaction()
    await choose(view(request), start, "start")
    mode = interaction()
    await choose(view(start), mode, "repair")
    difficulty = interaction()
    await choose(view(mode), difficulty, "2")
    submit = interaction()
    await submit_form(
        difficulty.response.send_modal.call_args.args[0], submit, topic="Public transport"
    )
    assert isinstance(view(submit), TrainingView)
    assert "repair" in content(submit)
    answer_request = interaction()
    await choose(view(submit), answer_request, "answer")
    submitted = interaction()
    await submit_form(
        answer_request.response.send_modal.call_args.args[0],
        submitted,
        answer="The premise does not establish the stated conclusion, so narrow the claim.",
    )
    assert "grading pending" in content(submitted)
    assert (await training_current(client, A))["state"] == "grading"
    assert await training_current(client, B) is None
    await drain(product)
    assert (await client.training.progress(A))["attempts"] == 1


async def test_optional_fallacy_selection_preserves_other_practice_modes(client, product):
    request = interaction()
    await training_difficulty(request, client, "repair")
    library = interaction()
    await view(request).children[1].callback(library)
    entry = view(library).children[0].options[0].value
    difficulty = interaction()
    await choose(view(library), difficulty, entry)
    topic = interaction()
    await choose(view(difficulty), topic, "3")
    await submit_form(
        topic.response.send_modal.call_args.args[0], interaction(), topic="Technology"
    )
    async with product.arena.repo.unit() as unit:
        session = await product.training._current(unit, A)
    assert session["mode"] == "repair" and session["exercise"]["fallacy"] == entry


async def test_profiles_preserve_consent_privacy_and_public_history_navigation(client, product):
    request = interaction()
    await show_profile(request, client)
    assert isinstance(view(request), ProfileView)
    other = interaction(20)
    await show_profile(other, client, A.id)
    assert view(other).choices == {"view", "history"}
    private = interaction(20)
    await choose(view(other), private, "view")
    assert "private" in content(private)
    preferences = interaction()
    await profile_preferences(preferences, client)
    assert not (await client.profiles.settings(A))["analysis"]
    changed = interaction()
    await choose(view(preferences), changed, "analysis")
    assert (await client.profiles.settings(A))["analysis"]
    history = interaction(20)
    await choose(view(other), history, "history")
    assert "statistics" in content(history)


async def test_help_is_ephemeral_in_channels_and_threads_with_valid_guidance(client):
    for channel in (999, 888):
        request = interaction(30, channel=channel)
        await client.tree.get_command("help", guild=client.guild)._do_call(request, {})
        assert "/challenge @member" in content(request)
        assert "admin" not in [o.value for o in view(request).children[0].options]
    for key, (title, description) in HELP.items():
        request = interaction(40, True)
        await show_help(request, client, key)
        assert packet(request).kwargs["embed"].title == title
        assert len(description) <= 4096
        assert len(view(request).to_components()) <= 5
    assert "24-hour" in HELP["automatic"][1]
    assert "immediately lose" in HELP["end"][1]
    assert "both agree" in HELP["end"][1]


async def test_summary_and_panels_fit_discord_limits_and_errors_do_not_expose_details(
    client, product
):
    match = await active(product.arena)
    embed = summary(match)
    assert len(embed) <= 6000
    assert all(len(field.value) <= 1024 for field in embed.fields)
    request = interaction()
    await show_match(request, client, match["id"])
    assert len(view(request).to_components()) <= 5
    panel = Panel(client, A.id)
    denied = interaction(30)
    assert not await panel.interaction_check(denied)
    failed = interaction()
    await panel.on_error(failed, RuntimeError("private payload"), None)
    assert "private payload" not in content(failed)
    leaderboard_request = interaction()
    await show_leaderboard(leaderboard_request, client)
    assert "Filter standings" in [b.label for b in view(leaderboard_request).children]


async def test_feedback_without_judging_does_not_change_outcome(product):
    match = await active(product.arena, {"judging": {"enabled": False}})
    await message(product.arena, match)
    await message(product.arena, match, B, "101")
    await product.arena.action(A, match["id"], "finish")
    await product.arena.action(B, match["id"], "finish")
    await drain(product)
    result = await product.arena.result(match["id"], A.guild)
    assert result["outcome"] == "inconclusive" and result["report"] is None
    assert result["feedback"][A.id]["needs"] and not result["rated"]


def test_invalid_advanced_settings_json_has_actionable_error():
    with pytest.raises(ArenaError, match="valid JSON"):
        parse_json("{not-json}")
    with pytest.raises(ArenaError):
        parse_json("[]")


async def test_missing_routes_explain_setup_without_creating_a_match(client, product):
    await product.arena.setup(ADMIN, {"categories": {"active": None}})
    request = interaction()
    command = client.tree.get_command("challenge", guild=client.guild)
    await command._do_call(request, {"member": SimpleNamespace(id=20, bot=False)})
    message = content(request)
    assert "folder" in message and "Set up routes" in message and "Save routes" in message
    assert "same category" in message and "forfeited" in message
    assert request.response.send_modal.call_count == 0
    async with product.arena.repo.unit() as unit:
        assert await unit.rows("SELECT id FROM matches") == []
        assert await unit.rows("SELECT id FROM jobs") == []


async def test_incomplete_category_setup_identifies_missing_choices_and_keeps_saved_routes(
    client, product
):
    original = await product.arena.config(A.guild)
    request = interaction(40, True)
    await show_admin(request, client)
    setup = interaction(40, True)
    await choose(view(request), setup, "routes")
    assert "Completed" in content(setup) and "forfeits" in content(setup)
    panel = view(setup)
    panel.children[0]._values = [SimpleNamespace(id=99, guild=SimpleNamespace(id=123))]
    await panel.children[0].callback(interaction(40, True))
    with pytest.raises(ArenaError) as rejected:
        await panel.save(interaction(40, True))
    assert "Completed, Cancelled" in str(rejected.value)
    assert "have not changed" in str(rejected.value)
    assert await product.arena.config(A.guild) == original


async def test_failed_grading_explains_recovery_and_reuses_only_its_owners_saved_answer(
    client, product
):
    await product.training.start(A)
    answer = "My private answer explains the unsupported conclusion in this argument."
    await product.training.answer(A, answer)
    product.llm.responses["grade"] = ProviderError("credential_rejected", retry=False)
    await product.worker.once()
    request = interaction()
    await show_training(request, client)
    message = content(request)
    assert "rejected the bot's API key" in message and "Retry failed grading" in message
    assert answer not in message and await training_current(client, B) is None
    async with product.arena.repo.unit() as unit:
        session = await product.training._current(unit, A)
        assert session["pending_answer"] == answer and session["state"] == "grading"
    product.llm.responses.pop("grade")
    await product.training.retry(A)
    await product.worker.once()
    assert (await product.training.progress(A))["attempts"] == 1


async def test_match_status_explains_failed_and_scheduled_work(client, product):
    match = await active(product.arena)
    async with product.arena.repo.unit() as unit:
        for key in ("failed-check", "waiting-check"):
            await unit.job(key, "research", match["id"], {}, product.clock())
    await product.arena.repo.job_failed(
        "failed-check", product.clock(), "active_category_unavailable", retry=False
    )
    await product.arena.repo.job_failed("waiting-check", product.clock(), "rate_limited")
    request = interaction()
    await MatchView(client, match, A, await product.arena.config(A.guild)).selected(
        request, "status"
    )
    message = content(request)
    assert "Set up routes" in message and "Retry failed work" in message
    assert "scheduled another attempt" in message and "no need to resubmit" in message
