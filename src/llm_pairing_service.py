"""
LLM-based fourball partner suggestions.

Given a team's available players for a day, asks Claude to split them into
pairs using each player's individual Fourball record, historical partner
synergy, and handicaps. Advisory only - callers still create matches
manually via the existing Add Match flow.
"""
import json
import logging
import os
import re
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
MAX_ATTEMPTS = 2


class PairingSuggestionError(Exception):
    """Raised when pairing suggestions can't be produced; message is safe to show in the UI."""


class PairingSuggester:
    """Uses the Claude API to suggest fourball partnerships for one team."""

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
        """Continue a chat about pairings; return {'reply': str, 'conversation': [...]}.

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
The admin has not generated a formatted pairing list yet. Answer their question or discuss pairing \
ideas conversationally in plain text, using the data above. They can click "Suggest Pairings" \
separately if they want a full formatted list.

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

        return f"""You are helping a golf trip organizer with fourball (better-ball) partnerships for {year}.

Team: {team}
Available players ({len(players)}): {', '.join(players)}

Fourball background: in fourball match play, each pair's better score counts on each hole. Playing \
handicaps use an 85% allowance, with the lowest course handicap in the group playing to scratch and \
everyone else receiving 85% of the difference - so pairing two very low-handicap players together does \
not by itself create an unfair advantage within their own pair.

Individual Fourball performance to date:
{player_stats_text}

Historical partner synergy (Fourball matches only):
{partner_history_text}
"""

    def _build_suggestion_prompt(self, team: str, year: int, players: list[str]) -> str:
        context = self._build_context_block(team, year, players)
        return f"""{context}
Task: produce the best possible set of {len(players) // 2} pairings for {team} from these {len(players)} \
players, using their individual records, historical synergy as partners, and handicaps to judge how well \
each pair is likely to perform. Every player must appear in exactly one pair.

Respond with ONLY valid JSON (no markdown fences, no extra text) in this exact shape:
{{"pairings": [{{"players": ["PlayerA", "PlayerB"], "rationale": "one or two sentence justification"}}]}}
"""

    def _send(self, client, conversation: list[dict]) -> str:
        """Call the Anthropic API and return the reply text, wrapping any failure as PairingSuggestionError."""
        logger.info("Calling Claude API (model=%s, turns=%d)", self.model, len(conversation))
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=1500,
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
