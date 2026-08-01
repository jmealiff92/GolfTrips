import json
import os
import unittest
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pandas as pd

from src.llm_pairing_service import PairingSuggester, PairingSuggestionError


class FakeTextBlock:
    def __init__(self, text):
        self.type = 'text'
        self.text = text


class FakeNonTextBlock:
    def __init__(self, block_type='thinking'):
        self.type = block_type


class FakeToolUseBlock:
    def __init__(self, tool_id, name, input_):
        self.type = 'tool_use'
        self.id = tool_id
        self.name = name
        self.input = input_


class FakeMessage:
    def __init__(self, text=None, stop_reason='end_turn', stop_details=None, content=None):
        self.content = content if content is not None else ([FakeTextBlock(text)] if text is not None else [])
        self.stop_reason = stop_reason
        self.stop_details = stop_details


def _stream_client(final_messages=None, error=None):
    """Build a MagicMock Anthropic client whose messages.stream(...) context manager stands in
    for PairingSuggester._call_api's streaming call. get_final_message() on the entered context
    yields `final_messages` - a single FakeMessage repeated on every call, or a list consumed one
    per call (mirroring the old .create.side_effect list pattern). Pass `error` instead to make
    messages.stream(...) itself raise, standing in for an API error surfaced before/during
    streaming."""
    fake_client = MagicMock()
    if error is not None:
        fake_client.messages.stream.side_effect = error
        return fake_client
    entered = fake_client.messages.stream.return_value.__enter__.return_value
    if isinstance(final_messages, list):
        entered.get_final_message.side_effect = final_messages
    else:
        entered.get_final_message.return_value = final_messages
    return fake_client


