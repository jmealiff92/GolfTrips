"""
LLM-based fourball partner suggestions and open-ended trip stats chat ("Captain Claude").

Given a team's available players for a day, asks Claude to split them into
pairs using each player's individual Fourball record, historical partner
synergy, and handicaps.

Beyond pairing suggestions, the chat also gives Claude tool access to query
match-by-match results (including score margins, to judge how tight a match
was), head-to-head records, partner history, and course performance, so it
can answer open-ended stats questions rather than only what's pre-baked into
the prompt context. Claude also has write tools to create matches and record
match results directly from natural-language requests (e.g. "create the 2026
day 2 matches at Druids Glen: Jeff & Jordan vs Conor & Ian", "Jeff beat Conor
1up") - see create_matches, create_course, and record_match_result below.
"""
import json
import logging
import os
import re
from typing import Optional

import anthropic
import pandas as pd

from src.handicap_calculator import HandicapCalculator
from src.match_score import validate_result_score

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_ATTEMPTS = 2
MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 6


def _json_default(value):
    """json.dumps default= hook: unwrap numpy/pandas scalars, stringify anything else."""
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _df_records(df) -> list:
    """DataFrame -> JSON-safe list of dicts (NaN -> None), or [] for None/empty input."""
    if df is None or getattr(df, "empty", True):
        return []
    return df.where(df.notnull(), None).to_dict('records')


def _serialize_content_blocks(blocks) -> list[dict]:
    """Anthropic SDK response content blocks -> plain JSON-safe dicts, for storing in dcc.Store
    and replaying back to the API on the next turn."""
    serialized = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block_type == "tool_use":
            serialized.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return serialized


class PairingSuggestionError(Exception):
    """Raised when pairing suggestions can't be produced; message is safe to show in the UI."""


VALID_MATCH_TYPES = ("Singles", "Fourball")


