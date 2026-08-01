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


def _summarize_conversation_shape(conversation) -> list:
    """Compact, log-safe structural summary of a `messages` list - role, content type, and (for
    block-list content) each block's type - for diagnosing 'Input does not match the expected
    shape' API errors without dumping full message text into the logs."""
    if not isinstance(conversation, list):
        return [{"error": f"conversation is not a list: {type(conversation).__name__}"}]
    summary = []
    for i, msg in enumerate(conversation):
        if not isinstance(msg, dict):
            summary.append({"index": i, "error": f"not a dict: {type(msg).__name__}"})
            continue
        content = msg.get("content")
        if isinstance(content, str):
            summary.append({"index": i, "role": msg.get("role"), "content_type": "str", "len": len(content)})
        elif isinstance(content, list):
            summary.append({
                "index": i, "role": msg.get("role"), "content_type": "list",
                "blocks": [b.get("type") if isinstance(b, dict) else type(b).__name__ for b in content],
            })
        else:
            summary.append({"index": i, "role": msg.get("role"), "content_type": type(content).__name__})
    return summary


def _serialize_content_blocks(blocks) -> list[dict]:
    """Anthropic SDK response content blocks -> plain JSON-safe dicts, for storing in dcc.Store
    and replaying back to the API on the next turn. Every block type Claude can return in a
    tool-calling turn must round-trip here - dropping any of them (e.g. thinking blocks) corrupts
    the conversation's shape, and the next API call fails with a 400 'Input does not match the
    expected shape' error, since extended thinking requires its thinking/redacted_thinking blocks
    to be echoed back unmodified (signature included) alongside any tool_use in the same turn."""
    serialized = []
    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            serialized.append({"type": "text", "text": block.text})
        elif block_type == "tool_use":
            serialized.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
        elif block_type == "thinking":
            serialized.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature})
        elif block_type == "redacted_thinking":
            serialized.append({"type": "redacted_thinking", "data": block.data})
    return serialized


class PairingSuggestionError(Exception):
    """Raised when pairing suggestions can't be produced; message is safe to show in the UI."""


VALID_MATCH_TYPES = ("Singles", "Fourball")
VALID_MATCH_STATUSES = ("decided", "pending", "all")


