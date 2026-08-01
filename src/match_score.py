"""
Shared match-result score format used by both the manual Add/Edit Match UI
(src/app.py) and Captain Claude's match-creation/result-recording chat tools
(src/llm_pairing_service.py), so both paths enforce the same rule.

Allowed score formats: "1UP".."99UP", "1&1".."99&99", "A/S" (halved), "Unknown".
"""
import re
from typing import Optional

SCORE_PATTERN = re.compile(r'^\d{1,2}UP$|^\d{1,2}&\d{1,2}$|^A/S$|^Unknown$', re.IGNORECASE)

VALID_RESULTS = ('Blue', 'Red', 'Half', '')


def normalize_score(raw: Optional[str]) -> Optional[str]:
    """Trim/uppercase `raw` into canonical form ('1up' -> '1UP', 'a/s' -> 'A/S',
    'unknown' -> 'Unknown'), or return None if it doesn't match SCORE_PATTERN.
    An empty/blank input normalizes to '' (meaning "no score recorded")."""
    if raw is None:
        return ''
    text = raw.strip()
    if not text:
        return ''
    if not SCORE_PATTERN.match(text):
        return None
    if text.upper() == 'UNKNOWN':
        return 'Unknown'
    if text.upper() == 'A/S':
        return 'A/S'
    return text.upper()


def validate_result_score(result: Optional[str], score: Optional[str]) -> tuple[bool, str, str, str]:
    """Validate a (result, score) pair before it's persisted.

    Returns (ok, normalized_result, normalized_score, error_message).
    - Half always forces score to 'A/S', regardless of what was passed.
    - A blank result (clearing a match back to pending) always forces score blank too,
      regardless of what was passed - so clearing a result doesn't also require clearing
      whatever stray text was left in the score field.
    - A non-blank result (Blue/Red) requires a score matching SCORE_PATTERN,
      e.g. '3&2', '1UP', or 'Unknown'.
    """
    result = (result or '').strip()
    if result not in VALID_RESULTS:
        return False, result, score or '', (
            f"Invalid result {result!r}; must be one of 'Blue', 'Red', 'Half', or blank/pending."
        )

    if result == 'Half':
        return True, result, 'A/S', ''

    if not result:
        return True, result, '', ''

    normalized_score = normalize_score(score)
    if normalized_score is None:
        return False, result, score or '', (
            f"Invalid score {score!r}; allowed formats are e.g. '3&2', '1UP', 'A/S', or 'Unknown'."
        )

    if not normalized_score:
        return False, result, normalized_score, "A score is required once a result (Blue/Red) is set."

    return True, result, normalized_score, ''
