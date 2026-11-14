"""Discord-independent debate rules, transitions, clocks, results and ratings."""

import math
import time

from .store import new_id


class DomainError(ValueError):
    """An invalid or unauthorized user action, safe to explain to the user."""


DEFAULT_SETTINGS = {
    "claim_tracking": True, "background_research": True, "factual_corrections": True,
    "on_demand_checks": True, "fallacy_detection": False, "coaching": False,
    "civility": True, "live_scores": False, "judging": True, "feedback": True,
    "turn_enforcement": True, "inactivity_forfeits": True, "deadline_reminders": True,
    "limits": False, "spectator_reactions": True, "discussion_threads": True,
    "audience_voting": False, "ranked": False, "profile_insights": False,
    "automatic_archival": True, "response_hours": 24, "reminder_minutes": 60,
    "round_limit": 10, "message_limit": 200, "length_limit": 4000,
    "research_budget": 20, "llm_budget": 100, "llm_budget_usd": 0,
    "research_depth": "basic", "source_preferences": [], "correction_confidence": 0.85,
    "notification_interval": 60, "claim_detail": "concise", "coaching_delivery": "private",
    "feedback_delivery": "private", "feedback_detail": "detailed", "civility_strictness": "normal",
    "fallacy_families": [], "model": "", "judge_model": "", "moderation_model": "",
    "research_model": "", "training_model": "", "profile_model": "", "tie_threshold": 3,
    "weights": {"reasoning": 25, "evidence": 20, "accuracy": 15, "engagement": 20,
                "clarity": 10, "rules": 10},
    "first_speaker": "challenger", "archive_threads": False, "forfeit_rated": False,
    "audience_vote_hours": 24, "audience_eligibility": "members",
    "on_demand_limit": 5,
}
PRESETS = {"casual": {}, "ranked": {"ranked": True, "judging": True, "turn_enforcement": True},
           "no-research": {"background_research": False, "factual_corrections": False},
           "coaching": {"coaching": True, "fallacy_detection": True, "ranked": False}}
DEFAULT_SERVER = {"moderator_role_ids": [], "max_concurrent": 10, "challenge_cooldown": 60,
                  "channel_template": "match-{id}", "defaults": {}, "presets": {},
                  "active_category_id": None, "completed_category_id": None,
                  "forfeited_category_id": None, "cancelled_category_id": None,
                  "announcement_channel_id": None, "results_channel_id": None}


def validate_settings(patch, base=None):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULT_SETTINGS):
        raise DomainError("Unknown match settings. Use /match options for the supported keys.")
    settings = {**DEFAULT_SETTINGS, **(base or {}), **patch}
    for key, default in DEFAULT_SETTINGS.items():
        value = settings[key]
        if isinstance(default, bool) and not isinstance(value, bool):
            raise DomainError(f"{key} must be true or false.")
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise DomainError(f"{key} must be a finite nonnegative number.")
        if isinstance(default, str) and (not isinstance(value, str) or len(value) > 200):
            raise DomainError(f"{key} must be a string of at most 200 characters.")
        if isinstance(default, list) and (not isinstance(value, list) or len(value) > 30 or any(not isinstance(x, str) for x in value)):
            raise DomainError(f"{key} must be a list of up to 30 strings.")
    if not 0.01 <= settings["response_hours"] <= 720:
        raise DomainError("response_hours must be between 0.01 and 720.")
    if not 0 <= settings["correction_confidence"] <= 1:
        raise DomainError("correction_confidence must be between zero and one.")
    for key in ("round_limit", "message_limit", "length_limit", "research_budget", "llm_budget", "on_demand_limit"):
        if type(settings[key]) is not int or settings[key] > 100000:
            raise DomainError(f"{key} must be an integer no greater than 100000.")
    for key in ("round_limit", "message_limit", "length_limit"):
        if settings[key] < 1:
            raise DomainError(f"{key} must be positive.")
    for key, choices in {
        "first_speaker": ("challenger", "opponent"), "research_depth": ("basic", "advanced"),
        "coaching_delivery": ("public", "private"), "feedback_delivery": ("public", "private"),
        "civility_strictness": ("gentle", "normal", "strict"),
        "audience_eligibility": ("members", "nonparticipants"),
    }.items():
        if settings[key] not in choices:
            raise DomainError(f"{key} must be one of: {', '.join(choices)}.")
    weights = settings["weights"]
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_SETTINGS["weights"]):
        raise DomainError("weights must specify reasoning, evidence, accuracy, engagement, clarity, rules.")
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100 for v in weights.values()) or not 0 < sum(weights.values()) <= 600:
        raise DomainError("Judging weights must be between 0 and 100 and sum to a positive value.")
    if not settings["background_research"]:
        settings["factual_corrections"] = False
    if not settings["judging"]:
        settings["ranked"] = False
    if settings["ranked"]:
        if weights != DEFAULT_SETTINGS["weights"] or settings["tie_threshold"] != 3 or not settings["turn_enforcement"]:
            raise DomainError("Ranked play requires the shared default rubric, tie threshold and turn enforcement.")
    return settings


