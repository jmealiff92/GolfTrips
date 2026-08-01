"""
Tests for Captain Claude's write actions: creating matches and recording match
results (src/llm_pairing_service.py's create_matches/create_course/
record_match_result tools), plus the shared score-format validation in
src/match_score.py that both those tools and the manual Add/Edit Match UI use.
"""
import json
import os
import tempfile
import unittest

from src.db_service import DatabaseService
from src.data_service import DataService
from src.handicap_calculator import HandicapCalculator
from src.llm_pairing_service import PairingSuggester
from src.match_score import normalize_score, validate_result_score


class TestMatchScore(unittest.TestCase):
    def test_valid_formats_normalize(self):
        self.assertEqual(normalize_score('1up'), '1UP')
        self.assertEqual(normalize_score('2up'), '2UP')
        self.assertEqual(normalize_score('3&2'), '3&2')
        self.assertEqual(normalize_score('a/s'), 'A/S')
        self.assertEqual(normalize_score('unknown'), 'Unknown')
        self.assertEqual(normalize_score('10&8'), '10&8')

    def test_invalid_formats_rejected(self):
        for bad in ['1 down', '3-2', 'won', 'AS', '1 up', '']:
            if bad == '':
                self.assertEqual(normalize_score(bad), '')
            else:
                self.assertIsNone(normalize_score(bad), f"{bad!r} should be invalid")

    def test_up_margin_capped_at_two(self):
        # A match that reaches the 18th hole can only finish A/S, 1UP, or 2UP - anything
        # more decisive would have closed out early and been recorded as "X&Y" instead.
        for bad in ['3UP', '4UP', '10UP', '0UP']:
            self.assertIsNone(normalize_score(bad), f"{bad!r} should be invalid")

    def test_half_forces_a_s(self):
        ok, result, score, err = validate_result_score('Half', 'anything')
        self.assertTrue(ok)
        self.assertEqual(result, 'Half')
        self.assertEqual(score, 'A/S')
        self.assertEqual(err, '')

    def test_half_with_no_score_still_a_s(self):
        ok, result, score, err = validate_result_score('Half', None)
        self.assertTrue(ok)
        self.assertEqual(score, 'A/S')

    def test_blank_result_blank_score_ok(self):
        ok, result, score, err = validate_result_score('', '')
        self.assertTrue(ok)
        self.assertEqual(result, '')
        self.assertEqual(score, '')

    def test_blank_result_auto_clears_stray_score(self):
        # Clearing a result back to pending should silently drop any leftover score text,
        # the same way Half forces the score to 'A/S' regardless of what was passed.
        ok, result, score, err = validate_result_score('', '1UP')
        self.assertTrue(ok)
        self.assertEqual(result, '')
        self.assertEqual(score, '')

    def test_decided_result_requires_score(self):
        ok, result, score, err = validate_result_score('Blue', '')
        self.assertFalse(ok)
        self.assertIn('required', err)

    def test_decided_result_with_invalid_score_rejected(self):
        ok, result, score, err = validate_result_score('Red', '1 down')
        self.assertFalse(ok)

    def test_decided_result_with_valid_score_ok(self):
        ok, result, score, err = validate_result_score('Blue', '3&2')
        self.assertTrue(ok)
        self.assertEqual(result, 'Blue')
        self.assertEqual(score, '3&2')

    def test_invalid_result_value_rejected(self):
        ok, result, score, err = validate_result_score('Green', '1UP')
        self.assertFalse(ok)


class CaptainWriteActionsTestCase(unittest.TestCase):
    """Shared fixture: a tempfile SQLite DB with a 2026 roster (Blue: Jeff Smith, Jeffrey Jones,
    Jordan; Red: Conor, Ian) plus handicaps, and a course, wired into a real PairingSuggester."""

    YEAR = 2026

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)
        self.data_service = DataService(self.db_service)
        self.suggester = PairingSuggester(
            self.data_service, self.db_service, api_key='test-key', model='claude-test'
        )

        self.db_service.add_course('Druids Glen', 71, 128, 71.5)

        blue_players = {'Jeff Smith': 12.0, 'Jordan Lee': 8.0}
        red_players = {'Conor Byrne': 14.0, 'Ian Doyle': 20.0}
        for name, hcp in blue_players.items():
            self.db_service.assign_player_team(name, self.YEAR, 'Blue')
            self.db_service.add_or_update_handicap(name, self.YEAR, hcp)
        for name, hcp in red_players.items():
            self.db_service.assign_player_team(name, self.YEAR, 'Red')
            self.db_service.add_or_update_handicap(name, self.YEAR, hcp)

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _execute(self, tool_name, tool_input):
        return json.loads(self.suggester._execute_tool(tool_name, tool_input))