class PairingSuggester:
    """Uses the Claude API to suggest fourball partnerships, answer stats questions, and - via the
    create_matches/create_course/record_match_result tools - create matches and record results."""

    TOOLS = [
        {
            "name": "get_matches",
            "description": (
                "Look up individual match results, including each match's score/margin "
                "(e.g. '3&2', '1 up', 'AS') so you can judge how tight or lopsided it was, and "
                "exactly who played whom. By default only returns matches with a decided result - "
                "pass `status` to include scheduled-but-undecided matches; see the `status` "
                "parameter description before ever concluding no matches exist for a given year/"
                "player/filter. Filter by any combination of year, match type, player, and opponent. "
                "For a match-type-specific head-to-head (e.g. 'Jeff vs Conor in Singles'), pass both "
                "player and opponent together with match_type - get_head_to_head cannot filter by "
                "match_type, only get_matches can. In Singles, player+opponent always means they "
                "played each other; in Fourball it can also mean they were partners, so check the "
                "BluePlayer/RedPlayer columns in the result to tell which."
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
                    "status": {
                        "type": "string",
                        "enum": list(VALID_MATCH_STATUSES),
                        "description": (
                            "Which matches to include, based on whether a result has been recorded. "
                            "Defaults to 'decided' (only matches with a final Result/Score) - this is "
                            "the same behavior this tool has always had, since score margins only "
                            "exist for decided matches. Pass 'pending' to see matches that have been "
                            "scheduled/created but not yet played (Result and Score will be empty - "
                            "there's no margin to analyze for these). Pass 'all' for every match "
                            "regardless of status. IMPORTANT: an empty or short result list under the "
                            "default 'decided' status does NOT mean no matches exist for that year/"
                            "player/filter - it only means none are decided yet. Before telling an "
                            "admin there are no matches for a year or other filter, or when answering "
                            "a general 'what matches are there' question, call again with "
                            "status='all' or 'pending' to check for scheduled matches."
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
            "description": (
                "Aggregate Blue/Red record at each golf course played on the trip. `Matches` counts "
                "every match recorded at that course including ones with no result yet - the "
                "`Pending` field tells you how many of those are still unfinalized. When Pending is "
                "non-zero, mention it rather than letting the totals look inconsistent."
            ),
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
                "for them yourself, using whatever par/slope rating/course rating is on file for the "
                "resolved course. Nothing is ever created on the first call: with `confirm` omitted or "
                "false, this validates everything and returns 'confirm_required' with a full preview - "
                "the course's par/slope rating/course rating, plus each proposed match's Blue vs Red "
                "players and their computed handicaps - and creates nothing. Read that preview back to "
                "the admin in full (don't just say 'ready to create X matches' - list who's on each side "
                "and the handicaps) and wait for their explicit go-ahead in a NEW message. Only then call "
                "create_matches again with confirm=true and the exact same year/day/course/matches to "
                "actually create them. Never call it twice with confirm=true in the same turn - always "
                "stop and wait for the admin's next message after showing the preview. If the admin "
                "points out something wrong in the preview (course numbers, pairings), fix the input "
                "(e.g. update_course, or correct the matches list) and preview again rather than forcing "
                "confirm=true through."
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
                    "confirm": {
                        "type": "boolean",
                        "description": (
                            "Set true only on a second call, after the admin has explicitly approved the "
                            "preview (course details + resolved matches/handicaps) returned by the first "
                            "call. Omit or leave false on the first attempt - nothing is created until "
                            "confirm=true."
                        ),
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
            "name": "update_course",
            "description": (
                "Update an existing course's par, slope rating, and/or course rating - e.g. 'update "
                "Druids Glen to slope 132' or 'the par for Druids Glen is actually 72, not 71'. Resolves "
                "`name` the same way create_matches does (case-insensitive, unambiguous partial match); "
                "if it can't find exactly one matching course it returns an error rather than guessing. "
                "Only pass the field(s) the admin actually wants changed - any field you omit keeps its "
                "current stored value, so you don't need to ask for or restate values that aren't "
                "changing. Never guess a new value the admin didn't state."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "par": {"type": "integer", "description": "Omit to leave par unchanged."},
                    "slope_rating": {"type": "number", "description": "Omit to leave slope rating unchanged."},
                    "course_rating": {"type": "number", "description": "Omit to leave course rating unchanged."},
                },
                "required": ["name"],
            },
        },
        {
            "name": "record_match_result",
            "description": (
                "Record the result of a match from a natural-language report like 'Jeff beat Conor 1up' "
                "or 'Ian lost to Jordan 1 down'. For SINGLES (or to identify a match by just one player "
                "from each side), use player_a/player_b - just the two players named in the message, in "
                "any order; `outcome` says which of them actually won (or 'half' if halved/all square) - "
                "always work out the winner yourself before calling. For FOURBALL results reported as a "
                "pairing vs pairing (e.g. 'Jeff & Jordan beat Conor & Ian 2&1', 'Ralph & Andy halved with "
                "Matty & Neville'), use fourball_side_a/fourball_side_b INSTEAD - each a list of exactly "
                "the 2 partners on that side - and never call this twice with individual names for a "
                "Fourball result: the tool expects player_a/player_b to be OPPONENTS, not partners, so two "
                "separate single-name calls won't find the match. Provide either player_a+player_b OR "
                "fourball_side_a+fourball_side_b, never both. In fourball mode `outcome` still refers to "
                "fourball_side_a ('player_a_won' = side_a won) / fourball_side_b ('player_b_won' = side_b "
                "won). Always normalize `score` to the WINNING side's margin in the format '1UP', '3&2', "
                "etc, regardless of how the admin phrased it - e.g. 'Ian lost to Jordan 1 down' means "
                "Jordan won by 1, so call this with player_a='Ian', player_b='Jordan', "
                "outcome='player_b_won', score='1UP' (NOT '1 down' and NOT attached to Ian). If the admin "
                "didn't state a score at all, omit the `score` argument entirely rather than guessing - "
                "the tool will return a 'score_required'/'invalid_score' error so you can ask the admin "
                "for it; if they say they don't know or can't provide one, call again with "
                "score='Unknown'. Halved matches always record as score 'A/S' automatically - you don't "
                "need to pass a score for outcome='half'. If the admin didn't state a year/day, omit them "
                "and this tool searches for the one pending (not yet decided) match where these players "
                "are on opposite sides; if it finds none ('no_pending_match') or more than one "
                "('ambiguous_match'), it returns what it found so you can ask the admin to confirm the "
                "match (e.g. by year/day) rather than guessing. To undo a result that was recorded "
                "incorrectly (e.g. 'clear the result for Jeff vs Conor', 'that was wrong, they haven't "
                "played yet'), call this with outcome='clear' (same player_a/player_b or "
                "fourball_side_a/fourball_side_b rules apply) - it searches decided (non-pending) matches "
                "instead of pending ones, resets the match back to pending (no result, no score), and you "
                "don't need to pass `score`. Same 'no_result_to_clear'/'ambiguous_match' handling applies "
                "if it can't find exactly one match to clear. Nothing is ever written on the first call: "
                "with `confirm` omitted or false, once a single matching match is found and the "
                "result/score are valid, this returns 'confirm_required' with a preview of exactly what "
                "would change (the match's year/day/course/players and the proposed result/score, or "
                "'reset to pending' for outcome='clear') and writes nothing. Read that preview back to "
                "the admin (e.g. 'I'll record Jeff beat Conor 1UP for the Year 2026 Day 2 match at Druids "
                "Glen - confirm?') and wait for their explicit go-ahead in a NEW message before calling "
                "again with confirm=true and the same arguments. Never call it twice with confirm=true in "
                "the same turn."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "player_a": {
                        "type": "string",
                        "description": "Singles mode: one player. Omit if using fourball_side_a/fourball_side_b instead.",
                    },
                    "player_b": {
                        "type": "string",
                        "description": "Singles mode: one player. Omit if using fourball_side_a/fourball_side_b instead.",
                    },
                    "fourball_side_a": {
                        "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2,
                        "description": (
                            "Fourball mode: both partners on one side, e.g. ['Jeff', 'Jordan']. Use with "
                            "fourball_side_b instead of player_a/player_b."
                        ),
                    },
                    "fourball_side_b": {
                        "type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2,
                        "description": (
                            "Fourball mode: both partners on the other side. Use with fourball_side_a "
                            "instead of player_a/player_b."
                        ),
                    },
                    "outcome": {
                        "type": "string", "enum": ["player_a_won", "player_b_won", "half", "clear"],
                        "description": (
                            "Which side won - player_a/fourball_side_a vs player_b/fourball_side_b - "
                            "'half' if halved, or 'clear' to undo an incorrectly-recorded result and "
                            "reset the match back to pending."
                        ),
                    },
                    "score": {
                        "type": "string",
                        "description": "Winner's margin, e.g. '1UP', '3&2', or 'Unknown'. Omit if the admin didn't state one.",
                    },
                    "year": {"type": "integer", "description": "Omit unless the admin stated it."},
                    "day": {"type": "integer", "description": "Omit unless the admin stated it."},
                    "confirm": {
                        "type": "boolean",
                        "description": (
                            "Set true only on a second call, after the admin has explicitly approved the "
                            "preview returned by the first call. Omit or leave false on the first "
                            "attempt - nothing is written until confirm=true."
                        ),
                    },
                },
                "required": ["outcome"],
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
            client = anthropic.Anthropic(api_key=self.api_key)
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
            client = anthropic.Anthropic(api_key=self.api_key)
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
handicaps use a 90% allowance, with the lowest course handicap in the group playing to scratch and \
everyone else receiving 90% of the difference - so pairing two very low-handicap players together does \
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

PENDING MATCHES - several tools only count DECIDED (results-in) matches by default, and a short or \
empty answer from them does NOT mean no matches exist:
- get_matches defaults to status='decided'. Before ever telling an admin "there are no matches" for \
a year/player/filter, or before answering a general "what matches are there" / "what's happening in \
year X" question, call get_matches again with status='all' (or status='pending') to check for \
scheduled-but-undecided matches, and mention them explicitly if found (e.g. "no decided matches yet \
for 2026, but there are 4 pending: ..."). Never report "0 results" from the default decided-only call \
as evidence that nothing has been scheduled.
- get_player_course_performance and get_course_stats count every match recorded, including ones with \
no result yet (see their `Pending` field), unlike get_matches/get_player_stats which only count \
decided matches by default. When a course breakdown includes pending matches, say so explicitly (e.g. \
"2-0 completed at Druids Heath, 1 match still pending") rather than treating the raw match count as \
decided results - this matters for pairing decisions since only locked-in results are real signal.
- get_year_summary and get_team_points_by_day only tally decided results into their point totals; a \
year or day with only pending matches can show up looking like "0-0" or an unchanged/tied score rather \
than "not yet played." If a year's summary looks suspiciously empty or tied at 0, cross-check with \
get_matches (status='pending' or 'all') before reporting a final score or winner.

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

PARSING PASTED MATCH DATA - admins often paste real-world text (e.g. a WhatsApp export) instead of \
typing a clean "X & Y vs A & B" request. Handle this the same way, just with more inference required:
- Strip chat metadata like "[22/07, 20:56] Jeff Mealiff:" - these are timestamps/sender names, not \
match data. Don't treat them as player names or let them break up the names around them.
- A number sitting next to a player's name in pasted text (e.g. "Paul 18", "Matty 6") is very often \
just the sender's own rough note to themselves, NOT a handicap and NOT a score - disregard it unless \
the admin has explicitly told you what it means. Handicaps always come from create_matches's own \
lookup, never from pasted text; if it reports one missing, ask the admin for it rather than reusing a \
stray number you saw.
- When two or more chunks of pasted text each list one side's players for the day, with no explicit \
"vs" tying specific pairs together (e.g. one chunk is a flat list of names like "Jeff Andy Jordan \
Thomas Ralph Gavin Evans Andrew C" and another is several lines each naming two players), infer the \
match-up POSITIONALLY: split each side into consecutive pairs in the order given (Fourball) or one \
player at a time (Singles), then line the two sides up in the same order - 1st vs 1st, 2nd vs 2nd, 3rd \
vs 3rd, and so on. This applies equally to Fourball and Singles requests.
- Worked example: "Add these matches for day 2 2026 at druids glen [22/07, 20:56] Jeff Mealiff: Jeff \
Andy Jordan Thomas Ralph Gavin Evans Andrew C [22/07, 20:56] Conor McMeekin: Paul 18 Matty 6 / Conor 19 \
Ian 18 / Neville 14 Graham 21 / James 3 Jack 11" is 4 Fourball matches for year 2026, day 2, at druids \
glen. Drop the "[date, time] Sender:" headers and the trailing numbers, split Jeff's flat list into \
pairs in order (Jeff & Andy, Jordan & Thomas, Ralph & Gavin, Evans & Andrew C), split Conor's lines into \
pairs (Paul & Matty, Conor & Ian, Neville & Graham, James & Jack), and match them up positionally: \
Jeff & Andy vs Paul & Matty, Jordan & Thomas vs Conor & Ian, Ralph & Gavin vs Neville & Graham, \
Evans & Andrew C vs James & Jack.
- Because this involves real inference, lean on the confirm-preview safety net below rather than being \
certain up front: read the preview back clearly enough - who's paired with whom, which side plays which \
- that the admin would immediately notice if a pairing came out wrong.

CONFIRM BEFORE CREATING - create_matches NEVER creates anything on the first call. With confirm omitted/ \
false, it validates everything and returns 'confirm_required' with a full preview: the course's par/slope \
rating/course rating, and every proposed match's Blue vs Red players with their computed handicaps. Read \
that whole preview back to the admin - list each match's actual pairings and handicaps, don't just say \
"ready to create N matches" - and STOP: wait for their explicit go-ahead in a new message (e.g. "yes", \
"looks good", "go ahead"). Only after that do you call create_matches again with confirm=true and the \
exact same arguments. Never call it a second time with confirm=true in the same turn/response as the \
first call - the admin must see the preview and reply before you proceed. If the admin flags something \
wrong in the preview (a par/slope number, a pairing), fix the input (update_course, or correct the \
matches list) and preview again rather than forcing confirm=true through unchanged.

EDITING COURSES - update_course lets you fix a course's par, slope rating, or course rating directly from \
a request like "update Druids Glen to slope 132" or "the par for Druids Glen is actually 72" - only pass \
the field(s) the admin is actually changing, everything else stays as-is. Never guess a new value; if the \
admin flags something as wrong without saying what it should be, ask for the correct number.

RECORDING MATCH RESULTS - you can record a result directly with record_match_result, e.g. from "Jeff \
beat Conor 1up" or "Ian lost to Jordan 1 down". Work out who actually won before calling: always express \
the score as the WINNER's margin (e.g. "1 down" for the loser becomes score="1UP" attached to the winner \
via `outcome`), never leave it framed from the loser's side. If the admin didn't state a score, omit the \
`score` argument and ask them for it once the tool confirms it's needed; if they say they don't know or \
can't provide one, call again with score="Unknown". Halved matches are automatic - score always ends up \
"A/S", you don't need to supply one for outcome="half". If the admin didn't mention a year or day, omit \
them and let the tool search for the one pending match between the two named players; if it comes back \
'no_pending_match' or 'ambiguous_match', tell the admin what you found (or didn't) and ask them to \
confirm the match/year/day rather than guessing which one they mean or silently picking the first result. \
If the admin says a result was entered wrong and wants it undone (e.g. "clear that result", "they haven't \
actually played yet", "I recorded that incorrectly"), call record_match_result with outcome="clear" for \
the two players - it resets the match back to pending (no result, no score) and you don't need a `score`. \
For a FOURBALL result reported as a pairing vs pairing (e.g. "Jeff & Jordan beat Conor & Ian 2&1"), use \
fourball_side_a/fourball_side_b instead of player_a/player_b - never make two separate record_match_result \
calls with individual names for a fourball result, since the tool expects player_a/player_b to be \
opponents, not partners, so it won't find the match that way.

CONFIRM BEFORE RECORDING - record_match_result NEVER writes anything on the first call once it has found \
the one matching match. With confirm omitted/false, it returns 'confirm_required' with a preview of \
exactly what would change - the match's year/day/course/players and the proposed result/score (or "reset \
to pending" for outcome="clear") - and changes nothing. Read that back to the admin plainly (e.g. "I'll \
record Jeff beat Conor 1UP for the Year 2026 Day 2 match at Druids Glen - confirm?") and STOP: wait for \
their explicit go-ahead in a new message before calling record_match_result again with confirm=true and \
the same arguments. Never call it a second time with confirm=true in the same turn/response as the first \
call. This applies to every outcome, including outcome="clear".
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
        """One Claude API call, wrapping any failure as PairingSuggestionError. Streams the
        response rather than waiting on a single blocking call - bytes keep arriving as Claude
        generates, so a long tool-heavy or long-output turn (e.g. predicting a full slate of
        pending matches) doesn't sit silent long enough to trip a client-side read timeout."""
        logger.info("Calling Claude API (model=%s, turns=%d)", self.model, len(conversation))
        try:
            with client.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                tools=self.TOOLS,
                messages=conversation,
            ) as stream:
                response = stream.get_final_message()
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
            logger.warning(
                "Claude API error: %s | conversation shape: %s",
                e, _summarize_conversation_shape(conversation)
            )
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
            "update_course": self._tool_update_course,
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

    @staticmethod
    def _validate_status(status: Optional[str]) -> None:
        if status is not None and status not in VALID_MATCH_STATUSES:
            raise ValueError(
                f"invalid status {status!r}; must be one of {list(VALID_MATCH_STATUSES)} or omitted"
            )

    def _tool_get_matches(self, year: Optional[int] = None, match_type: Optional[str] = None,
                           player: Optional[str] = None, opponent: Optional[str] = None,
                           status: Optional[str] = None) -> str:
        self._validate_match_type(match_type)
        self._validate_status(status)
        status = status or "decided"
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
        if status == "decided":
            df = df[df['Result'].notna() & (df['Result'] != '')]
        elif status == "pending":
            df = df[df['Result'].isna() | (df['Result'] == '')]
        # status == "all": no filter

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
        if df is not None and not df.empty:
            df = df.copy()
            df['Pending'] = df['Matches'] - (df['Blue_Wins'] + df['Red_Wins'] + df['Halves'])
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

    @staticmethod
    def _clean_optional_str(value) -> Optional[str]:
        """Normalize a possibly-NaN/empty DataFrame cell to None for display (e.g. a match's
        current Result/Score before anything has been recorded). Plain `value or None` mishandles
        NaN, which is truthy in Python, so this checks pd.isna explicitly like _clean_handicap."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        return text or None

    @staticmethod
    def _claim_group_slot(name: str, available: list, used: list) -> bool:
        """Try to match `name` (case-insensitive exact-or-substring) against one not-yet-claimed
        entry in `available`, marking it used in place. Returns whether a slot was claimed - used
        by _group_side_of to confirm every member of a fourball pairing maps to a distinct player
        slot on the same side, rather than two names matching the same slot."""
        query = (name or "").strip().lower()
        if not query:
            return False
        for i, p_name in enumerate(available):
            if used[i] or not p_name:
                continue
            if p_name == query or query in p_name:
                used[i] = True
                return True
        return False

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

    def _tool_update_course(self, name: str, par: Optional[int] = None,
                             slope_rating: Optional[float] = None,
                             course_rating: Optional[float] = None) -> str:
        existing = self._resolve_course(name)
        if "error" in existing:
            return json.dumps(existing)

        if par is None and slope_rating is None and course_rating is None:
            return json.dumps({
                "error": "no changes given - specify par, slope_rating, and/or course_rating",
            })

        new_par = int(par) if par is not None else existing["par"]
        new_slope = float(slope_rating) if slope_rating is not None else existing["slope_rating"]
        new_rating = float(course_rating) if course_rating is not None else existing["course_rating"]

        ok = self.db_service.update_course(existing["name"], new_par, new_slope, new_rating)
        if not ok:
            return json.dumps({"error": f"failed to update course {existing['name']!r}"})
        return json.dumps({"course": self.db_service.get_course(existing["name"])}, default=_json_default)

    def _tool_create_matches(self, year: int, day: int, course: str, matches: Optional[list] = None,
                              confirm: bool = False) -> str:
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

        # Compute handicaps once up front (pure calculation, no writes) so the confirmation
        # preview and the actual write below operate on the exact same resolved plan.
        planned = []
        for entry in resolved_matches:
            blue, red = entry["blue"], entry["red"]
            if entry["match_type"] == "Singles":
                p1_hcp, p3_hcp = HandicapCalculator.calculate_match_handicaps(
                    match_type="Singles",
                    handicap_index_p1=blue[0]["handicap_index"], handicap_index_p2=None,
                    handicap_index_p3=red[0]["handicap_index"], handicap_index_p4=None,
                    slope_rating=course_info["slope_rating"],
                    course_rating=course_info["course_rating"], par=course_info["par"],
                )
                blue_hcp, red_hcp = [p1_hcp, None], [p3_hcp, None]
            else:
                p1_hcp, p2_hcp, p3_hcp, p4_hcp = HandicapCalculator.calculate_match_handicaps(
                    match_type="Fourball",
                    handicap_index_p1=blue[0]["handicap_index"], handicap_index_p2=blue[1]["handicap_index"],
                    handicap_index_p3=red[0]["handicap_index"], handicap_index_p4=red[1]["handicap_index"],
                    slope_rating=course_info["slope_rating"],
                    course_rating=course_info["course_rating"], par=course_info["par"],
                )
                blue_hcp, red_hcp = [p1_hcp, p2_hcp], [p3_hcp, p4_hcp]

            planned.append({
                "match_type": entry["match_type"],
                "blue": blue, "blue_hcp": blue_hcp, "red": red, "red_hcp": red_hcp,
                "blue_players": [{"name": p["name"], "handicap": h} for p, h in zip(blue, blue_hcp)],
                "red_players": [{"name": p["name"], "handicap": h} for p, h in zip(red, red_hcp)],
            })

        if not confirm:
            return json.dumps({
                "error": "confirm_required",
                "course": {
                    "name": course_info["name"], "par": course_info["par"],
                    "slope_rating": course_info["slope_rating"], "course_rating": course_info["course_rating"],
                },
                "matches": [
                    {
                        "match_type": p["match_type"],
                        "blue_players": p["blue_players"], "red_players": p["red_players"],
                    }
                    for p in planned
                ],
                "message": (
                    f"Nothing has been created yet. Read this preview back to the admin in full - "
                    f"{len(planned)} match(es) for Year {year}, Day {day} at {course_info['name']} "
                    f"(par {course_info['par']}, slope {course_info['slope_rating']}, course rating "
                    f"{course_info['course_rating']}), listing each match's Blue vs Red players and "
                    f"handicaps - and wait for their explicit go-ahead before calling create_matches "
                    f"again with confirm=true."
                ),
            }, default=_json_default)

        created = []
        for entry in planned:
            blue, blue_hcp, red, red_hcp = entry["blue"], entry["blue_hcp"], entry["red"], entry["red_hcp"]
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
                "blue_players": entry["blue_players"], "red_players": entry["red_players"],
            })

        self.data_service.invalidate_cache()
        return json.dumps({"created": created}, default=_json_default)

    def _tool_record_match_result(self, player_a: Optional[str] = None, player_b: Optional[str] = None,
                                   outcome: Optional[str] = None, score: Optional[str] = None,
                                   year: Optional[int] = None, day: Optional[int] = None,
                                   fourball_side_a: Optional[list] = None,
                                   fourball_side_b: Optional[list] = None,
                                   confirm: bool = False) -> str:
        if outcome not in ("player_a_won", "player_b_won", "half", "clear"):
            return json.dumps({"error": f"invalid outcome {outcome!r}"})

        has_fourball_sides = bool(fourball_side_a) or bool(fourball_side_b)
        has_individual = bool(player_a) or bool(player_b)
        if has_fourball_sides and has_individual:
            return json.dumps({
                "error": "mixed_player_args",
                "message": "Provide either player_a/player_b or fourball_side_a/fourball_side_b, not both.",
            })

        if has_fourball_sides:
            fourball_side_a = list(dict.fromkeys(fourball_side_a or []))
            fourball_side_b = list(dict.fromkeys(fourball_side_b or []))
            if len(fourball_side_a) != 2 or len(fourball_side_b) != 2:
                return json.dumps({
                    "error": "invalid_fourball_sides",
                    "message": "fourball_side_a and fourball_side_b must each list exactly 2 distinct players.",
                })
            display_a, display_b = " & ".join(fourball_side_a), " & ".join(fourball_side_b)
        elif has_individual:
            if not player_a or not player_b:
                return json.dumps({
                    "error": "missing_players",
                    "message": "Both player_a and player_b are required in Singles/individual mode.",
                })
            display_a, display_b = player_a, player_b
        else:
            return json.dumps({
                "error": "missing_players",
                "message": "Provide player_a/player_b, or fourball_side_a/fourball_side_b for a fourball result.",
            })

        df = self.data_service.df
        if df is None or df.empty:
            return json.dumps({
                "error": "no_pending_match", "player_a": display_a, "player_b": display_b,
                "message": "There are no matches recorded at all.",
            })

        is_clear = outcome == "clear"
        if is_clear:
            subset = df[df["Result"].notna() & (df["Result"] != "")]
        else:
            subset = df[df["Result"].isna() | (df["Result"] == "")]
        if year is not None:
            subset = subset[subset["Year"] == int(year)]
        if day is not None:
            subset = subset[subset["Day"] == int(day)]

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

        def _group_side_of(row, names):
            """Like _side_of, but requires every name in `names` to match a distinct player
            slot on the SAME side (used for fourball_side_a/fourball_side_b, so 2 partners
            reported together resolve to their shared team rather than 2 separate opponents)."""
            slots = {
                "Blue": [row.get("BluePlayer1"), row.get("BluePlayer2")],
                "Red": [row.get("RedPlayer1"), row.get("RedPlayer2")],
            }
            for side, players in slots.items():
                available = [str(p or "").strip().lower() for p in players]
                used = [False] * len(available)
                if not all(self._claim_group_slot(name, available, used) for name in names):
                    continue
                return side
            return None

        def _resolve_sides(row):
            if has_fourball_sides:
                return _group_side_of(row, fourball_side_a), _group_side_of(row, fourball_side_b)
            return _side_of(row, player_a), _side_of(row, player_b)

        candidates = []
        for _, row in subset.iterrows():
            side_a, side_b = _resolve_sides(row)
            if side_a and side_b and side_a != side_b:
                candidates.append(row)

        if not candidates:
            error_type = "no_result_to_clear" if is_clear else "no_pending_match"
            verb = "decided (non-pending)" if is_clear else "pending"
            return json.dumps({
                "error": error_type, "player_a": display_a, "player_b": display_b,
                "year": year, "day": day,
                "message": (
                    f"No {verb} match found where {display_a} and {display_b} are on opposite sides"
                    + (f" for {year} day {day}" if year and day else "")
                    + ". Ask the admin to confirm the year/day, or the player names."
                ),
            }, default=_json_default)

        if len(candidates) > 1:
            return json.dumps({
                "error": "ambiguous_match", "player_a": display_a, "player_b": display_b,
                "candidates": [
                    {
                        "year": int(row["Year"]), "day": int(row["Day"]), "match_number": int(row["MatchNumber"]),
                        "course": row["Course"], "match_type": row["MatchType"],
                    }
                    for row in candidates
                ],
                "message": "More than one matching match found - ask the admin which one (or for year/day).",
            }, default=_json_default)

        row = candidates[0]
        match_year, match_day, match_number = int(row["Year"]), int(row["Day"]), int(row["MatchNumber"])
        side_a, side_b = _resolve_sides(row)

        if is_clear:
            normalized_result, normalized_score = "", ""
        else:
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

        current_blue = " & ".join(n for n in (row.get("BluePlayer1"), row.get("BluePlayer2")) if n)
        current_red = " & ".join(n for n in (row.get("RedPlayer1"), row.get("RedPlayer2")) if n)

        if not confirm:
            proposed = (
                "reset to pending (no result, no score)" if is_clear
                else f"result={normalized_result!r}, score={normalized_score!r}"
            )
            return json.dumps({
                "error": "confirm_required",
                "match": {
                    "year": match_year, "day": match_day, "match_number": match_number,
                    "course": row["Course"], "match_type": row["MatchType"],
                    "blue_players": current_blue, "red_players": current_red,
                    "current_result": self._clean_optional_str(row.get("Result")),
                    "current_score": self._clean_optional_str(row.get("Score")),
                },
                "proposed": proposed,
                "message": (
                    f"Nothing has been changed yet. Read this back to the admin - Year {match_year} Day "
                    f"{match_day} at {row['Course']} ({current_blue} vs {current_red}) would be set to "
                    f"{proposed} - and wait for their explicit go-ahead before calling record_match_result "
                    f"again with confirm=true and the same arguments."
                ),
            }, default=_json_default)

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
