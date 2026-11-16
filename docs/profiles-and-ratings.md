# Profiles and ratings

`profiles.py` generates evidence-linked observations. `competition.py` owns Elo
replay and standings. `member_ui.py` provides `/profile`, history and leaderboard
filters. Public match records and optional generated profiles are distinct.

## Consent and observations

Profile defaults are analysis off, private visibility, training sharing off and
recommendations on. Only a profile's owner can change consent/visibility, correct
observations or remove insights. Staff cannot bypass another member's private
profile. Public match history remains separately accessible.

Generation requires an existing result, exactly two participants, the match's
profile feature and the player's analysis opt-in. It excludes matches before the
latest opt-in, matches at/before the removal cutoff and results requiring review.
Pending single-player LFG cancellations therefore generate no profile insights.

An observation includes its match link, assigned position, claims with source
quotes/URLs, topic and reasoning-approach tags, evidence/engagement counts and
available feedback. It describes managed debate activity; assigned positions are
not treated as personal beliefs. Aggregate tendencies, strengths and practice
needs require at least three included opted-in matches. Per-match history and
change-over-time records retain evidence references.

Owners can attach a 5–2000 character correction and optionally exclude an
observation. Exclusions survive regeneration and leave aggregate analysis.
Removal deletes the owner's generated insights, turns future analysis off and
records a cutoff that prevents old jobs from regenerating them. Turning analysis
off alone stops future generation without erasing existing observations.

Training summaries require the separate sharing preference. Turning off practice
recommendations suppresses recommendation lists and links. Privacy policy and
operator contact guidance live in [PRIVACY.md](../PRIVACY.md); service terms live
in [TERMS.md](../TERMS.md).

## Elo and public history

Elo is replayed deterministically in result creation order, with match ID as a
tiebreaker. A result is eligible only when there are exactly two players, ranked
play is enabled, both completed at least one turn, the outcome is judged/draw/
concession/forfeit, review is not pending and the pair's daily repeat cap permits
it. Casual play, cancellations, inconclusive results and training are unrated.
Server rating parameters are listed in [configuration](configuration.md).

The winner scores 1, loser 0 and a draw 0.5; the expected score uses the usual
400-point Elo logistic denominator. Rating changes retain before/after values
and result revision. Staff amendments replay all later results so corrected
ratings stay consistent. Transcript changes or contrary evidence can withdraw
eligibility until an explained staff review resolves the result.

`/leaderboard` filters rated results by topic, time, ranked format and minimum
match count. It sorts by current guild Elo; filtered win/loss/forfeit counts are
derived from qualifying results. `/profile` → **Public match history** shows
match states, outcomes, links and rating changes, with topic/time filters.
Audience votes remain separate from outcomes and Elo.
