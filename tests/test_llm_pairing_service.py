import json
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


class FakeMessage:
    def __init__(self, text):
        self.content = [FakeTextBlock(text)]


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

    def _suggester(self, api_key='test-key'):
        return PairingSuggester(self.data_service, self.db_service, api_key=api_key, model='claude-test')

    # ---- input validation (no API call should happen) ----

    def test_missing_api_key_raises_configuration_error(self):
        suggester = PairingSuggester(self.data_service, self.db_service, api_key=None, model='claude-test')
        with self.assertRaises(PairingSuggestionError) as ctx:
            suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('ANTHROPIC_API_KEY', str(ctx.exception))

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

    # ---- response parsing/validation ----

    def test_successful_response_parsed_into_pairings(self):
        suggester = self._suggester()
        payload = json.dumps({
            "pairings": [{"players": ["Alice", "Bob"], "rationale": "Balanced skill and strong synergy."}]
        })
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage(payload)
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
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage(payload)
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(len(result['pairings']), 1)

    def test_invalid_response_triggers_retry_then_succeeds(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice", "Alice"], "rationale": "x"}]})
        good_payload = json.dumps({"pairings": [{"players": ["Alice", "Bob"], "rationale": "ok"}]})
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = [FakeMessage(bad_payload), FakeMessage(good_payload)]
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(fake_client.messages.create.call_count, 2)
        self.assertEqual(result['pairings'][0]['players'], ['Alice', 'Bob'])

    def test_persistently_invalid_response_raises_after_max_attempts(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice"], "rationale": "x"}]})
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage(bad_payload)
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertEqual(fake_client.messages.create.call_count, 2)

    def test_response_missing_a_player_is_rejected(self):
        suggester = self._suggester()
        bad_payload = json.dumps({"pairings": [{"players": ["Alice", "Carol"], "rationale": "x"}]})
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage(bad_payload)
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    def test_non_json_response_is_rejected(self):
        suggester = self._suggester()
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage("Sure, here are some thoughts on pairings...")
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    # ---- graceful failure on API errors ----

    def test_authentication_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        response = httpx.Response(401, request=request)
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = anthropic.AuthenticationError(
            'bad key', response=response, body=None
        )
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('API key', str(ctx.exception))

    def test_rate_limit_or_quota_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        response = httpx.Response(429, request=request)
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = anthropic.RateLimitError(
            'rate limited', response=response, body=None
        )
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])
        self.assertIn('rate limit', str(ctx.exception).lower())

    def test_generic_connection_error_is_wrapped_gracefully(self):
        suggester = self._suggester()
        request = httpx.Request('POST', 'https://api.anthropic.com/v1/messages')
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = anthropic.APIConnectionError(request=request)
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError):
                suggester.suggest_pairings('Blue', 2026, ['Alice', 'Bob'])

    # ---- continue_conversation: chat without a prior suggestion (lazy, token-free seed) ----

    def test_chat_without_prior_conversation_seeds_context_in_a_single_call(self):
        suggester = self._suggester()
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage("Sure, Alice and Bob look strong together.")
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="What do you think?"
            )
        self.assertEqual(fake_client.messages.create.call_count, 1)
        self.assertEqual(result['reply'], "Sure, Alice and Bob look strong together.")
        self.assertEqual(len(result['conversation']), 2)
        seed_content = result['conversation'][0]['content']
        self.assertIn('Alice', seed_content)
        self.assertIn('75.0% win rate', seed_content)
        self.assertIn('What do you think?', seed_content)
        self.assertEqual(result['conversation'][1], {'role': 'assistant', 'content': result['reply']})

    def test_chat_continues_an_existing_conversation_without_mutating_it(self):
        suggester = self._suggester()
        original_conversation = [
            {'role': 'user', 'content': 'original prompt'},
            {'role': 'assistant', 'content': 'original reply'},
        ]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = FakeMessage("Here's my feedback on that pairing.")
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            result = suggester.continue_conversation(
                'Blue', 2026, ['Alice', 'Bob'], conversation=original_conversation,
                user_message="What about pairing Alice with Carol instead?"
            )
        self.assertEqual(fake_client.messages.create.call_count, 1)
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
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = anthropic.RateLimitError(
            'rate limited', response=response, body=None
        )
        with patch('src.llm_pairing_service.anthropic.Anthropic', return_value=fake_client):
            with self.assertRaises(PairingSuggestionError) as ctx:
                suggester.continue_conversation('Blue', 2026, ['Alice', 'Bob'], conversation=None, user_message="Hi")
        self.assertIn('rate limit', str(ctx.exception).lower())


if __name__ == '__main__':
    unittest.main()
