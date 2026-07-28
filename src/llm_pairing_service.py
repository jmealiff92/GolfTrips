"""
LLM-based fourball partner suggestions and open-ended trip stats chat ("Captain Claude").

Given a team's available players for a day, asks Claude to split them into
pairs using each player's individual Fourball record, historical partner
synergy, and handicaps. Advisory only - callers still create matches
manually via the existing Add Match flow.

Beyond pairing suggestions, the chat also gives Claude tool access to query
match-by-match results (including score margins, to judge how tight a match
was), head-to-head records, partner history, and course performance, so it
can answer open-ended stats questions rather than only what's pre-baked into
the prompt context.
"""
import json
import logging
import os
import re
from typing import Optional

import anthropic

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


class PairingSuggester:
    """Uses the Claude API to suggest fourball partnerships and answer stats questions for one team."""

    TOOLS = [
        {
            "name": "get_matches",
            "description": (
                "Look up individual match results, including each match's score/margin "
                "(e.g. '3&2', '1 up', 'AS') so you can judge how tight or lopsided it was, and "
                "exactly who played whom. Filter by any combination of year, match type, or player."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "Trip year, e.g. 2026"},
                    "match_type": {
                        "type": "string", "enum": ["Singles", "Fourball"],
                        "description": "Omit to include both Singles and Fourball matches.",
                    },
                    "player": {"type": "string", "description": "Only matches this player appeared in"},
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
                        "type": "string", "enum": ["Singles", "Fourball"],
                        "description": "Omit for the player's combined record across all match types.",
                    },
                    "year": {"type": "integer", "description": "Year to look up the handicap index for"},
                },
                "required": ["player"],
            },
        },
        {
            "name": "get_head_to_head",
            "description": "Head-to-head record between two specific players across every match they've played against each other.",
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
            "description": "One player's win/loss/half record broken down by course.",
            "input_schema": {
                "type": "object",
                "properties": {"player": {"type": "string"}},
                "required": ["player"],
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

        If `conversation` is empty (no suggestion has been generated yet), the stats/handicap
        context is built locally at no API cost and bundled into this same request alongside the
        user's message, rather than spent on a separate priming call.
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
            players = list(dict.fromkeys(available_players or []))
            context = self._build_context_block(team, year, players)
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
        player_stats_text = self._format_player_stats(players, year)
        partner_history_text = self._format_partner_history(players)
        match_history_text = self._format_match_history(players)

        return f"""You are Captain Claude, helping a golf trip organizer with fourball (better-ball) \
partnerships for {year} and with any other questions they have about the trip's matches, players, and \
courses.

Team: {team}
Available players ({len(players)}): {', '.join(players)}

Fourball background: in fourball match play, each pair's better score counts on each hole. Playing \
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
between two players, partner history, and course-by-course performance. Use them whenever a question \
needs more detail than the summary above.

SCOPE - the Fourball-only data above is for judging pairings. It is NOT the player's overall record. \
If the admin asks a general question about a player (their record, how good they are, how they've been \
playing, etc.) without specifying a match type, treat that as spanning ALL match types: call \
get_player_stats or get_matches with no match_type argument to get their combined Singles + Fourball \
picture, don't just reuse the Fourball-only summary above. Only scope an answer to one match type when \
the admin's question is specifically about pairings, Fourball, or Singles.
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

    def _tool_get_matches(self, year: Optional[int] = None, match_type: Optional[str] = None,
                           player: Optional[str] = None) -> str:
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
        df = df[df['Result'].notna() & (df['Result'] != '')]

        cols = ['Year', 'Day', 'MatchNumber', 'Course', 'MatchType',
                'BluePlayer1', 'BluePlayer2', 'RedPlayer1', 'RedPlayer2', 'Result', 'Score']
        df = df[cols].sort_values(by=['Year', 'Day', 'MatchNumber'])
        return json.dumps({"matches": _df_records(df)}, default=_json_default)

    def _tool_get_player_stats(self, player: str, match_type: Optional[str] = None,
                                year: Optional[int] = None) -> str:
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
        return json.dumps({"player": player, "courses": _df_records(df)}, default=_json_default)

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