class TestCreateMatches(CaptainWriteActionsTestCase):
    def test_singles_happy_path(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'druids glen',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff Smith'],
                'side_b_players': ['Conor Byrne'],
            }],
        })
        self.assertIn('created', payload)
        self.assertEqual(len(payload['created']), 1)
        created = payload['created'][0]
        self.assertNotIn('error', created)
        self.assertEqual(created['course'], 'Druids Glen')
        self.assertEqual(created['blue_players'][0]['name'], 'Jeff Smith')
        self.assertEqual(created['red_players'][0]['name'], 'Conor Byrne')

        expected = HandicapCalculator.calculate_match_handicaps(
            match_type='Singles', handicap_index_p1=12.0, handicap_index_p2=None,
            handicap_index_p3=14.0, handicap_index_p4=None, slope_rating=128, par=71,
        )
        self.assertEqual(created['blue_players'][0]['handicap'], expected[0])
        self.assertEqual(created['red_players'][0]['handicap'], expected[1])

        matches_df = self.db_service.get_matches_by_year(self.YEAR)
        self.assertEqual(len(matches_df), 1)

    def test_fourball_happy_path_partial_name_match(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Fourball',
                'side_a_players': ['Jeff', 'Jordan'],
                'side_b_players': ['Conor', 'Ian'],
            }],
        })
        self.assertIn('created', payload)
        created = payload['created'][0]
        self.assertNotIn('error', created)
        blue_names = {p['name'] for p in created['blue_players']}
        red_names = {p['name'] for p in created['red_players']}
        self.assertEqual(blue_names, {'Jeff Smith', 'Jordan Lee'})
        self.assertEqual(red_names, {'Conor Byrne', 'Ian Doyle'})

    def test_two_matches_batched_get_sequential_match_numbers(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [
                {'match_type': 'Singles', 'side_a_players': ['Jeff Smith'], 'side_b_players': ['Conor Byrne']},
                {'match_type': 'Singles', 'side_a_players': ['Jordan Lee'], 'side_b_players': ['Ian Doyle']},
            ],
        })
        numbers = sorted(c['match_number'] for c in payload['created'])
        self.assertEqual(numbers, [1, 2])

    def test_team_color_mismatch_within_side_rejected(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Fourball',
                'side_a_players': ['Jeff Smith', 'Conor Byrne'],
                'side_b_players': ['Jordan Lee', 'Ian Doyle'],
            }],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertEqual(len(self.db_service.get_matches_by_year(self.YEAR)), 0)

    def test_same_team_both_sides_rejected(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff Smith'],
                'side_b_players': ['Jordan Lee'],
            }],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertEqual(len(self.db_service.get_matches_by_year(self.YEAR)), 0)

    def test_unresolvable_player_name(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Nobody Here'],
                'side_b_players': ['Conor Byrne'],
            }],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertTrue(any('Nobody Here' in p for p in payload['problems']))

    def test_ambiguous_player_name(self):
        self.db_service.assign_player_team('Jeffrey Jones', self.YEAR, 'Blue')
        self.db_service.add_or_update_handicap('Jeffrey Jones', self.YEAR, 18.0)

        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff'],
                'side_b_players': ['Conor Byrne'],
            }],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertTrue(any('multiple players' in p for p in payload['problems']))

    def test_missing_handicap_blocks_creation(self):
        self.db_service.assign_player_team('No Handicap Guy', self.YEAR, 'Red')
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff Smith'],
                'side_b_players': ['No Handicap Guy'],
            }],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertEqual(len(self.db_service.get_matches_by_year(self.YEAR)), 0)

    def test_unknown_course_returns_course_not_found(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Nonexistent Links',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff Smith'],
                'side_b_players': ['Conor Byrne'],
            }],
        })
        self.assertEqual(payload.get('error'), 'course_not_found')

    def test_batch_is_atomic_one_bad_match_creates_nothing(self):
        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'Druids Glen',
            'matches': [
                {'match_type': 'Singles', 'side_a_players': ['Jeff Smith'], 'side_b_players': ['Conor Byrne']},
                {'match_type': 'Singles', 'side_a_players': ['Jeff Smith'], 'side_b_players': ['Jordan Lee']},
            ],
        })
        self.assertEqual(payload.get('error'), 'validation_failed')
        self.assertEqual(len(self.db_service.get_matches_by_year(self.YEAR)), 0)

    def test_create_course_then_create_matches(self):
        create_payload = self._execute('create_course', {
            'name': 'New Links', 'par': 72, 'slope_rating': 130, 'course_rating': 72.5,
        })
        self.assertIn('course', create_payload)

        payload = self._execute('create_matches', {
            'year': self.YEAR, 'day': 2, 'course': 'New Links',
            'matches': [{
                'match_type': 'Singles',
                'side_a_players': ['Jeff Smith'],
                'side_b_players': ['Conor Byrne'],
            }],
        })
        self.assertIn('created', payload)
        self.assertEqual(payload['created'][0]['course'], 'New Links')

    def test_create_course_duplicate_rejected(self):
        payload = self._execute('create_course', {
            'name': 'druids glen', 'par': 72, 'slope_rating': 130, 'course_rating': 72.5,
        })
        self.assertIn('error', payload)