class Arena:
    def __init__(self, store):
        self.store = store

    def server(self, guild_id):
        return {**DEFAULT_SERVER, **self.store.get("servers", guild_id, {}), "guild_id": guild_id}

    def configure(self, guild_id, actor_id, **config):
        if set(config) - set(DEFAULT_SERVER):
            raise DomainError("Unknown server configuration key.")
        server = {**self.server(guild_id), **config}
        if not isinstance(server["defaults"], dict) or not isinstance(server["presets"], dict):
            raise DomainError("defaults and presets must be JSON objects.")
        if not isinstance(server["moderator_role_ids"], list):
            raise DomainError("moderator_role_ids must be a list of role IDs.")
        if not isinstance(server["channel_template"], str):
            raise DomainError("channel_template must be a string.")
        validate_settings(server["defaults"])
        for patch in server["presets"].values():
            validate_settings(patch)
        for key in ("max_concurrent", "challenge_cooldown"):
            if type(server[key]) is not int or server[key] < 1:
                raise DomainError(f"{key} must be a positive integer.")
        if any(type(v) is not int or v < 1 for v in server["moderator_role_ids"]):
            raise DomainError("moderator_role_ids must contain role IDs.")
        try:
            name = server["channel_template"].format(id="example", topic="topic")
            if not 1 <= len(name) <= 100:
                raise ValueError()
        except (ValueError, KeyError, AttributeError, IndexError):
            raise DomainError("channel_template must be a valid name using {id} and optionally {topic}.") from None
        for key in DEFAULT_SERVER:
            if key.endswith("_id") and server[key] is not None and (type(server[key]) is not int or server[key] < 1):
                raise DomainError(f"{key} must be a channel ID or null.")
        with self.store.atomic():
            self.store.put("servers", guild_id, server)
            self.store.event(None, "server_configured", actor_id, {"guild_id": guild_id, "patch": config})
        return server

    def get_match(self, match_id):
        match = self.store.get("matches", match_id)
        if match is None:
            raise DomainError("Match not found.")
        return match

    def _save(self, match, kind, actor_id=0, data=None):
        self.store.put("matches", match["id"], match)
        self.store.event(match["id"], kind, actor_id, data)
        return match

    @staticmethod
    def _participant(match, actor_id):
        if actor_id not in match["participants"]:
            raise DomainError("Only a participant may perform this action.")

    def challenge(self, guild_id, challenger_id, opponent_id, topic, positions=None, origin_url=None, now=None, preset="casual"):
        now = time.time() if now is None else now
        if challenger_id == opponent_id:
            raise DomainError("Choose another member as your opponent.")
        if not topic.strip() or len(topic) > 1000:
            raise DomainError("Topic must contain between 1 and 1000 characters.")
        with self.store.atomic():
            server = self.server(guild_id)
            matches = self.store.list("matches", guild_id=guild_id)
            if sum(m["status"] not in ("ended", "declined") for m in matches) >= server["max_concurrent"]:
                raise DomainError("The server's concurrent match limit has been reached.")
            if any(m["participants"][0] == challenger_id and now - m["created_at"] < server["challenge_cooldown"] for m in matches):
                raise DomainError("Please wait before issuing another challenge.")
            presets = {**PRESETS, **server["presets"]}
            if preset not in presets:
                raise DomainError("Unknown match preset.")
            settings = validate_settings(presets[preset], server["defaults"])
            key = new_id("M")
            match = {"id": key, "guild_id": guild_id, "participants": [challenger_id, opponent_id],
                     "topic": topic.strip(), "positions": positions or {str(challenger_id): "For", str(opponent_id): "Against"},
                     "origin_url": origin_url, "preset": preset, "settings": settings, "confirmations": [challenger_id],
                     "status": "pending", "channel_id": None, "created_at": now,
                     "next_speaker_id": None, "deadline": None, "turn_index": 0, "result": None}
            return self._save(match, "challenged", challenger_id)

    def propose_settings(self, match_id, actor_id, patch):
        with self.store.atomic():
            match = self.get_match(match_id)
            self._participant(match, actor_id)
            if match["status"] not in ("pending", "ready", "active", "paused"):
                raise DomainError("Settings cannot change at this match stage.")
            proposed = validate_settings(patch, match["settings"])
            if match["status"] in ("pending", "ready"):
                match.update(settings=proposed, confirmations=[actor_id], status="pending")
            else:
                match["settings_proposal"] = {"settings": proposed, "confirmations": [actor_id]}
            return self._save(match, "settings_proposed", actor_id, patch)

    def accept(self, match_id, actor_id):
        with self.store.atomic():
            match = self.get_match(match_id)
            self._participant(match, actor_id)
            proposal = match.get("settings_proposal")
            if proposal:
                if match["status"] not in ("active", "paused"):
                    raise DomainError("This settings proposal is no longer open.")
                proposal["confirmations"] = sorted(set(proposal["confirmations"] + [actor_id]))
                if set(proposal["confirmations"]) == set(match["participants"]):
                    match["settings"] = proposal["settings"]
                    del match["settings_proposal"]
            else:
                if match["status"] not in ("pending", "ready"):
                    raise DomainError("There is no pending agreement to accept.")
                match["confirmations"] = sorted(set(match["confirmations"] + [actor_id]))
                if set(match["confirmations"]) == set(match["participants"]):
                    match["status"] = "ready"
            return self._save(match, "accepted", actor_id)

    def decline(self, match_id, actor_id):
        with self.store.atomic():
            match = self.get_match(match_id)
            self._participant(match, actor_id)
            if match.get("settings_proposal"):
                del match["settings_proposal"]
            elif match["status"] in ("pending", "ready"):
                match["status"] = "declined"
            else:
                raise DomainError("Only pending challenges or changes may be declined.")
            return self._save(match, "declined", actor_id)

    def activate(self, match_id, channel_id, now=None):
        now = time.time() if now is None else now
        with self.store.atomic():
            match = self.get_match(match_id)
            if match["status"] == "active" and match["channel_id"] == channel_id:
                return match
            if match["status"] != "ready":
                raise DomainError("Both participants must accept before starting.")
            first = 0 if match["settings"]["first_speaker"] == "challenger" else 1
            match.update(status="active", channel_id=channel_id, started_at=now,
                         next_speaker_id=match["participants"][first],
                         deadline=now + match["settings"]["response_hours"] * 3600)
            self.store.put("system", "heartbeat", {"time": now})
            return self._save(match, "started")

    def record_message(self, match_id, author_id, message_id, content, url, now=None):
        now = time.time() if now is None else now
        with self.store.atomic():
            match = self.get_match(match_id)
            self._participant(match, author_id)
            existing = self.store.get("messages", str(message_id))
            if existing:
                if existing["match_id"] != match_id or existing["author_id"] != author_id:
                    raise DomainError("This message already belongs to a different transcript.")
                return existing
            if match["status"] != "active":
                raise DomainError("This match is not active.")
            match = self._check_deadline(match, now)
            if match["settings"]["turn_enforcement"] and author_id != match["next_speaker_id"]:
                raise DomainError("It is the other participant's turn.")
            if not content.strip():
                raise DomainError("Submit text so the official transcript can be judged.")
            if match["settings"]["limits"] and len(content) > match["settings"]["length_limit"]:
                raise DomainError("This message exceeds the agreed length limit.")
            key = str(message_id)
            message = {"id": key, "match_id": match_id, "guild_id": match["guild_id"],
                       "author_id": author_id, "content": content, "url": url,
                       "created_at": now, "turn_index": match["turn_index"], "deleted": False}
            self.store.put("messages", key, message)
            if match["settings"]["limits"] and len(self.store.list("messages", match_id=match_id)) >= match["settings"]["message_limit"]:
                self._finish(match, now)
                self._save(match, "message_limit")
            return message

    def submit(self, match_id, actor_id, now=None):
        now = time.time() if now is None else now
        with self.store.atomic():
            match = self.get_match(match_id)
            self._participant(match, actor_id)
            if match["status"] != "active" or actor_id != match["next_speaker_id"]:
                raise DomainError("Only the required speaker can submit an active turn.")
            match = self._check_deadline(match, now)
            if not any(not m.get("deleted") and m["author_id"] == actor_id and m["turn_index"] == match["turn_index"] for m in self.store.list("messages", match_id=match_id)):
                raise DomainError("Post your argument before submitting the turn.")
            match["turn_index"] += 1
            match["next_speaker_id"] = next(p for p in match["participants"] if p != actor_id)
            match["deadline"] = now + match["settings"]["response_hours"] * 3600
            match.pop("reminded", None)
            if match["settings"]["limits"] and match["turn_index"] >= 2 * match["settings"]["round_limit"]:
                self._finish(match, now)
            return self._save(match, "turn_submitted", actor_id)

    def _check_deadline(self, match, now):
        checkpoint = self.store.get("system", "heartbeat")
        if checkpoint and now - checkpoint["time"] > 90:
            self.recover(now)
            match = self.get_match(match["id"])
        if (match["settings"]["inactivity_forfeits"] and match.get("deadline") is not None
                and now >= match["deadline"]):
            raise DomainError("The response deadline has passed. This match is awaiting its forfeit result.")
        return match

    def _finish(self, match, now):
        match.pop("settings_proposal", None)
        match.pop("action_proposal", None)
        if match["settings"]["judging"]:
            match.update(status="judging", deadline=None)
        else:
            match.update(status="ended", deadline=None, ended_at=now,
                         result={"outcome": "unjudged", "winner_id": None, "report": None})

    def request_action(self, match_id, actor_id, action, now=None, staff=False, **params):
        now = time.time() if now is None else now
        with self.store.atomic():
            match = self.get_match(match_id)
            if not staff:
                self._participant(match, actor_id)
            if action == "concede" and match["status"] in ("active", "paused"):
                self._participant(match, actor_id)
                return self.end(match_id, "concession", next(p for p in match["participants"] if p != actor_id), actor_id)
            allowed = {"pause": ("active",), "resume": ("paused",), "extend": ("active", "paused"),
                       "cancel": ("pending", "ready", "active", "paused", "judging"),
                       "draw": ("active", "paused"), "finish": ("active", "paused"),
                       "request_response": ("active",)}
            if action not in allowed or match["status"] not in allowed[action]:
                raise DomainError("That action is unavailable at this match stage.")
            if action == "extend" and (type(params.get("hours")) not in (int, float) or not 0 < params["hours"] <= 720):
                raise DomainError("Specify an extension in hours, greater than zero and at most 720.")
            if not staff:
                proposal = {"action": action, "params": params}
                existing = match.get("action_proposal", {})
                confirmations = existing.get("confirmations", []) if all(existing.get(k) == v for k, v in proposal.items()) else []
                proposal["confirmations"] = sorted(set(confirmations + [actor_id]))
                match["action_proposal"] = proposal
                if set(proposal["confirmations"]) != set(match["participants"]):
                    return self._save(match, "action_proposed", actor_id, proposal)
            match.pop("action_proposal", None)
            if action == "pause":
                match.update(status="paused", remaining_seconds=max(0, (match["deadline"] or now) - now), deadline=None)
            elif action == "resume":
                match.update(status="active", deadline=now + max(60, match.get("remaining_seconds", 0)))
            elif action == "extend":
                if match["status"] == "paused":
                    match["remaining_seconds"] = match.get("remaining_seconds", 0) + params["hours"] * 3600
                else:
                    match["deadline"] = max(now, match["deadline"] or now) + params["hours"] * 3600
                match.pop("reminded", None)
            elif action in ("cancel", "draw"):
                return self.end(match_id, "cancelled" if action == "cancel" else "draw", actor_id=actor_id)
            elif action == "finish":
                self._finish(match, now)
            elif action == "request_response":
                target = params.get("user_id")
                if target not in match["participants"]:
                    raise DomainError("Choose a participant as the required speaker.")
                match.update(next_speaker_id=target, deadline=now + match["settings"]["response_hours"] * 3600)
            return self._save(match, action, actor_id, params)

    def end(self, match_id, outcome, winner_id=None, actor_id=0, report=None):
        with self.store.atomic():
            match = self.get_match(match_id)
            if match["status"] == "ended":
                return match
            if winner_id is not None and winner_id not in match["participants"]:
                raise DomainError("The winner must be a participant.")
            if outcome not in ("judged", "draw", "inconclusive", "concession", "forfeit", "cancelled", "unjudged"):
                raise DomainError("Unknown result outcome.")
            match.update(status="ended", deadline=None, ended_at=time.time(),
                         result={"outcome": outcome, "winner_id": winner_id, "report": report})
            match.pop("settings_proposal", None)
            match.pop("action_proposal", None)
            self._save(match, "ended", actor_id, match["result"])
            self._rebuild_ratings(match["guild_id"])
            return self.get_match(match_id)

    def correct_result(self, match_id, actor_id, winner_id, reason):
        if not reason.strip():
            raise DomainError("A correction requires a reason.")
        with self.store.atomic():
            match = self.get_match(match_id)
            if match["status"] != "ended" or (winner_id is not None and winner_id not in match["participants"]):
                raise DomainError("Choose a finished match and a valid winner (or draw).")
            match.setdefault("result_history", []).append(match["result"])
            match["result"] = {"outcome": "judged" if winner_id else "draw", "winner_id": winner_id,
                               "report": {"staff_review": reason, "reviewer_id": actor_id}}
            match["result_published"] = False
            self._save(match, "result_corrected", actor_id, {"reason": reason})
            self._rebuild_ratings(match["guild_id"])
            return self.get_match(match_id)

    def _rebuild_ratings(self, guild_id):
        ratings = {}
        matches = sorted(self.store.list("matches", guild_id=guild_id), key=lambda m: (m.get("ended_at", 0), m["id"]))
        for match in matches:
            result = match.get("result")
            if not result or not match["settings"]["ranked"]:
                continue
            result["rating_changes"] = {}
            eligible = result["outcome"] in ("judged", "draw", "concession") or (result["outcome"] == "forfeit" and match["settings"]["forfeit_rated"])
            if eligible:
                a, b = match["participants"]
                ra, rb = ratings.get(a, 1200.0), ratings.get(b, 1200.0)
                score = 0.5 if result["winner_id"] is None else float(result["winner_id"] == a)
                change = 32 * (score - 1 / (1 + 10 ** ((rb - ra) / 400)))
                ratings[a], ratings[b] = ra + change, rb - change
                result["rating_changes"] = {str(a): change, str(b): -change}
            self.store.put("matches", match["id"], match)
        for old in self.store.list("ratings", guild_id=guild_id):
            self.store.delete("ratings", old["id"])
        for user_id, rating in ratings.items():
            self.store.put("ratings", f"{guild_id}:{user_id}", {"guild_id": guild_id, "user_id": user_id, "rating": rating})

    def leaderboard(self, guild_id, topic=None, since=None, preset=None, min_matches=1):
        stats = {}
        for match in self.store.list("matches", guild_id=guild_id):
            if not match.get("result") or not match["settings"]["ranked"]:
                continue
            if topic and topic.lower() not in match["topic"].lower():
                continue
            if since and match.get("ended_at", 0) < since:
                continue
            if preset and match.get("preset", "casual") != preset:
                continue
            result = match["result"]
            if result["outcome"] in ("cancelled", "inconclusive", "unjudged"):
                continue
            for user_id in match["participants"]:
                row = stats.setdefault(user_id, {"user_id": user_id, "wins": 0, "losses": 0, "draws": 0, "forfeits": 0, "matches": []})
                field = "draws" if result["winner_id"] is None else "wins" if result["winner_id"] == user_id else "losses"
                row[field] += 1
                row["forfeits"] += int(result["outcome"] == "forfeit" and result["winner_id"] != user_id)
                row["matches"].append(match["id"])
        for user_id, row in stats.items():
            row["rating"] = self.store.get("ratings", f"{guild_id}:{user_id}", {}).get("rating", 1200)
        return sorted((row for row in stats.values() if len(row["matches"]) >= min_matches),
                      key=lambda r: (-r["rating"], -r["wins"], r["user_id"]))

    def recover(self, now=None):
        now = time.time() if now is None else now
        checkpoint = self.store.get("system", "heartbeat")
        recovered = []
        with self.store.atomic():
            if checkpoint and now - checkpoint["time"] > 90:
                downtime = now - checkpoint["time"]
                for match in self.store.list("matches", status="active"):
                    if match["deadline"] is not None:
                        match["deadline"] += downtime
                        self._save(match, "outage_compensated", data={"seconds": downtime})
                        recovered.append({"kind": "recovered", "match_id": match["id"], "seconds": downtime})
            self.store.put("system", "heartbeat", {"time": now})
        return recovered

    def due(self, now=None):
        now = time.time() if now is None else now
        with self.store.atomic():
            events = self.recover(now)
            for match in self.store.list("matches", status="active"):
                deadline = match.get("deadline")
                if deadline is None:
                    continue
                if deadline <= now and match["settings"]["inactivity_forfeits"]:
                    winner = next(p for p in match["participants"] if p != match["next_speaker_id"])
                    self.end(match["id"], "forfeit", winner)
                    events.append({"kind": "ended", "match_id": match["id"]})
                elif match["settings"]["deadline_reminders"] and not match.get("reminded") and 0 < deadline - now <= match["settings"]["reminder_minutes"] * 60:
                    match["reminded"] = True
                    self._save(match, "reminder")
                    events.append({"kind": "reminder", "match_id": match["id"], "user_id": match["next_speaker_id"], "deadline": deadline})
            return events