class TestPairingSuggester(unittest.TestCase):
    """Unit tests for PairingSuggester - no real network calls, the Anthropic client is mocked."""

    def setUp(self):
        self.data_service = MagicMock()
        self.db_service = MagicMock()

        self.data_service.get_player_performance_all_players.return_value = pd.DataFrame({
            'Player': ['Alice', 'Bob'],
            'Matches': [4, 4],
            'Wins': [3, 1],
            'Losses': [1, 3],
            'Halves': [0, 0],
            'Points': [3, 1],
            'Win %': [75.0, 25.0],
            'PPG': [0.75, 0.25],
        })
        self.data_service.get_partner_performace.return_value = pd.DataFrame({
            'partnership': ['Alice & Bob'],
            'Matches': [2],
            'Wins': [2],
            'Halves': [0],
            'Losses': [0],
            'Points': [2.0],
            'PPG': [1.0],
        })
        handicaps = {'Alice': 5.0, 'Bob': 12.0, 'Carol': 8.0}
        self.db_service.get_player_handicap.side_effect = lambda name, year: handicaps.get(name)
        self.db_service.get_team_assignments_by_year.return_value = [
            {'name': 'Alice', 'team': 'Blue'},
            {'name': 'Bob', 'team': 'Blue'},
            {'name': 'Carol', 'team': 'Red'},
        ]

    def _suggester(self, api_key='test-key'):
        return PairingSuggester(self.data_service, self.db_service, api_key=api_key, model='claude-test')

    # ---- input validation (no API call should happen) ----

    def test_missing_api_key_raises_configuration_error(self):
        suggester = PairingSuggester(self.data_service, self.db_service, api_key=None, model='claude-test')
        with self.assertRaises(PairingSuggestionError) as ctx:
            suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('ANTHROPIC_API_KEY', str(ctx.exception))

    def test_api_key_resolves_fresh_from_environment_without_restart(self):
        """A key added to the environment after construction should take effect immediately,
        so a Render env var change doesn't require restarting the process to work."""
        suggester = PairingSuggester(self.data_service, self.db_service, api_key=None, model='claude-test')
        with patch.dict('os.environ', {}, clear=False):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            self.assertIsNone(suggester.api_key)
            os.environ['ANTHROPIC_API_KEY'] = 'sk-late-arriving-key'
            self.assertEqual(suggester.api_key, 'sk-late-arriving-key')
            os.environ.pop('ANTHROPIC_API_KEY', None)

    def test_explicit_api_key_override_ignores_environment(self):
        suggester = self._suggester(api_key='explicit-key')
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'env-key'}):
            self.assertEqual(suggester.api_key, 'explicit-key')

    def test_odd_player_count_rejected_before_api_call(self):
        suggester = self._suggester()
        with patch('src.llm_pairing_service.anthropic.Anthropic') as mock_client_cls:
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob', 'Carol'])
            mock_client_cls.assert_not_called()

    def test_too_few_players_rejected_before_api_call(self):
        suggester = self._suggester()
        with patch('src.llm_pairing_service.anthropic.Anthropic') as mock_client_cls:
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice'])
            mock_client_cls.assert_not_called()

    # ---- prompt construction ----

    def test_prompt_includes_player_stats_and_partner_history(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('Alice', prompt)
        self.assertIn('Bob', prompt)
        self.assertIn('75.0% win rate', prompt)
        self.assertIn('handicap index 5.0', prompt)
        self.assertIn('Alice & Bob', prompt)
        self.assertIn('2 matches together', prompt)

    def test_prompt_includes_margin_weighting_guidance(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('Match-by-match Fourball results', prompt)
        self.assertIn('not just the raw win/loss tally', prompt)

    def test_prompt_scopes_fourball_context_to_pairings_and_tells_claude_to_widen_for_general_questions(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('NOT the player\'s overall record', prompt)
        self.assertIn('no match_type argument', prompt)

    def test_get_player_stats_tool_schema_documents_all_match_types_default(self):
        suggester = self._suggester()
        tool = next(t for t in suggester.TOOLS if t['name'] == 'get_player_stats')
        self.assertIn('all match types', tool['description'])

    def test_get_player_course_performance_tool_schema_documents_pending_field(self):
        suggester = self._suggester()
        tool = next(t for t in suggester.TOOLS if t['name'] == 'get_player_course_performance')
        self.assertIn('Pending', tool['description'])

    def test_prompt_instructs_flagging_pending_matches(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('PENDING MATCHES', prompt)
        self.assertIn('Pending', prompt)

    def test_prompt_warns_against_concluding_no_matches_from_decided_only_result(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('does NOT mean no matches exist', prompt)
        self.assertIn("status='all'", prompt)

    def test_prompt_instructs_parsing_messy_pasted_match_data(self):
        suggester = self._suggester()
        prompt = suggester._build_suggestion_prompt('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('PARSING PASTED MATCH DATA', prompt)
        self.assertIn('Jeff Mealiff', prompt)
        self.assertIn('POSITIONALLY', prompt)
        self.assertIn('NOT a handicap and NOT a score', prompt)

    # ---- response parsing/validation ----

    def test_successful_response_parsed_into_pairings(self):
        suggester = self._suggester()
        payload = json.dumps({
            "pairings": [{"players": ["Alice", "Bob"], "rationale": "Balanced skill and strong synergy."}]
        })
        fake_client = _stream_client(FakeMessage(payload))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(result['team'], 'Blue')
        self.assertEqual(
            result['pairings'],
            [{'players': ['Alice', 'Bob'], 'rationale': 'Balanced skill and strong synergy.'}]
        )
        self.assertEqual(result['conversation'][-1], {'role': 'assistant', 'content': payload})

    def test_response_wrapped_in_markdown_fence_is_parsed(self):
        suggester = self._suggester()
        payload = "```json\n" + json.dumps({
            "pairings": [{"players": ["Alice", "Bob"], "rationale": "Good fit."}]
        }) + "\n```"
        fake_client = _stream_client(FakeMessage(payload))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(len(result['pairings']), 1)

    def test_invalid_response_triggers_retry_then_succeeds(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice", "Alice"], "rationale": "x"}]})
        good_payload = json.dumps({"pairings": [{"players": ["Alice", "Bob"], "rationale": "ok"}]})
        fake_client = _stream_client([FakeMessage(bad_payload), FakeMessage(good_payload)])
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(fake_client.messages.stream.call_count, 2)
        self.assertEqual(result['pairings'][0]['players'], ['Alice', 'Bob'])

    def test_persistently_invalid_response_raises_after_max_attempts(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice"], "rationale": "x"}]})
        fake_client = _stream_client(FakeMessage(bad_payload))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(fake_client.messages.stream.call_count, 2)

    def test_response_missing_a_player_is_rejected(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice", "Carol"], "rationale": "x"}]})
        fake_client = _stream_client(FakeMessage(bad_payload))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    def test_non_json_response_is_rejected(self):
        suggester = self._suggester()
        fake_client = _stream_client(FakeMessage("Sure, here are some thoughts on pairings..."))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    # ---- graceful failure on API errors ----

    def test_authentication_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        response = httpx.Response(401, request=request)
        fake_client = _stream_client(error=anthropic.AuthenticationError(
            'bad key', response=response, body=None
        ))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('API key', str(ctx.exception))

    def test_rate_limit_or_quota_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        response = httpx.Response(429, request=request)
        fake_client = _stream_client(error=anthropic.RateLimitError(
            'rate limited', response=response, body=None
        ))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('rate limit', str(ctx.exception).lower())

    def test_generic_connection_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        fake_client = _stream_client(error=anthropic.APIConnectionError(request=request))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    def test_timeout_error_is_wrapped_gracefully_and_distinctly(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        fake_client = _stream_client(error=anthropic.APITimeoutError(request=request))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('timed out', str(ctx.exception).lower())

    def test_empty_reply_with_refusal_stop_reason_raises_visible_error(self):
        suggester = self._suggester()
        fake_client = _stream_client(FakeMessage(
            content=[FakeNonTextBlock('refusal')], stop_reason='refusal'
        ))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('refusal', str(ctx.exception).lower())

    # ---- continue_conversation: chat without a prior suggestion (lazy, token-free seed) ----

    def test_chat_without_prior_conversation_seeds_context_in_a_single_call(self):
        suggester = self._suggester()
        fake_client = _stream_client(FakeMessage("Sure, Alice and Bob look strong together."))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="What do you think?"
            )
        self.assertEqual(fake_client.messages.stream.call_count, 1)
        self.assertEqual(result['reply'], "Sure, Alice and Bob look strong together.")
        self.assertEqual(len(result['conversation']), 2)
        seed_content = result['conversation'][0]['content']
        self.assertIn('Alice', seed_content)
        self.assertIn('75.0% win rate', seed_content)
        self.assertIn('What do you think?', seed_content)
        self.assertEqual(result['conversation'][1], {'role': 'assistant', 'content': result['reply']})

    def test_chat_seed_covers_both_teams_full_roster_not_just_checked_players(self):
        """Chat context should be built from the whole year's roster (both teams), not just the
        subset of players currently checked in the pairing UI - Carol (Red team, unchecked) must
        still show up so open-ended questions aren't scoped to one team."""
        suggester = self._suggester()
        fake_client = _stream_client(FakeMessage("Here's the trip so far."))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="How's the trip going?"
            )
        seed_content = result['conversation'][0]['content']
        self.assertIn('Blue team (2): Alice, Bob', seed_content)
        self.assertIn('Red team (1): Carol', seed_content)
        self.assertIn('Carol', seed_content)
        self.assertIn('checked as available in the pairing tool', seed_content)

    def test_chat_continues_an_existing_conversation_without_mutating_it(self):
        suggester = self._suggester()
        original_conversation = [
            {'role': 'user', 'content': 'original prompt'},
            {'role': 'assistant', 'content': 'original reply'},
        ]
        fake_client = _stream_client(FakeMessage("Here's my feedback on that pairing."))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=original_conversation,
                user_message="What about pairing Alice with Carol instead?"
            )
        self.assertEqual(fake_client.messages.stream.call_count, 1)
        self.assertEqual(len(original_conversation), 2)  # caller's list untouched
        self.assertEqual(len(result['conversation']), 4)
        self.assertEqual(result['conversation'][-1], {'role': 'assistant', 'content': result['reply']})

    def test_chat_missing_api_key_raises_configuration_error(self):
        suggester = PairingSuggester(self.data_service, self.db_service, api_key=None, model='claude-test')
        with self.assertRaises(PairingSuggestionError) as ctx:
            suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Hi")
        self.assertIn('ANTHROPIC_API_KEY', str(ctx.exception))

    def test_chat_empty_message_rejected_before_api_call(self):
        suggester = self._suggester()
        with patch('src.llm_pairing_service.anthropic.Anthropic') as mock_client_cls:
            with self.assertRaises(PairingSuggestionError):
                suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="   ")
            mock_client_cls.assert_not_called()

    def test_chat_rate_limit_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        response = httpx.Response(429, request=request)
        fake_client = _stream_client(error=anthropic.RateLimitError(
            'rate limited', response=response, body=None
        ))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Hi")
        self.assertIn('rate limit', str(ctx.exception).lower())

    def test_chat_timeout_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        fake_client = _stream_client(error=anthropic.APITimeoutError(request=request))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Hi")
        self.assertIn('timed out', str(ctx.exception).lower())

    def test_chat_empty_reply_raises_visible_error(self):
        suggester = self._suggester()
        fake_client = _stream_client(FakeMessage(content=[], stop_reason='max_tokens'))
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Hi")
        self.assertIn('empty response', str(ctx.exception).lower())


class TestPairingSuggesterTools(unittest.TestCase):
    """Tests for the Claude tool-calling loop and the individual tool implementations that back
    open-ended stats questions (match tightness, opponent strength, course/head-to-head records)."""

    def setUp(self):
        self.data_service = MagicMock()
        self.db_service = MagicMock()

        self.data_service.df = pd.DataFrame({
            'Year': [2026, 2026, 2027],
            'Day': [1, 2, 1],
            'MatchNumber': [1, 1, 1],
            'Course': ['Course A', 'Course B', 'Course C'],
            'MatchType': ['Singles', 'Fourball', 'Singles'],
            'BluePlayer1': ['Alice', 'Alice', 'Eve'],
            'BluePlayer2': [None, 'Dave', None],
            'RedPlayer1': ['Bob', 'Bob', 'Frank'],
            'RedPlayer2': [None, 'Carol', None],
            'Result': ['Blue', 'Half', ''],
            'Score': ['3&2', 'AS', ''],
        })
        self.data_service.get_player_performance_all_players.return_value = pd.DataFrame({
            'Player': ['Alice'],
            'Matches': [4], 'Wins': [3], 'Losses': [1], 'Halves': [0],
            'Points': [3], 'Win %': [75.0], 'PPG': [0.75],
        })
        self.data_service.get_head_to_head_stats.return_value = {
            'matches': 2, 'player1_wins': 1, 'player2_wins': 0, 'halves': 1,
        }
        self.data_service.get_partner_performace.return_value = pd.DataFrame({
            'partnership': ['Alice & Dave'], 'Matches': [1], 'Wins': [0],
            'Halves': [1], 'Losses': [0], 'Points': [0.5], 'PPG': [0.5],
        })
        self.data_service.get_course_statistics.return_value = pd.DataFrame({
            'Course': ['Course A'], 'Matches': [1], 'Blue_Wins': [1], 'Red_Wins': [0], 'Halves': [0],
        })
        self.data_service.get_player_course_performance.return_value = pd.DataFrame({
            'Course': ['Course A'], 'Matches': [1], 'Wins': [1], 'Halves': [0], 'Losses': [0],
            'Points': [1.0], 'PPG': [1.0],
        })
        self.db_service.get_player_handicap.return_value = 5.0

    def _suggester(self):
        return PairingSuggester(self.data_service, self.db_service, api_key='test-key', model='claude-test')

    # ---- the tool-calling loop ----

    def test_tool_use_round_trip_returns_final_text_and_feeds_result_back(self):
        suggester = self._suggester()
        tool_call = FakeMessage(
            content=[FakeToolUseBlock('tool_1', 'get_matches', {'player': 'Alice'})],
            stop_reason='tool_use',
        )
        final = FakeMessage("Alice won 3&2 on day 1 - not especially tight.")
        fake_client = _stream_client([tool_call, final])

        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Was Alice's win tight?"
            )

        self.assertEqual(fake_client.messages.stream.call_count, 2)
        self.assertEqual(result['reply'], "Alice won 3&2 on day 1 - not especially tight.")

        tool_result_turn = result['conversation'][-2]
        self.assertEqual(tool_result_turn['role'], 'user')
        tool_result_content = tool_result_turn['content'][0]['content']
        self.assertIn('3&2', tool_result_content)
        self.assertIn('Alice', tool_result_content)

    def test_unrecognized_tool_reports_error_without_crashing_the_loop(self):
        suggester = self._suggester()
        tool_call = FakeMessage(
            content=[FakeToolUseBlock('tool_1', 'not_a_real_tool', {})], stop_reason='tool_use',
        )
        final = FakeMessage("Sorry, I can't look that up.")
        fake_client = _stream_client([tool_call, final])

        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="What's the weather?"
            )

        self.assertEqual(result['reply'], "Sorry, I can't look that up.")
        tool_result_content = result['conversation'][-2]['content'][0]['content']
        self.assertIn('unknown tool', tool_result_content)

    def test_tool_loop_gives_up_after_max_iterations(self):
        suggester = self._suggester()
        looping_call = FakeMessage(
            content=[FakeToolUseBlock('tool_1', 'get_course_stats', {})], stop_reason='tool_use',
        )
        fake_client = _stream_client(looping_call)

        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.continue_conversation(
                    'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Loop forever?"
                )
        self.assertIn('tool call', str(ctx.exception).lower())

    # ---- individual tool implementations ----

    def test_get_matches_filters_by_player_and_reports_score_margin(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'player': 'Alice'}))
        self.assertEqual(len(payload['matches']), 2)
        self.assertEqual(payload['matches'][0]['Score'], '3&2')

    def test_get_matches_filters_by_year_and_match_type(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'year': 2026, 'match_type': 'Fourball'}))
        self.assertEqual(len(payload['matches']), 1)
        self.assertEqual(payload['matches'][0]['MatchType'], 'Fourball')

    def test_get_player_stats_includes_record_and_handicap(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_player_stats', {'player': 'Alice', 'year': 2026}))
        self.assertEqual(payload['stats']['Wins'], 3)
        self.assertEqual(payload['handicap_index'], 5.0)

    def test_get_player_stats_defaults_to_all_match_types(self):
        suggester = self._suggester()
        suggester._execute_tool('get_player_stats', {'player': 'Alice'})
        self.data_service.get_player_performance_all_players.assert_called_once_with(None)

    def test_get_player_stats_respects_explicit_match_type(self):
        suggester = self._suggester()
        suggester._execute_tool('get_player_stats', {'player': 'Alice', 'match_type': 'Singles'})
        self.data_service.get_player_performance_all_players.assert_called_once_with('Singles')

    def test_get_matches_rejects_invalid_match_type(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'match_type': 'Single'}))
        self.assertIn('error', payload)
        self.assertIn('Single', payload['error'])

    def test_get_matches_default_status_excludes_pending(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {}))
        self.assertEqual(len(payload['matches']), 2)
        self.assertTrue(all(m['Result'] for m in payload['matches']))

    def test_get_matches_status_pending_returns_only_undecided(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'status': 'pending'}))
        self.assertEqual(len(payload['matches']), 1)
        self.assertEqual(payload['matches'][0]['Year'], 2027)
        self.assertEqual(payload['matches'][0]['Result'], '')
        self.assertEqual(payload['matches'][0]['Score'], '')

    def test_get_matches_status_all_returns_everything(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'status': 'all'}))
        self.assertEqual(len(payload['matches']), 3)

    def test_get_matches_pending_only_year_not_reported_as_no_matches(self):
        # Direct repro of the bug: a year with ONLY pending matches must not look empty when
        # explicitly asked for pending/all matches, even though the decided-only default is empty.
        suggester = self._suggester()
        default_payload = json.loads(suggester._execute_tool('get_matches', {'year': 2027}))
        self.assertEqual(default_payload['matches'], [])

        all_payload = json.loads(suggester._execute_tool('get_matches', {'year': 2027, 'status': 'all'}))
        self.assertEqual(len(all_payload['matches']), 1)
        self.assertEqual(all_payload['matches'][0]['Year'], 2027)

        pending_payload = json.loads(suggester._execute_tool('get_matches', {'year': 2027, 'status': 'pending'}))
        self.assertEqual(len(pending_payload['matches']), 1)

    def test_get_matches_year_with_no_matches_at_all_stays_empty(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'year': 2099, 'status': 'all'}))
        self.assertEqual(payload['matches'], [])

    def test_get_matches_rejects_invalid_status(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_matches', {'status': 'bogus'}))
        self.assertIn('error', payload)
        self.assertIn('bogus', payload['error'])

    def test_get_matches_tool_schema_documents_status_parameter(self):
        suggester = self._suggester()
        tool = next(t for t in suggester.TOOLS if t['name'] == 'get_matches')
        self.assertIn('status', tool['input_schema']['properties'])
        self.assertIn('pending', tool['input_schema']['properties']['status']['description'])

    def test_get_course_stats_tool_schema_documents_pending_field(self):
        suggester = self._suggester()
        tool = next(t for t in suggester.TOOLS if t['name'] == 'get_course_stats')
        self.assertIn('Pending', tool['description'])

    def test_get_player_stats_rejects_invalid_match_type(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_player_stats', {'player': 'Alice', 'match_type': 'single'}))
        self.assertIn('error', payload)
        self.data_service.get_player_performance_all_players.assert_not_called()

    def test_get_player_stats_unknown_player_returns_no_stats(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_player_stats', {'player': 'Zed'}))
        self.assertIsNone(payload['stats'])

    def test_get_head_to_head_dispatches_to_data_service(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_head_to_head', {'player1': 'Alice', 'player2': 'Bob'}))
        self.assertEqual(payload['matches'], 2)
        self.data_service.get_head_to_head_stats.assert_called_once_with('Alice', 'Bob')

    def test_get_partner_history_dispatches_to_data_service(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_partner_history', {'player': 'Alice'}))
        self.assertEqual(payload['partnerships'][0]['partnership'], 'Alice & Dave')

    def test_get_course_stats_returns_course_records(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_course_stats', {}))
        self.assertEqual(payload['courses'][0]['Course'], 'Course A')

    def test_get_player_course_performance_dispatches_to_data_service(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('get_player_course_performance', {'player': 'Alice'}))
        self.assertEqual(payload['courses'][0]['Wins'], 1)
        self.assertEqual(payload['courses'][0]['Pending'], 0)

    def test_get_player_course_performance_flags_pending_matches(self):
        suggester = self._suggester()
        self.data_service.get_player_course_performance.return_value = pd.DataFrame({
            'Course': ['Druids Heath'], 'Matches': [3], 'Wins': [2], 'Halves': [0], 'Losses': [0],
            'Points': [2.0], 'PPG': [0.67],
        })
        payload = json.loads(suggester._execute_tool('get_player_course_performance', {'player': 'Jeff'}))
        self.assertEqual(payload['courses'][0]['Pending'], 1)

    def test_unknown_tool_name_returns_json_error(self):
        suggester = self._suggester()
        payload = json.loads(suggester._execute_tool('nonexistent', {}))
        self.assertIn('error', payload)

    # ---- match history / margin context fed into pairing decisions ----

    def test_format_match_history_reports_score_margin_and_outcome(self):
        suggester = self._suggester()
        text = suggester._format_match_history(['Alice', 'Bob'])
        self.assertIn('Alice', text)
        self.assertIn('Bob', text)
        self.assertIn('halved AS', text)

    def test_format_match_history_respects_match_type_and_reports_win_margin(self):
        suggester = self._suggester()
        text = suggester._format_match_history(['Alice'], match_type='Singles')
        self.assertIn('won 3&2', text)

    def test_format_match_history_player_with_no_history(self):
        suggester = self._suggester()
        text = suggester._format_match_history(['Zed'])
        self.assertIn('no Fourball match history yet', text)

    def test_context_block_includes_match_history_and_margin_guidance(self):
        suggester = self._suggester()
        context = suggester._build_context_block('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('Match-by-match Fourball results', context)
        self.assertIn('halved AS', context)
        self.assertIn('not just the raw win/loss tally', context)


if __name__ == '__main__':
    unittest.main()