class TestRecordMatchResult(CaptainWriteActionsTestCase):
    def _add_pending_match(self, year, day, match_number=1, match_type='Singles',
                            blue='Jeff Smith', red='Conor Byrne'):
        self.db_service.add_match(
            year=year, day=day, match_number=match_number,
            course='Druids Glen', match_type=match_type,
            blue_player1=blue, blue_player1_handicap=0,
            blue_player2=None, blue_player2_handicap=None,
            red_player1=red, red_player1_handicap=0,
            red_player2=None, red_player2_handicap=None,
            result='', score='',
        )
        self.data_service.invalidate_cache()

    def test_finds_pending_match_by_names_only(self):
        self._add_pending_match(self.YEAR, 2)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': '1UP',
        })
        self.assertIn('updated', payload)
        self.assertEqual(payload['updated']['result'], 'Blue')
        self.assertEqual(payload['updated']['score'], '1UP')

        matches_df = self.db_service.get_matches_by_year(self.YEAR)
        row = matches_df.iloc[0]
        self.assertEqual(row['Result'], 'Blue')
        self.assertEqual(row['Score'], '1UP')

    def test_player_b_won_maps_to_correct_side(self):
        self._add_pending_match(self.YEAR, 2, blue='Jeff Smith', red='Conor Byrne')
        payload = self._execute('record_match_result', {
            'player_a': 'Ian Doyle', 'player_b': 'Jordan Lee',
            'outcome': 'player_b_won', 'score': '1UP',
        })
        # Ian (Red) lost to Jordan (Blue) -> need a match with these two first
        self.assertEqual(payload.get('error'), 'no_pending_match')

        self._add_pending_match(self.YEAR, 3, match_number=1, blue='Jordan Lee', red='Ian Doyle')
        payload = self._execute('record_match_result', {
            'player_a': 'Ian Doyle', 'player_b': 'Jordan Lee',
            'outcome': 'player_b_won', 'score': '1UP',
        })
        self.assertIn('updated', payload)
        self.assertEqual(payload['updated']['result'], 'Blue')  # Jordan's side

    def test_half_forces_a_s_score(self):
        self._add_pending_match(self.YEAR, 2)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'half',
        })
        self.assertEqual(payload['updated']['result'], 'Half')
        self.assertEqual(payload['updated']['score'], 'A/S')

    def test_missing_score_asks_for_one(self):
        self._add_pending_match(self.YEAR, 2)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'player_a_won',
        })
        self.assertEqual(payload.get('error'), 'score_required')

        matches_df = self.db_service.get_matches_by_year(self.YEAR)
        self.assertEqual(matches_df.iloc[0]['Result'], '')

    def test_invalid_score_format_rejected(self):
        self._add_pending_match(self.YEAR, 2)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': '1 down',
        })
        self.assertEqual(payload.get('error'), 'invalid_score')

    def test_unknown_score_accepted(self):
        self._add_pending_match(self.YEAR, 2)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': 'Unknown',
        })
        self.assertEqual(payload['updated']['score'], 'Unknown')

    def test_no_pending_match_found(self):
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': '1UP',
        })
        self.assertEqual(payload.get('error'), 'no_pending_match')

    def test_ambiguous_match_across_multiple_pending(self):
        self._add_pending_match(2025, 1, match_number=1)
        self._add_pending_match(2026, 2, match_number=1)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': '1UP',
        })
        self.assertEqual(payload.get('error'), 'ambiguous_match')
        self.assertEqual(len(payload['candidates']), 2)

    def test_year_day_disambiguates(self):
        self._add_pending_match(2025, 1, match_number=1)
        self._add_pending_match(2026, 2, match_number=1)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne',
            'outcome': 'player_a_won', 'score': '1UP', 'year': 2026, 'day': 2,
        })
        self.assertIn('updated', payload)
        self.assertEqual(payload['updated']['year'], 2026)
        self.assertEqual(payload['updated']['day'], 2)

        # the 2025 match should remain untouched/pending
        other = self.db_service.get_matches_by_year(2025).iloc[0]
        self.assertEqual(other['Result'], '')