class PairingSuggester:
    """Uses the Claude API to suggest fourball partnerships, answer stats questions, and - via the
    create_matches/create_course/record_match_result tools - create matches and record results."""

    TOOLS = [
        {
            "name": "get_matches",
            "description": (
                "Look up individual match results, including each match's score/margin "
                "(e.g. '3&2', '1 up', 'AS') so you can judge how tight or lopsided it was, and "
                "exactly who played whom. Only returns matches with a decided result - pending/"
                "unfinalized matches are omitted. Filter by any combination of year, match type, "
                "player, and opponent. For a match-type-specific head-to-head (e.g. 'Jeff vs Conor in "
                "Singles'), pass both player and opponent together with match_type - get_head_to_head "
                "cannot filter by match_type, only get_matches can. In Singles, player+opponent always "
                "means they played each other; in Fourball it can also mean they were partners, so "
                "check the BluePlayer/RedPlayer columns in the result to tell which."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Trip year, e.g. 2026"},
                    "match_type": {
                        "type": "string", "enum": list(VALID_MATCH_TYPES),
                        "description": "Omit to include both Singles and Fourball matches.",
                    },
                    "player": {"type": "string", "description": "Only matches this player appeared in"},
                    "opponent": {
                        "type": "string",
                        "description": (
                            "Only matches this player AND `player` both appeared in (either as "
                            "opponents or, in Fourball, as partners - see the description above). "
                            "Requires `player` to also be set."
                        ),
                    },
                },
            },
        },
        {
            "name": "get_player_stats",
            "description": (
                "Overall win/loss/half record, win percentage, and points-per-game for one player, "
                "plus their handicap index for a given year. Omit match_type to get their combined "
                "record across all match types (Singles + Fourball) - this is the right default for "
                "general questions about a player. Only pass match_type when the question is "
                "specifically about their Fourball or Singles record (e.g. pairing decisions, which "
                "are always Fourball-only)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "player": {"type": "string"},
                    "match_type": {
                        "type": "string", "enum": list(VALID_MATCH_TYPES),
                        "description": "Omit for the player's combined record across all match types.",
                    },
                    "year": {"type": "integer", "description": "Year to look up the handicap index for"},
                },
                "required": ["player"],
            },
        },
        {
            "name": "get_head_to_head",
            "description": (
                "Head-to-head win/loss/half record between two specific players across every match "
                "they've played against each other, combined across Singles and Fourball - there is "
                "no match_type filter here. For a Singles-only or Fourball-only head-to-head, or to "
                "see the individual match scores/margins, use get_matches with player and opponent "
                "set to the two names (plus match_type if scoping to one type) instead."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "player1": {"type": "string"},
                    "player2": {"type": "string"},
                },
                "required": ["player1", "player2"],
            },
        },
        {
            "name": "get_partner_history",
            "description": (
                "Fourball partnership records - how pairs of players have performed together as "
                "partners. Optionally scoped to one player's partnerships."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Only partnerships involving this player"},
                },
            },
        },
        {
            "name": "get_course_stats",
            "description": "Aggregate Blue/Red record at each golf course played on the trip.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_player_course_performance",
            "description": (
                "One player's win/loss/half record broken down by course. Unlike get_matches and "
                "get_player_stats, `Matches` here counts every match recorded at that course "
                "including ones with no result yet - the `Pending` field on each course tells you "
                "how many of those are still unfinalized (Matches minus Wins, Halves, and Losses). "
                "When Pending is non-zero, mention it rather than letting the totals look "
                "inconsistent, e.g. 'Jeff is 2-0 at Druids Heath with 1 match still pending' - this "
                "matters for pairing decisions since only decided results are real signal."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"player": {"type": "string"}},
                "required": ["player"],
            },
        },
        {
            "name": "get_year_summary",
            "description": (
                "Overall Blue/Red point totals and the winner for one trip year, or every year if "
                "none is given. Points already account for halves (0.5 each) and are pre-computed - "
                "use this instead of manually tallying get_matches results to answer 'who won year "
                "X', 'how many years has each team won', or 'was year X close'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"year": {"type": "integer", "description": "Omit to get every year's summary."}},
            },
        },
        {
            "name": "get_team_points_by_day",
            "description": (
                "Cumulative Blue/Red points at the end of each day of a trip year, in order, for one "
                "year or every year if none is given. Each day already includes a `leader` field "
                "('Blue'/'Red'/'Tie') so you don't have to compare the point totals yourself. The "
                "last day's leader is the year's overall winner. Use this for any momentum/lead "
                "question - who led after day N, whether a team came from behind to win overall "
                "(compare the leader on an earlier day to the leader on the last day), which day had "
                "the biggest swing, whether the lead changed hands, etc. - by comparing the `leader` "
                "values directly rather than the raw point numbers. Don't reconstruct day-by-day "
                "standings by hand from get_matches; this tool already has the running totals and the "
                "leader resolved."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"year": {"type": "integer", "description": "Omit to get every year's day-by-day breakdown."}},
            },
        },
        {
            "name": "get_team_roster",
            "description": "Which players were on the Blue and Red teams for a given year, with each player's handicap index for that year.",
            "input_schema": {
                "type": "object",
                "properties": {"year": {"type": "integer"}},
                "required": ["year"],
            },
        },
        {
            "name": "get_course_details",
            "description": (
                "Par, slope rating, and course rating for one course, or every course if none is "
                "given. For win/loss records at a course use get_course_stats instead."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"course": {"type": "string", "description": "Omit to get every course."}},
            },
        },
        {
            "name": "get_player_handicap_history",
            "description": (
                "A player's handicap index in every year it was recorded, or every player's handicap "
                "history if no player is given. Use this for questions about handicap trends over "
                "time - get_player_stats only returns the handicap for one specified year."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"player": {"type": "string", "description": "Omit to get every player's handicap history."}},
            },
        },
        {
            "name": "get_trip_years",
            "description": "List of every year this trip has recorded matches for, most recent first.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_all_players",
            "description": "Full roster of every player registered in the system (Manage Players page), not limited to those with recorded matches.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "create_matches",
            "description": (
                "Create one or more matches for a specific year/day/course, e.g. from a message like "
                "'create the 2026 day 2 matches at druids glen: Jeff & Jordan vs Conor & Ian'. year, "
                "day, and course are REQUIRED - never guess any of them; ask the admin if any is "
                "missing from their message. Batch every match mentioned in one message into a single "
                "call (the `matches` list) so they're all created together, or none are if any of them "
                "fails validation. Each match's two sides don't need to specify team colors - just name "
                "the players; this tool resolves each player's actual Blue/Red team from that year's "
                "roster (case-insensitive, allows an unambiguous partial/first name), and rejects the "
                "match if a side mixes teams, both sides are the same team, or a name doesn't match "
                "exactly one player on that year's roster. If it returns a 'course_not_found' error, "
                "ask the admin for the course's par, slope rating, and course rating, call create_course "
                "with those, then retry create_matches. If it returns 'validation_failed', relay the "
                "listed problems to the admin and ask them to clarify rather than guessing. Handicaps "
                "are computed automatically the same way the Add Match page does - never pass or ask "
                "for them yourself."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Trip year, e.g. 2026. Required - never guess."},
                    "day": {"type": "integer", "description": "Day number within the trip, e.g. 2. Required - never guess."},
                    "course": {"type": "string", "description": "Course name. Required - never guess."},
                    "matches": {
                        "type": "array",
                        "description": "Every match to create in this batch.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "match_type": {"type": "string", "enum": list(VALID_MATCH_TYPES)},
                                "side_a_players": {
                                    "type": "array", "items": {"type": "string"},
                                    "description": "1 player for Singles, 2 for Fourball.",
                                },
                                "side_b_players": {
                                    "type": "array", "items": {"type": "string"},
                                    "description": "1 player for Singles, 2 for Fourball.",
                                },
                            },
                            "required": ["match_type", "side_a_players", "side_b_players"],
                        },
                    },
                },
                "required": ["year", "day", "course", "matches"],
            },
        },
        {
            "name": "create_course",
            "description": (
                "Create a new course record so it can be used by create_matches. Only call this after "
                "create_matches has returned a 'course_not_found' error for that name, and after you've "
                "asked the admin for the course's par, slope rating, and course rating - never guess "
                "those values."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "par": {"type": "integer"},
                    "slope_rating": {"type": "number"},
                    "course_rating": {"type": "number"},
                },
                "required": ["name", "par", "slope_rating", "course_rating"],
            },
        },
        {
            "name": "record_match_result",
            "description": (
                "Record the result of a match from a natural-language report like 'Jeff beat Conor 1up' "
                "or 'Ian lost to Jordan 1 down'. player_a/player_b are just the two players named in the "
                "message, in any order; `outcome` says which of them actually won (or 'half' if halved/"
                "all square) - always work out the winner yourself before calling. Always normalize "
                "`score` to the WINNING player's margin in the format '1UP', '3&2', etc, regardless of "
                "how the admin phrased it - e.g. 'Ian lost to Jordan 1 down' means Jordan won by 1, so "
                "call this with player_a='Ian', player_b='Jordan', outcome='player_b_won', "
                "score='1UP' (NOT '1 down' and NOT attached to Ian). If the admin didn't state a score "
                "at all, omit the `score` argument entirely rather than guessing - the tool will return "
                "a 'score_required'/'invalid_score' error so you can ask the admin for it; if they say "
                "they don't know or can't provide one, call again with score='Unknown'. Halved matches "
                "always record as score 'A/S' automatically - you don't need to pass a score for "
                "outcome='half'. If the admin didn't state a year/day, omit them and this tool searches "
                "for the one pending (not yet decided) match where these two players are on opposite "
                "sides; if it finds none ('no_pending_match') or more than one ('ambiguous_match'), it "
                "returns what it found so you can ask the admin to confirm the match (e.g. by year/day) "
                "rather than guessing."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "player_a": {"type": "string"},
                    "player_b": {"type": "string"},
                    "outcome": {
                        "type": "string", "enum": ["player_a_won", "player_b_won", "half"],
                        "description": "Which player won, or 'half' if the match was halved.",
                    },
                    "score": {
                        "type": "string",
                        "description": "Winner's margin, e.g. '1UP', '3&2', or 'Unknown'. Omit if the admin didn't state one.",
                    },
                    "year": {"type": "integer", "description": "Omit unless the admin stated it."},
                    "day": {"type": "integer", "description": "Omit unless the admin stated it."},
                },
                "required": ["player_a", "player_b", "outcome"],
            },
        },
    ]

    def __init__(self, data_service, db_service, api_key: Optional[str] = None, model: Optional[str] = None):
        self.data_service = data_service
        self.db_service = db_service
        self._api_key_override = api_key
        self.model = model or os.getenv('ANTHROPIC_MODEL', DEFAULT_MODEL)

    @property
    def api_key(self) -> Optional[str]:
        """Resolved fresh on every access (unless explicitly overridden) so a key added to the
        environment after process startup takes effect without requiring a restart."""
        return self._api_key_override if self._api_key_override is not None else os.getenv('ANTHROPIC_API_KEY')

    def suggest_pairings(self, team: str, year: int, available_players: list[str]) -> dict:
        """Return {'team', 'year', 'pairings': [...], 'conversation': [...]}.

        `conversation` is the raw Anthropic message history for this exchange, so a caller can
        hand it to `continue_conversation()` to keep discussing these pairings with full context.
        """
        players = list(dict.fromkeys(available_players))  # de-dupe, keep order
        if len(players) < 2:
            raise PairingSuggestionError("Select at least 2 players to generate pairings.")
        if len(players) % 2 != 0:
            raise PairingSuggestionError("Select an even number of players so everyone can be paired.")
        if not self.api_key:
            logger.warning("suggest_pairings called with no ANTHROPIC_API_KEY configured")
            raise PairingSuggestionError(
                "Claude pairing suggestions aren't configured. Add ANTHROPIC_API_KEY to your .env file."
            )

        prompt = self._build_suggestion_prompt(team, year, players)

        try:
            client = anthropic.Anthropic(api_key=self.api_key, timeout=30.0)
        except Exception as e:
            raise PairingSuggestionError(f"Could not initialize the Claude client: {e}") from e

        conversation = [{"role": "user", "content": prompt}]
        last_validation_error = None

        for _ in range(MAX_ATTEMPTS):
            text = self._send(client, conversation)

            try:
                pairings = self._parse_and_validate(text, players)
                conversation.append({"role": "assistant", "content": text})
                return {"team": team, "year": year, "pairings": pairings, "conversation": conversation}
            except ValueError as e:
                last_validation_error = e
                conversation.append({"role": "assistant", "content": text})
                conversation.append({
                    "role": "user",
                    "content": (
                        f"That response was invalid: {e}. Reply again with ONLY corrected JSON in the same "
                        f"format, covering each of these players exactly once: {players}."
                    ),
                })

        raise PairingSuggestionError(
            f"Claude did not return a valid pairing set after retrying: {last_validation_error}"
        )

    def continue_conversation(self, team: str, year: int, available_players: list[str],
                               conversation: Optional[list[dict]], user_message: str) -> dict:
        """Continue an open-ended chat with Captain Claude; return {'reply': str, 'conversation': [...]}.

        If `conversation` is empty (no suggestion has been generated yet), context covering both
        teams' full rosters for `year` is built locally at no API cost and bundled into this same
        request alongside the user's message, rather than spent on a separate priming call. This is
        deliberately broader than `available_players` (the checked subset for one team in the
        pairing UI) since chat questions aren't scoped to whichever team happens to be selected.
        """
        if not self.api_key:
            logger.warning("continue_conversation called with no ANTHROPIC_API_KEY configured")
            raise PairingSuggestionError(
                "Claude pairing suggestions aren't configured. Add ANTHROPIC_API_KEY to your .env file."
            )

        user_message = (user_message or "").strip()
        if not user_message:
            raise PairingSuggestionError("Type a message before sending.")

        if conversation:
            conversation = list(conversation)
            conversation.append({
                "role": "user",
                "content": (
                    f"{user_message}\n\n(Reply conversationally in plain text - you do not need to output "
                    "JSON for this unless explicitly asked to restate the full pairing list.)"
                ),
            })
        else:
            selected_players = list(dict.fromkeys(available_players or []))
            context = self._build_chat_context_block(year, selected_team=team, selected_players=selected_players)
            seed = f"""{context}
The admin has not generated a formatted pairing list yet. Answer their question - about pairings, \
individual/head-to-head/course stats, or anything else about the trip - conversationally in plain \
text, using the data above and your tools. They can click "Suggest Pairings" separately if they \
want a full formatted list.

Admin: {user_message}"""
            conversation = [{"role": "user", "content": seed}]

        try:
            client = anthropic.Anthropic(api_key=self.api_key, timeout=30.0)
        except Exception as e:
            raise PairingSuggestionError(f"Could not initialize the Claude client: {e}") from e

        reply = self._send(client, conversation)
        conversation.append({"role": "assistant", "content": reply})
        return {"reply": reply, "conversation": conversation}

    def _build_context_block(self, team: str, year: int, players: list[str]) -> str:
        header = f"""You are Captain Claude, helping a golf trip organizer with fourball (better-ball) \
partnerships for {year} and with any other questions they have about the trip's matches, players, and \
courses.

Team: {team}
Available players ({len(players)}): {', '.join(players)}
"""
        return header + self._build_context_body(players, year)

    def _build_chat_context_block(self, year: int, selected_team: Optional[str] = None,
                                   selected_players: Optional[list[str]] = None) -> str:
        """Context for open-ended chat: covers every player on both teams for `year`, not just
        whichever team/roster happens to be checked in the pairing UI right now, since chat
        questions ('how did Blue do this year', 'who's Jeff's best partner') aren't scoped to one
        team the way a pairing-suggestion request is."""
        try:
            assignments = self.db_service.get_team_assignments_by_year(year)
        except Exception:
            assignments = []
        blue_players = sorted(dict.fromkeys(a['name'] for a in assignments if a['team'] == 'Blue'))
        red_players = sorted(dict.fromkeys(a['name'] for a in assignments if a['team'] == 'Red'))
        all_players = list(dict.fromkeys(blue_players + red_players))

        selection_note = ""
        if selected_team and selected_players:
            selection_note = f"""
The admin currently has these {selected_team} players checked as available in the pairing tool \
above the chat: {', '.join(selected_players)}. That's just what's on-screen right now, not a \
restriction on who you can discuss or include in pairing suggestions.
"""

        header = f"""You are Captain Claude, helping a golf trip organizer with fourball (better-ball) \
partnerships for {year} and with any other questions they have about the trip's matches, players, and \
courses.

Blue team ({len(blue_players)}): {', '.join(blue_players) or 'none assigned'}
Red team ({len(red_players)}): {', '.join(red_players) or 'none assigned'}
{selection_note}"""
        return header + self._build_context_body(all_players, year)

    def _build_context_body(self, players: list[str], year: int) -> str:
        """Shared data/instructions block (stats, partner synergy, match history, tool guidance) -
        used by both the single-team pairing-suggestion prompt and the all-players chat context."""
        player_stats_text = self._format_player_stats(players, year)
        partner_history_text = self._format_partner_history(players)
        match_history_text = self._format_match_history(players)

        return f"""Fourball background: in fourball match play, each pair's better score counts on each hole. Playing \
handicaps use an 85% allowance, with the lowest course handicap in the group playing to scratch and \
everyone else receiving 85% of the difference - so pairing two very low-handicap players together does \
not by itself create an unfair advantage within their own pair.

The sections below are scoped to Fourball only, since that's the match type these pairings are for:

Individual Fourball performance to date:
{player_stats_text}

Historical partner synergy (Fourball matches only):
{partner_history_text}

Match-by-match Fourball results, with each score's margin (e.g. "1 down" or "2&1" is a very close \
result; "5&4" or "6&5" is a blowout; "AS"/halved means the match was tied after 18):
{match_history_text}

IMPORTANT - weigh the margins above, not just the raw win/loss tally: a player who is 1-3 but each \
loss was 1 down or 2&1 has been performing much better than the record suggests and shouldn't be \
treated as weak; a player who is 3-1 but every win was narrow and the loss was a 6&5 blowout isn't \
automatically the stronger pick either. Use the closeness of results, not just win/loss counts, when \
judging how well a player is likely to perform and who they're best paired with. This only applies \
to pairing decisions, which are always Fourball-only.

You also have tools to look up match-by-match results (including each match's score/margin, to judge \
how tight or lopsided it was), a player's full stats or handicap for a given year, head-to-head records \
between two players, partner history, course-by-course performance, per-year team point totals and \
winners, day-by-day team point progression, team rosters by year, course details (par/slope/rating), \
a player's handicap history across all years, the list of trip years, and the full player roster. Use \
them whenever a question needs more detail than the summary above.

PREFER PRE-AGGREGATED TOOLS OVER MANUAL ARITHMETIC - for anything about team standings, who won a \
year, or how the score moved over the course of a trip, call get_year_summary and/or \
get_team_points_by_day rather than adding up individual results from get_matches yourself. Those \
totals are pre-computed and already handle halves correctly (0.5 points) - recomputing them by hand \
from a list of match rows is exactly the kind of arithmetic that's easy to get wrong, so don't do it \
when a tool already has the answer.

LEAD / MOMENTUM / "CAME FROM BEHIND" QUESTIONS - for anything comparing who was ahead at one point in \
a trip to who ended up winning it (e.g. "did a team come from behind after day 1", "who led after day \
2", "did the lead change hands", "which years were comebacks"), call get_team_points_by_day and read \
its `leader` field for the days you need - do NOT compare the raw Blue/Red point numbers yourself. A \
"comeback" year is one where the leader on the day in question differs from the leader on the last \
day of that year (the last day's leader is the overall winner). Comparing precomputed `leader` labels \
across years is far less error-prone than comparing point totals by hand, which is where mistakes \
happen.

PENDING MATCHES - get_player_course_performance counts every match recorded at a course, including \
ones with no result yet (see its `Pending` field), unlike get_matches/get_player_stats which only \
count decided matches. When a course breakdown includes pending matches, say so explicitly (e.g. \
"2-0 completed at Druids Heath, 1 match still pending") rather than treating the raw match count as \
decided results - this matters for pairing decisions since only locked-in results are real signal.

SCOPE - the Fourball-only data above is for judging pairings. It is NOT the player's overall record. \
If the admin asks a general question about a player (their record, how good they are, how they've been \
playing, etc.) without specifying a match type, treat that as spanning ALL match types: call \
get_player_stats or get_matches with no match_type argument to get their combined Singles + Fourball \
picture, don't just reuse the Fourball-only summary above. Only scope an answer to one match type when \
the admin's question is specifically about pairings, Fourball, or Singles.

WHEN TO ASK RATHER THAN GUESS - most questions have an obvious default (see SCOPE above) and should \
just be answered. Ask a short clarifying question instead of answering, only when guessing could give \
a confidently wrong answer:
- A name doesn't match any known player, or could match more than one (e.g. two players with similar \
names) - ask which player they meant rather than picking one or assuming it's nobody.
- A tool call comes back empty in a way that's ambiguous between "no such matches happened" and "the \
name/filter was wrong" - say what you tried and ask them to confirm the name/year rather than stating \
"they've never played each other" as fact.
- The question depends on a year and there's more than one year on record where the answer would \
differ, with no year given or inferable from context - ask which year (or confirm "across all years") \
instead of picking one silently.
Never ask about things covered by a default above (match type, which team, etc.) - only ask when \
answering without asking would risk stating something false.

CREATING MATCHES - you can create matches directly with the create_matches tool, e.g. from "create the \
2026 day 2 matches at druids glen: Jeff & Jordan vs Conor & Ian, Ralph & Andy vs Matty & Neville". Year, \
day, and course are REQUIRED inputs to that tool - if the admin's message is missing any of them, ask \
for it before calling the tool; never guess or default them (not even to "today" or "the current trip \
year"). Batch every match from one message into a single create_matches call. You don't need to work out \
Blue/Red team colors yourself - just pass the named players for each side and the tool resolves their \
actual team from that year's roster, rejecting the match if partners aren't on the same team or the two \
sides are the same team; relay any 'validation_failed' problems to the admin plainly and ask them to \
clarify rather than retrying with a guess. If create_matches returns 'course_not_found', ask the admin \
for that course's par, slope rating, and course rating, call create_course with those values, then retry \
create_matches - never invent course data yourself. Never pass or estimate handicaps yourself; the tool \
computes them the same way the Add Match page does.

RECORDING MATCH RESULTS - you can record a result directly with record_match_result, e.g. from "Jeff \
beat Conor 1up" or "Ian lost to Jordan 1 down". Work out who actually won before calling: always express \
the score as the WINNER's margin (e.g. "1 down" for the loser becomes score="1UP" attached to the winner \
via `outcome`), never leave it framed from the loser's side. If the admin didn't state a score, omit the \
`score` argument and ask them for it once the tool confirms it's needed; if they say they don't know or \
can't provide one, call again with score="Unknown". Halved matches are automatic - score always ends up \
"A/S", you don't need to supply one for outcome="half". If the admin didn't mention a year or day, omit \
them and let the tool search for the one pending match between the two named players; if it comes back \
'no_pending_match' or 'ambiguous_match', tell the admin what you found (or didn't) and ask them to \
confirm the match/year/day rather than guessing which one they mean or silently picking the first result.
"""

    def _build_suggestion_prompt(self, team: str, year: int, players: list[str]) -> str:
        context = self._build_context_block(team, year, players)
        return f"""{context}
Task: produce the best possible set of {len(players) // 2} pairings for {team} from these {len(players)} \
players, using their individual records (informed by match margins as above, not just win/loss counts), \
historical synergy as partners, and handicaps to judge how well each pair is likely to perform. Every \
player must appear in exactly one pair.

Respond with ONLY valid JSON (no markdown fences, no extra text) in this exact shape:
{{"pairings": [{{"players": ["PlayerA", "PlayerB"], "rationale": "one or two sentence justification"}}]}}
"""

    def _send(self, client, conversation: list[dict]) -> str:
        """Call the Anthropic API and return the final reply text, wrapping any failure as
        PairingSuggestionError. Transparently runs Claude's tool calls (see TOOLS) against the
        data/db services, feeding results back until Claude produces a text reply or the
        iteration cap is hit, appending each turn to `conversation` in place as it goes."""
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._call_api(client, conversation)

            if response.stop_reason == "tool_use":
                conversation.append({
                    "role": "assistant", "content": _serialize_content_blocks(response.content),
                })
                tool_results = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        result_text = self._execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result", "tool_use_id": block.id, "content": result_text,
                        })
                conversation.append({"role": "user", "content": tool_results})
                continue

            text = "".join(
                block.text for block in response.content if getattr(block, "type", None) == "text"
            )
            if not text:
                raise PairingSuggestionError(
                    f"Claude returned an empty response (stop_reason: {response.stop_reason}). "
                    "Try rephrasing your message."
                )
            logger.info("Claude API reply received (%d chars)", len(text))
            return text

        raise PairingSuggestionError("Claude kept requesting tool calls without finishing a reply. Try again.")

    def _call_api(self, client, conversation: list[dict]):
        """One Claude API call, wrapping any failure as PairingSuggestionError."""
        logger.info("Calling Claude API (model=%s, turns=%d)", self.model, len(conversation))
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                tools=self.TOOLS,
                messages=conversation,
            )
        except anthropic.APITimeoutError as e:
            logger.warning("Claude API request timed out: %s", e)
            raise PairingSuggestionError("Claude API request timed out. Try again.") from e
        except anthropic.AuthenticationError as e:
            logger.warning("Claude API authentication error: %s", e)
            raise PairingSuggestionError(
                "Claude API rejected the configured API key. Check ANTHROPIC_API_KEY."
            ) from e
        except anthropic.RateLimitError as e:
            logger.warning("Claude API rate limit/quota error: %s", e)
            raise PairingSuggestionError(
                "Claude API rate limit or usage quota reached. Try again later."
            ) from e
        except anthropic.APIConnectionError as e:
            logger.warning("Claude API connection error: %s", e)
            raise PairingSuggestionError(
                "Could not reach the Claude API. Check your network connection and try again."
            ) from e
        except anthropic.APIError as e:
            logger.warning("Claude API error: %s", e)
            raise PairingSuggestionError(f"Claude API returned an error: {e}") from e

        block_types = [getattr(block, "type", None) for block in response.content]
        logger.info(
            "Claude API response: stop_reason=%s, stop_details=%s, block_types=%s",
            response.stop_reason, getattr(response, "stop_details", None), block_types
        )
        return response

    def _execute_tool(self, name: str, tool_input: Optional[dict]) -> str:
        """Dispatch one Claude tool call to the matching data/db service query, returning a JSON
        string (never raises - errors are reported back to Claude as {"error": ...} so it can
        recover or explain rather than aborting the whole exchange)."""
        handlers = {
            "get_matches": self._tool_get_matches,
            "get_player_stats": self._tool_get_player_stats,
            "get_head_to_head": self._tool_get_head_to_head,
            "get_partner_history": self._tool_get_partner_history,
            "get_course_stats": self._tool_get_course_stats,
            "get_player_course_performance": self._tool_get_player_course_performance,
            "get_year_summary": self._tool_get_year_summary,
            "get_team_points_by_day": self._tool_get_team_points_by_day,
            "get_team_roster": self._tool_get_team_roster,
            "get_course_details": self._tool_get_course_details,
            "get_player_handicap_history": self._tool_get_player_handicap_history,
            "get_trip_years": self._tool_get_trip_years,
            "get_all_players": self._tool_get_all_players,
            "create_matches": self._tool_create_matches,
            "create_course": self._tool_create_course,
            "record_match_result": self._tool_record_match_result,
        }
        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"unknown tool '{name}'"})

        logger.info("Executing tool '%s' with input %s", name, tool_input)
        try:
            return handler(**(tool_input or {}))
        except TypeError as e:
            return json.dumps({"error": f"invalid arguments for '{name}': {e}"})
        except Exception as e:
            logger.warning("Tool '%s' failed: %s", name, e)
            return json.dumps({"error": str(e)})

    @staticmethod
    def _validate_match_type(match_type: Optional[str]) -> None:
        if match_type is not None and match_type not in VALID_MATCH_TYPES:
            raise ValueError(
                f"invalid match_type {match_type!r}; must be one of {list(VALID_MATCH_TYPES)} or omitted"
            )

    def _tool_get_matches(self, year: Optional[int] = None, match_type: Optional[str] = None,
                           player: Optional[str] = None, opponent: Optional[str] = None) -> str:
        self._validate_match_type(match_type)
        df = self.data_service.df
        if df is None or df.empty:
            return json.dumps({"matches": []})

        if year is not None:
            df = df[df['Year'] == int(year)]
        if match_type:
            df = df[df['MatchType'] == match_type]
        if player:
            df = df[
                (df['BluePlayer1'] == player) | (df['BluePlayer2'] == player) |
                (df['RedPlayer1'] == player) | (df['RedPlayer2'] == player)
            ]
        if opponent:
            df = df[
                (df['BluePlayer1'] == opponent) | (df['BluePlayer2'] == opponent) |
                (df['RedPlayer1'] == opponent) | (df['RedPlayer2'] == opponent)
            ]
        df = df[df['Result'].notna() & (df['Result'] != '')]

        cols = ['Year', 'Day', 'MatchNumber', 'Course', 'MatchType',
                'BluePlayer1', 'BluePlayer2', 'RedPlayer1', 'RedPlayer2', 'Result', 'Score']
        df = df[cols].sort_values(by=['Year', 'Day', 'MatchNumber'])
        return json.dumps({"matches": _df_records(df)}, default=_json_default)

    def _tool_get_player_stats(self, player: str, match_type: Optional[str] = None,
                                year: Optional[int] = None) -> str:
        self._validate_match_type(match_type)
        df = self.data_service.get_player_performance_all_players(match_type or None)
        stats = None
        if df is not None and not df.empty:
            match = df[df['Player'] == player]
            if not match.empty:
                stats = _df_records(match)[0]

        handicap = None
        if year is not None:
            try:
                handicap = self.db_service.get_player_handicap(player, int(year))
            except Exception:
                handicap = None

        return json.dumps({
            "player": player, "match_type": match_type or "All",
            "stats": stats, "handicap_index": handicap,
        }, default=_json_default)

    def _tool_get_head_to_head(self, player1: str, player2: str) -> str:
        result = self.data_service.get_head_to_head_stats(player1, player2) or {}
        return json.dumps({"player1": player1, "player2": player2, **result}, default=_json_default)

    def _tool_get_partner_history(self, player: Optional[str] = None) -> str:
        df = self.data_service.get_partner_performace(player or 'All')
        return json.dumps({"partnerships": _df_records(df)}, default=_json_default)

    def _tool_get_course_stats(self) -> str:
        df = self.data_service.get_course_statistics()
        return json.dumps({"courses": _df_records(df)}, default=_json_default)

    def _tool_get_player_course_performance(self, player: str) -> str:
        df = self.data_service.get_player_course_performance(player)
        if df is not None and not df.empty:
            df = df.copy()
            df['Pending'] = df['Matches'] - (df['Wins'] + df['Halves'] + df['Losses'])
        return json.dumps({"player": player, "courses": _df_records(df)}, default=_json_default)

    def _tool_get_year_summary(self, year: Optional[int] = None) -> str:
        df = self.data_service.summarise_team_results()
        if df is not None and not df.empty and year is not None:
            df = df[df['Year'] == int(year)]
        return json.dumps({"years": _df_records(df)}, default=_json_default)

    def _tool_get_team_points_by_day(self, year: Optional[int] = None) -> str:
        by_year = self.data_service.get_team_points_by_day()
        if year is not None:
            by_year = {k: v for k, v in by_year.items() if k == int(year)}
        return json.dumps({"team_points_by_day": by_year}, default=_json_default)

    def _tool_get_team_roster(self, year: int) -> str:
        roster = self.db_service.get_team_assignments_by_year(int(year))
        return json.dumps({"year": year, "roster": roster}, default=_json_default)

    def _tool_get_course_details(self, course: Optional[str] = None) -> str:
        if course:
            return json.dumps({"course": self.db_service.get_course(course)}, default=_json_default)
        return json.dumps({"courses": self.db_service.get_all_courses()}, default=_json_default)

    def _tool_get_player_handicap_history(self, player: Optional[str] = None) -> str:
        if player:
            return json.dumps({"player": self.db_service.get_player_with_handicaps(player)}, default=_json_default)
        return json.dumps({"players": self.db_service.get_all_players_with_handicaps()}, default=_json_default)

    def _tool_get_trip_years(self) -> str:
        return json.dumps({"years": self.db_service.get_years_list()}, default=_json_default)

    def _tool_get_all_players(self) -> str:
        return json.dumps({"players": self.db_service.get_all_players()}, default=_json_default)

    @staticmethod
    def _clean_handicap(value) -> Optional[float]:
        """get_team_assignments_by_year LEFT JOINs handicaps, so a player with no handicap row for
        that year comes back as NaN (not None) once it's passed through a DataFrame - normalize
        both to None so 'missing handicap' checks work regardless of which one shows up."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return value

    def _resolve_player(self, name: str, year: int) -> dict:
        """Resolve a user-typed name to {'name', 'team', 'handicap_index'} against `year`'s roster.
        Case-insensitive exact match first, then unambiguous case-insensitive substring match
        (e.g. 'Jeff' -> 'Jeff Smith' if he's the only Jeff on the roster). On failure returns
        {'error': 'not_found'|'ambiguous'|'no_roster', ...} for the caller to relay to Claude."""
        roster = self.db_service.get_team_assignments_by_year(int(year))
        if not roster:
            return {
                "error": "no_roster", "name": name, "year": year,
                "message": f"No players are assigned to a team for {year}.",
            }

        query = (name or "").strip().lower()
        exact = [p for p in roster if p["name"].strip().lower() == query]
        if len(exact) == 1:
            match = exact[0]
            return {
                "name": match["name"], "team": match["team"],
                "handicap_index": self._clean_handicap(match.get("handicap_index")),
            }
        if len(exact) > 1:
            return {"error": "ambiguous", "name": name, "candidates": [p["name"] for p in exact]}

        partial = [p for p in roster if query and query in p["name"].strip().lower()]
        if len(partial) == 1:
            match = partial[0]
            return {
                "name": match["name"], "team": match["team"],
                "handicap_index": self._clean_handicap(match.get("handicap_index")),
            }
        if len(partial) > 1:
            return {"error": "ambiguous", "name": name, "candidates": [p["name"] for p in partial]}

        return {
            "error": "not_found", "name": name, "year": year,
            "message": f"No player matching {name!r} is on the {year} roster.",
        }

    @staticmethod
    def _describe_resolution_error(resolved: dict) -> str:
        if resolved.get("error") == "ambiguous":
            return f"{resolved['name']!r} matches multiple players: {', '.join(resolved.get('candidates', []))} - ask which one"
        if resolved.get("error") in ("not_found", "no_roster"):
            return resolved.get("message", f"couldn't resolve {resolved.get('name')!r}")
        return str(resolved)

    def _resolve_course(self, name: str) -> dict:
        """Resolve a user-typed course name against the courses table, case-insensitive exact match
        first then unambiguous substring match. Returns the course dict, or {'error': ...} on failure."""
        courses = self.db_service.get_all_courses()
        query = (name or "").strip().lower()
        exact = [c for c in courses if c["name"].strip().lower() == query]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            return {"error": "ambiguous", "course": name, "candidates": [c["name"] for c in exact]}

        partial = [c for c in courses if query and query in c["name"].strip().lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            return {"error": "ambiguous", "course": name, "candidates": [c["name"] for c in partial]}

        return {"error": "not_found", "course": name}

    def _tool_create_course(self, name: str, par: int, slope_rating: float, course_rating: float) -> str:
        courses = self.db_service.get_all_courses()
        if any(c["name"].strip().lower() == (name or "").strip().lower() for c in courses):
            return json.dumps({"error": f"a course named {name!r} already exists"})

        ok = self.db_service.add_course(name.strip(), int(par), float(slope_rating), float(course_rating))
        if not ok:
            return json.dumps({"error": f"failed to create course {name!r}"})
        return json.dumps({"course": self.db_service.get_course(name.strip())}, default=_json_default)

    def _tool_create_matches(self, year: int, day: int, course: str, matches: Optional[list] = None) -> str:
        year = int(year)
        day = int(day)
        matches = matches or []
        if not matches:
            return json.dumps({"error": "no matches given"})

        course_info = self._resolve_course(course)
        if "error" in course_info:
            return json.dumps({
                "error": "course_not_found", "course": course,
                "message": f"No course matching {course!r} was found. Ask the admin for its par, "
                           f"slope rating, and course rating, then call create_course.",
            })

        errors = []
        resolved_matches = []
        for i, m in enumerate(matches, start=1):
            match_type = m.get("match_type")
            if match_type not in VALID_MATCH_TYPES:
                errors.append(f"match {i}: invalid match_type {match_type!r}")
                continue

            side_a = list(dict.fromkeys(m.get("side_a_players") or []))
            side_b = list(dict.fromkeys(m.get("side_b_players") or []))
            expected = 1 if match_type == "Singles" else 2
            if len(side_a) != expected or len(side_b) != expected:
                errors.append(
                    f"match {i}: {match_type} needs {expected} player(s) per side "
                    f"(got {len(side_a)} vs {len(side_b)})"
                )
                continue

            resolved_a = [self._resolve_player(p, year) for p in side_a]
            resolved_b = [self._resolve_player(p, year) for p in side_b]
            bad = [r for r in resolved_a + resolved_b if "error" in r]
            if bad:
                for r in bad:
                    errors.append(f"match {i}: {self._describe_resolution_error(r)}")
                continue

            all_names = [r["name"] for r in resolved_a + resolved_b]
            if len(set(all_names)) != len(all_names):
                errors.append(f"match {i}: the same player appears more than once")
                continue

            teams_a = {r["team"] for r in resolved_a}
            teams_b = {r["team"] for r in resolved_b}
            if len(teams_a) != 1 or len(teams_b) != 1:
                errors.append(f"match {i}: partners must be on the same team ({side_a} / {side_b})")
                continue
            team_a, team_b = next(iter(teams_a)), next(iter(teams_b))
            if team_a == team_b:
                errors.append(
                    f"match {i}: both sides are on team {team_a} - opponents must be on opposite teams"
                )
                continue

            missing_hcp = [r["name"] for r in resolved_a + resolved_b if r.get("handicap_index") is None]
            if missing_hcp:
                errors.append(f"match {i}: no {year} handicap index on file for {', '.join(missing_hcp)}")
                continue

            blue, red = (resolved_a, resolved_b) if team_a == "Blue" else (resolved_b, resolved_a)
            resolved_matches.append({"match_type": match_type, "blue": blue, "red": red})

        if errors:
            return json.dumps({"error": "validation_failed", "problems": errors})

        created = []
        for entry in resolved_matches:
            blue, red = entry["blue"], entry["red"]
            if entry["match_type"] == "Singles":
                p1_hcp, p3_hcp = HandicapCalculator.calculate_match_handicaps(
                    match_type="Singles",
                    handicap_index_p1=blue[0]["handicap_index"], handicap_index_p2=None,
                    handicap_index_p3=red[0]["handicap_index"], handicap_index_p4=None,
                    slope_rating=course_info["slope_rating"], par=course_info["par"],
                )
                blue_hcp, red_hcp = [p1_hcp, None], [p3_hcp, None]
            else:
                p1_hcp, p2_hcp, p3_hcp, p4_hcp = HandicapCalculator.calculate_match_handicaps(
                    match_type="Fourball",
                    handicap_index_p1=blue[0]["handicap_index"], handicap_index_p2=blue[1]["handicap_index"],
                    handicap_index_p3=red[0]["handicap_index"], handicap_index_p4=red[1]["handicap_index"],
                    slope_rating=course_info["slope_rating"], par=course_info["par"],
                )
                blue_hcp, red_hcp = [p1_hcp, p2_hcp], [p3_hcp, p4_hcp]

            match_number = self.db_service.get_next_match_number(year, day)
            while self.db_service.check_match_exists(year, day, match_number):
                match_number += 1

            ok = self.db_service.add_match(
                year=year, day=day, match_number=match_number,
                course=course_info["name"], match_type=entry["match_type"],
                blue_player1=blue[0]["name"], blue_player1_handicap=blue_hcp[0],
                blue_player2=blue[1]["name"] if len(blue) > 1 else None, blue_player2_handicap=blue_hcp[1],
                red_player1=red[0]["name"], red_player1_handicap=red_hcp[0],
                red_player2=red[1]["name"] if len(red) > 1 else None, red_player2_handicap=red_hcp[1],
                result="", score="",
            )
            if not ok:
                created.append({
                    "error": f"failed to save match {match_number} (Year {year}, Day {day}) - "
                             f"it may already exist",
                })
                continue

            created.append({
                "year": year, "day": day, "match_number": match_number,
                "course": course_info["name"], "match_type": entry["match_type"],
                "blue_players": [
                    {"name": p["name"], "handicap": h} for p, h in zip(blue, blue_hcp)
                ],
                "red_players": [
                    {"name": p["name"], "handicap": h} for p, h in zip(red, red_hcp)
                ],
            })

        self.data_service.invalidate_cache()
        return json.dumps({"created": created}, default=_json_default)

    def _tool_record_match_result(self, player_a: str, player_b: str, outcome: str,
                                   score: Optional[str] = None, year: Optional[int] = None,
                                   day: Optional[int] = None) -> str:
        if outcome not in ("player_a_won", "player_b_won", "half"):
            return json.dumps({"error": f"invalid outcome {outcome!r}"})

        df = self.data_service.df
        if df is None or df.empty:
            return json.dumps({
                "error": "no_pending_match", "player_a": player_a, "player_b": player_b,
                "message": "There are no matches recorded at all.",
            })

        pending = df[df["Result"].isna() | (df["Result"] == "")]
        if year is not None:
            pending = pending[pending["Year"] == int(year)]
        if day is not None:
            pending = pending[pending["Day"] == int(day)]

        def _side_of(row, name):
            query = (name or "").strip().lower()
            if not query:
                return None
            slots = {
                "Blue": [row.get("BluePlayer1"), row.get("BluePlayer2")],
                "Red": [row.get("RedPlayer1"), row.get("RedPlayer2")],
            }
            for side, players in slots.items():
                for p in players:
                    p_name = str(p or "").strip().lower()
                    if p_name and (p_name == query or query in p_name):
                        return side
            return None

        candidates = []
        for _, row in pending.iterrows():
            side_a = _side_of(row, player_a)
            side_b = _side_of(row, player_b)
            if side_a and side_b and side_a != side_b:
                candidates.append(row)

        if not candidates:
            return json.dumps({
                "error": "no_pending_match", "player_a": player_a, "player_b": player_b,
                "year": year, "day": day,
                "message": (
                    f"No pending match found where {player_a} and {player_b} are on opposite sides"
                    + (f" for {year} day {day}" if year and day else "")
                    + ". Ask the admin to confirm the year/day, or the player names."
                ),
            }, default=_json_default)

        if len(candidates) > 1:
            return json.dumps({
                "error": "ambiguous_match", "player_a": player_a, "player_b": player_b,
                "candidates": [
                    {
                        "year": int(row["Year"]), "day": int(row["Day"]), "match_number": int(row["MatchNumber"]),
                        "course": row["Course"], "match_type": row["MatchType"],
                    }
                    for row in candidates
                ],
                "message": "More than one pending match matches these players - ask the admin which one (or for year/day).",
            }, default=_json_default)

        row = candidates[0]
        match_year, match_day, match_number = int(row["Year"]), int(row["Day"]), int(row["MatchNumber"])
        side_a, side_b = _side_of(row, player_a), _side_of(row, player_b)

        if outcome == "half":
            result = "Half"
        elif outcome == "player_a_won":
            result = side_a
        else:
            result = side_b

        ok, normalized_result, normalized_score, error_message = validate_result_score(result, score)
        if not ok:
            error_type = "score_required" if not (score or "").strip() else "invalid_score"
            return json.dumps({"error": error_type, "message": error_message})

        success = self.db_service.update_match_result(match_year, match_day, match_number,
                                                        normalized_result, normalized_score)
        if not success:
            return json.dumps({
                "error": f"failed to update match {match_number} (Year {match_year}, Day {match_day})",
            })

        self.data_service.invalidate_cache()
        return json.dumps({
            "updated": {
                "year": match_year, "day": match_day, "match_number": match_number,
                "course": row["Course"], "match_type": row["MatchType"],
                "result": normalized_result, "score": normalized_score,
            },
        }, default=_json_default)

    def _format_player_stats(self, players: list[str], year: int) -> str:
        try:
            df = self.data_service.get_player_performance_all_players('Fourball')
        except Exception:
            df = None

        stats_by_player = {}
        if df is not None and not df.empty:
            stats_by_player = {row['Player']: row for _, row in df.iterrows()}

        lines = []
        for name in players:
            try:
                handicap = self.db_service.get_player_handicap(name, year)
            except Exception:
                handicap = None
            handicap_text = f"{handicap:.1f}" if handicap is not None else "unknown"

            row = stats_by_player.get(name)
            if row is not None:
                lines.append(
                    f"- {name}: handicap index {handicap_text}, {int(row['Matches'])} matches, "
                    f"{int(row['Wins'])} wins, {int(row['Losses'])} losses, {int(row['Halves'])} halves, "
                    f"{row['Win %']:.1f}% win rate, {row['PPG']:.2f} PPG"
                )
            else:
                lines.append(f"- {name}: handicap index {handicap_text}, no Fourball match history yet")
        return "\n".join(lines) if lines else "No players supplied."

    def _format_match_history(self, players: list[str], match_type: str = 'Fourball') -> str:
        try:
            df = self.data_service.df
        except Exception:
            df = None
        if df is None or df.empty:
            return "No match history yet."

        df = df[df['MatchType'] == match_type]
        df = df[df['Result'].notna() & (df['Result'] != '')]
        if df.empty:
            return f"No {match_type} match history yet."

        lines = []
        for name in players:
            player_df = df[
                (df['BluePlayer1'] == name) | (df['BluePlayer2'] == name) |
                (df['RedPlayer1'] == name) | (df['RedPlayer2'] == name)
            ].sort_values(by=['Year', 'Day', 'MatchNumber'])

            if player_df.empty:
                lines.append(f"- {name}: no {match_type} match history yet")
                continue

            results = []
            for _, m in player_df.iterrows():
                player_side = 'Blue' if name in (m['BluePlayer1'], m['BluePlayer2']) else 'Red'
                if m['Result'] == 'Half':
                    outcome = 'halved'
                elif m['Result'] == player_side:
                    outcome = 'won'
                else:
                    outcome = 'lost'
                score = m['Score'] if m['Score'] else 'no score recorded'
                results.append(f"{m['Year']} Day {int(m['Day'])}: {outcome} {score}")
            lines.append(f"- {name}: " + "; ".join(results))

        return "\n".join(lines)

    def _format_partner_history(self, players: list[str]) -> str:
        try:
            df = self.data_service.get_partner_performace()
        except Exception:
            df = None

        if df is None or df.empty:
            return "No historical Fourball partnerships recorded yet."

        available = set(players)
        lines = []
        for _, row in df.iterrows():
            partnership = row.get('partnership')
            if not isinstance(partnership, str) or ' & ' not in partnership:
                continue
            p1, p2 = partnership.split(' & ', 1)
            if p1 in available and p2 in available:
                lines.append(
                    f"- {p1} & {p2}: {int(row['Matches'])} matches together, {int(row['Wins'])} wins, "
                    f"{int(row['Halves'])} halves, {int(row['Losses'])} losses, {row['PPG']:.2f} PPG"
                )

        if not lines:
            return "None of the available players have played as Fourball partners together before."
        lines.append("(Pairs not listed above have no shared Fourball history.)")
        return "\n".join(lines)

    def _parse_and_validate(self, text: str, players: list[str]) -> list[dict]:
        data = self._extract_json(text)

        if not isinstance(data, dict) or 'pairings' not in data:
            raise ValueError("response JSON did not contain a 'pairings' list")

        pairings = data['pairings']
        if not isinstance(pairings, list):
            raise ValueError("'pairings' was not a list")

        seen = []
        cleaned = []
        for entry in pairings:
            if not isinstance(entry, dict) or 'players' not in entry:
                raise ValueError("each pairing must be an object with a 'players' list")
            pair = entry['players']
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError(f"pairing {pair!r} does not have exactly 2 players")
            if pair[0] == pair[1]:
                raise ValueError(f"pairing {pair!r} pairs a player with themselves")
            seen.extend(pair)
            cleaned.append({
                "players": [pair[0], pair[1]],
                "rationale": str(entry.get('rationale', '')).strip(),
            })

        if sorted(seen) != sorted(players):
            missing = set(players) - set(seen)
            extra = set(seen) - set(players)
            detail = []
            if missing:
                detail.append(f"missing {sorted(missing)}")
            if extra:
                detail.append(f"unexpected {sorted(extra)}")
            if len(seen) != len(set(seen)):
                detail.append("a player appears more than once")
            raise ValueError(f"pairings did not cover every player exactly once ({'; '.join(detail)})")

        return cleaned

    @staticmethod
    def _extract_json(text: str):
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"response was not valid JSON: {e}") from e