class TestClearMatchResult(CaptainWriteActionsTestCase):
    """outcome='clear' - undoing an incorrectly-recorded result back to pending."""

    def _add_decided_match(self, year, day, match_number=1, match_type='Singles',
                            blue='Jeff Smith', red='Conor Byrne', result='Blue', score='1UP'):
        self.db_service.add_match(
            year=year, day=day, match_number=match_number,
            course='Druids Glen', match_type=match_type,
            blue_player1=blue, blue_player1_handicap=0,
            blue_player2=None, blue_player2_handicap=None,
            red_player1=red, red_player1_handicap=0,
            red_player2=None, red_player2_handicap=None,
            result=result, score=score,
        )
        self.data_service.invalidate_cache()

    def test_clear_resets_decided_match_to_pending(self):
        self._add_decided_match(self.YEAR, 2, result='Blue', score='1UP')
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'clear',
        })
        self.assertIn('updated', payload)
        self.assertEqual(payload['updated']['result'], '')
        self.assertEqual(payload['updated']['score'], '')

        row = self.db_service.get_matches_by_year(self.YEAR).iloc[0]
        self.assertEqual(row['Result'], '')
        self.assertEqual(row['Score'], '')

    def test_clear_works_on_half_result_too(self):
        self._add_decided_match(self.YEAR, 2, result='Half', score='A/S')
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'clear',
        })
        self.assertIn('updated', payload)
        row = self.db_service.get_matches_by_year(self.YEAR).iloc[0]
        self.assertEqual(row['Result'], '')

    def test_clear_ignores_pending_matches(self):
        self._add_decided_match(self.YEAR, 2, result='', score='')  # already pending, nothing to clear
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'clear',
        })
        self.assertEqual(payload.get('error'), 'no_result_to_clear')

    def test_clear_ambiguous_across_multiple_decided_matches(self):
        self._add_decided_match(2025, 1, match_number=1)
        self._add_decided_match(2026, 2, match_number=1)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'clear',
        })
        self.assertEqual(payload.get('error'), 'ambiguous_match')
        self.assertEqual(len(payload['candidates']), 2)

    def test_clear_disambiguated_by_year_day(self):
        self._add_decided_match(2025, 1, match_number=1)
        self._add_decided_match(2026, 2, match_number=1)
        payload = self._execute('record_match_result', {
            'player_a': 'Jeff Smith', 'player_b': 'Conor Byrne', 'outcome': 'clear',
            'year': 2026, 'day': 2,
        })
        self.assertIn('updated', payload)
        self.assertEqual(payload['updated']['year'], 2026)

        other = self.db_service.get_matches_by_year(2025).iloc[0]
        self.assertEqual(other['Result'], 'Blue')  # untouched


if __name__ == '__main__':
    unittest.main()
