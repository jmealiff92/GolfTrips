import unittest
import pandas as pd
from unittest.mock import Mock, MagicMock, patch
import numpy as np
from src.data_service import DataService, check_value_exists, get_match_result_for_player
from src.db_service import DatabaseService


class TestDataService(unittest.TestCase):
    """Unit tests for DataService class"""

    def setUp(self):
        """Set up test fixtures before each test method"""
        self.mock_db = Mock(spec=DatabaseService)
        self.data_service = DataService(self.mock_db)
        
        # Sample match data for testing
        self.sample_matches = pd.DataFrame({
            'Year': [2023, 2023, 2023, 2024, 2024],
            'MatchNumber': [1, 2, 3, 1, 2],
            'Day': [1, 1, 2, 1, 1],
            'MatchType': ['Fourball', 'Singles', 'Fourball', 'Singles', 'Fourball'],
            'BluePlayer1': ['John', 'John', 'John', 'John', 'John'],
            'BluePlayer2': ['Mike', None, 'Mike', None, 'Mike'],
            'RedPlayer1': ['Bob', 'Bob', 'Bob', 'Bob', 'Bob'],
            'RedPlayer2': ['Tom', None, 'Tom', None, 'Tom'],
            'Result': ['Blue', 'Red', 'Half', 'Blue', 'Red'],
            'Score': ['2&1', '3&2', 'AS', '4&3', '1UP'],
            'BluePlayer1MatchHandicap': [10, 10, 10, 10, 10],
            'BluePlayer2MatchHandicap': [8, None, 8, None, 8],
            'RedPlayer1MatchHandicap': [12, 12, 12, 12, 12],
            'RedPlayer2MatchHandicap': [14, None, 14, None, 14]
        })

    def test_init(self):
        """Test DataService initialization"""
        self.assertEqual(self.data_service.db, self.mock_db)
        self.assertIsNone(self.data_service._df_cache)
        self.assertFalse(self.data_service._cache_valid)

    def test_invalidate_cache(self):
        """Test cache invalidation"""
        # Set cache as valid
        self.data_service._cache_valid = True
        self.data_service._df_cache = pd.DataFrame()
        
        # Invalidate cache
        self.data_service.invalidate_cache()
        
        self.assertFalse(self.data_service._cache_valid)

    def test_df_property_cache_hit(self):
        """Test df property returns cached data when valid"""
        expected_df = pd.DataFrame({'test': [1, 2, 3]})
        self.data_service._df_cache = expected_df
        self.data_service._cache_valid = True
        
        result = self.data_service.df
        
        self.assertTrue(result.equals(expected_df))
        self.mock_db.get_all_matches.assert_not_called()

    def test_df_property_cache_miss(self):
        """Test df property fetches data when cache invalid"""
        expected_df = pd.DataFrame({'test': [1, 2, 3]})
        self.mock_db.get_all_matches.return_value = expected_df
        
        result = self.data_service.df
        
        self.assertTrue(result.equals(expected_df))
        self.assertTrue(self.data_service._cache_valid)
        self.mock_db.get_all_matches.assert_called_once()

    def test_players_property(self):
        """Test players property delegates to database service"""
        expected_players = ['John', 'Mike', 'Bob', 'Tom']
        self.mock_db.get_players_from_matches.return_value = expected_players
        
        result = self.data_service.players
        
        self.assertEqual(result, expected_players)
        self.mock_db.get_players_from_matches.assert_called_once()

    def test_get_players_list(self):
        """Test get_players_list method"""
        expected_players = ['John', 'Mike', 'Bob', 'Tom']
        self.mock_db.get_players_from_matches.return_value = expected_players
        
        result = self.data_service.get_players_list()
        
        self.assertEqual(result, expected_players)

    def test_summarise_team_results_empty_df(self):
        """Test team results summary with empty dataframe"""
        self.mock_db.get_all_matches.return_value = pd.DataFrame()
        
        result = self.data_service.summarise_team_results()
        
        self.assertTrue(result.empty)

    def test_summarise_team_results(self):
        """Test team results summary calculation"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        
        result = self.data_service.summarise_team_results()
        
        # Check structure
        expected_columns = ['Year', 'Blue_Points', 'Red_Points', 'Winner']
        self.assertEqual(list(result.columns), expected_columns)
        
        # Check calculations for 2023 specifically
        matches_2023 = self.sample_matches[self.sample_matches['Year'] == 2023]
        blue_wins_2023 = (matches_2023['Result'] == 'Blue').sum()
        red_wins_2023 = (matches_2023['Result'] == 'Red').sum()
        halves_2023 = (matches_2023['Result'] == 'Half').sum()
        
        expected_blue_points = blue_wins_2023 + halves_2023 * 0.5
        expected_red_points = red_wins_2023 + halves_2023 * 0.5
        
        # Find the row for 2023
        result_2023 = result[result['Year'] == 2023].iloc[0]
        self.assertEqual(result_2023['Blue_Points'], expected_blue_points)
        self.assertEqual(result_2023['Red_Points'], expected_red_points)

    def test_get_player_team_blue(self):
        """Test getting player team when player is on Blue team"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        
        result = self.data_service.get_player_team('John', 2023)
        
        self.assertEqual(result, 'Blue')

    def test_get_player_team_red(self):
        """Test getting player team when player is on Red team"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        
        result = self.data_service.get_player_team('Bob', 2023)
        
        self.assertEqual(result, 'Red')

    def test_get_player_team_not_found(self):
        """Test getting player team when player not found"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        
        result = self.data_service.get_player_team('Unknown', 2023)
        
        self.assertIsNone(result)

    def test_build_results_per_player_empty_df(self):
        """Test building results per player with empty dataframe"""
        self.mock_db.get_all_matches.return_value = pd.DataFrame()
        self.mock_db.get_players_from_matches.return_value = []
        
        result = self.data_service.build_results_per_player()
        
        self.assertTrue(result.empty)

    def test_build_results_per_player(self):
        """Test building results per player"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        self.mock_db.get_players_from_matches.return_value = ['John', 'Mike', 'Bob', 'Tom']
        
        result = self.data_service.build_results_per_player()
        
        # Check structure
        expected_columns = ['Player', 'Year', 'MatchNumber', 'Day', 'Result', 'Score', 'Team', 'MatchType']
        self.assertEqual(list(result.columns), expected_columns)
        
        # Should have entries for each player
        self.assertTrue(len(result) > 0)

    def test_get_match_result_for_player_method(self):
        """Test match result conversion for player perspective"""
        # Test win scenarios
        self.assertEqual(self.data_service.get_match_result_for_player('Blue', 'Blue'), 'Win')
        self.assertEqual(self.data_service.get_match_result_for_player('Red', 'Red'), 'Win')
        
        # Test loss scenarios
        self.assertEqual(self.data_service.get_match_result_for_player('Blue', 'Red'), 'Loss')
        self.assertEqual(self.data_service.get_match_result_for_player('Red', 'Blue'), 'Loss')
        
        # Test half scenarios
        self.assertEqual(self.data_service.get_match_result_for_player('Half', 'Blue'), 'Half')
        self.assertEqual(self.data_service.get_match_result_for_player('Half', 'Red'), 'Half')

    def test_get_player_performance_all_players_empty_df(self):
        """Test player performance with empty dataframe"""
        with patch.object(self.data_service, 'build_results_per_player', return_value=pd.DataFrame()):
            result = self.data_service.get_player_performance_all_players()
            
            self.assertTrue(result.empty)

    def test_get_player_performance_all_players(self):
        """Test player performance calculation"""
        sample_results = pd.DataFrame({
            'Player': ['John', 'John', 'Bob', 'Bob'],
            'Year': [2023, 2023, 2023, 2023],
            'Result': ['Win', 'Loss', 'Win', 'Half'],
            'MatchType': ['Fourball', 'Singles', 'Fourball', 'Singles']
        })
        
        with patch.object(self.data_service, 'build_results_per_player', return_value=sample_results):
            result = self.data_service.get_player_performance_all_players()
            
            # Check structure
            expected_columns = ['Player', 'Matches', 'Wins', 'Losses', 'Halves', 'Points', 'Win %', 'PPG']
            self.assertEqual(list(result.columns), expected_columns)
            
            # Check John's stats
            john_stats = result[result['Player'] == 'John'].iloc[0]
            self.assertEqual(john_stats['Matches'], 2)
            self.assertEqual(john_stats['Wins'], 1)
            self.assertEqual(john_stats['Losses'], 1)
            self.assertEqual(john_stats['Halves'], 0)
            self.assertEqual(john_stats['Points'], 1.0)

    def test_get_player_performance_with_match_type_filter(self):
        """Test player performance with match type filter"""
        sample_results = pd.DataFrame({
            'Player': ['John', 'John', 'Bob', 'Bob'],
            'Year': [2023, 2023, 2023, 2023],
            'Result': ['Win', 'Loss', 'Win', 'Half'],
            'MatchType': ['Fourball', 'Singles', 'Fourball', 'Singles']
        })
        
        with patch.object(self.data_service, 'build_results_per_player', return_value=sample_results):
            result = self.data_service.get_player_performance_all_players(match_type='Fourball')
            
            # Should only include Fourball matches
            self.assertEqual(len(result), 2)  # John and Bob
            john_stats = result[result['Player'] == 'John'].iloc[0]
            self.assertEqual(john_stats['Matches'], 1)  # Only one Fourball match

    def test_get_head_to_head_stats(self):
        """Test head-to-head stats delegation"""
        expected_stats = {'wins': 2, 'losses': 1}
        self.mock_db.get_head_to_head.return_value = expected_stats
        
        result = self.data_service.get_head_to_head_stats('John', 'Bob')
        
        self.assertEqual(result, expected_stats)
        self.mock_db.get_head_to_head.assert_called_once_with('John', 'Bob')

    def test_get_course_statistics(self):
        """Test course statistics delegation"""
        expected_stats = pd.DataFrame({'Course': ['Course1'], 'Matches': [5]})
        self.mock_db.get_course_statistics.return_value = expected_stats
        
        result = self.data_service.get_course_statistics()
        
        self.assertTrue(result.equals(expected_stats))
        self.mock_db.get_course_statistics.assert_called_once()

    def test_get_player_course_performance(self):
        """Test player course performance delegation"""
        expected_performance = pd.DataFrame({'Course': ['Course1'], 'Matches': [3]})
        self.mock_db.get_player_course_performance.return_value = expected_performance
        
        result = self.data_service.get_player_course_performance('John')
        
        self.assertTrue(result.equals(expected_performance))
        self.mock_db.get_player_course_performance.assert_called_once_with('John')

    def test_build_player_matches_empty_df(self):
        """Test building player matches with empty dataframe"""
        self.mock_db.get_all_matches.return_value = pd.DataFrame()
        
        result = self.data_service.build_player_matches()
        
        expected_columns = [
            "player_name", "player_team", "player_handicap",
            "partner_name", "partner_handicap",
            "match_type", "result", "year", "match_number", "day", "score"
        ]
        self.assertEqual(list(result.columns), expected_columns)
        self.assertTrue(result.empty)

    def test_build_player_matches(self):
        """Test building player matches"""
        self.mock_db.get_all_matches.return_value = self.sample_matches
        
        result = self.data_service.build_player_matches()
        
        # Should have entries for each player in each match
        self.assertTrue(len(result) > 0)
        
        # Check that we have entries for John (Blue team)
        john_entries = result[result['player_name'] == 'John']
        self.assertTrue(len(john_entries) > 0)
        self.assertTrue(all(john_entries['player_team'] == 'Blue'))

    def test_get_partner_performace_all_players(self):
        """Test partner performance analysis for all players"""
        sample_player_matches = pd.DataFrame({
            'player_name': ['John', 'John', 'Mike', 'Mike'],
            'partner_name': ['Mike', 'Mike', 'John', 'John'],
            'result': ['Win', 'Loss', 'Win', 'Loss'],
            'match_type': ['Fourball', 'Fourball', 'Fourball', 'Fourball'],
            'year': [2023, 2023, 2023, 2023],
            'match_number': [1, 2, 1, 2],
            'day': [1, 1, 1, 1]
        })
        
        with patch.object(self.data_service, 'build_player_matches', return_value=sample_player_matches):
            result = self.data_service.get_partner_performace()
            
            # Should have partnership data
            self.assertTrue(len(result) > 0)
            self.assertIn('partnership', result.columns)

    def test_get_partner_performace_specific_player(self):
        """Test partner performance analysis for specific player"""
        sample_player_matches = pd.DataFrame({
            'player_name': ['John', 'John', 'Bob', 'Bob'],
            'partner_name': ['Mike', 'Tom', 'Mike', 'Tom'],
            'result': ['Win', 'Loss', 'Win', 'Loss'],
            'match_type': ['Fourball', 'Fourball', 'Fourball', 'Fourball'],
            'year': [2023, 2023, 2023, 2023],
            'match_number': [1, 2, 1, 2],
            'day': [1, 1, 1, 1]
        })
        
        with patch.object(self.data_service, 'build_player_matches', return_value=sample_player_matches):
            result = self.data_service.get_partner_performace(player='John')
            
            # Should only include John's partnerships
            john_partnerships = result[result['partnership'].str.contains('John', na=False)]
            self.assertEqual(len(result), len(john_partnerships))

    def test_get_partner_performace_min_matches_filter(self):
        """Test partner performance with minimum matches filter"""
        sample_player_matches = pd.DataFrame({
            'player_name': ['John', 'John', 'Mike', 'Mike'],
            'partner_name': ['Mike', 'Mike', 'John', 'John'],
            'result': ['Win', 'Loss', 'Win', 'Loss'],
            'match_type': ['Fourball', 'Fourball', 'Fourball', 'Fourball'],
            'year': [2023, 2023, 2023, 2023],
            'match_number': [1, 2, 1, 2],
            'day': [1, 1, 1, 1]
        })
        
        with patch.object(self.data_service, 'build_player_matches', return_value=sample_player_matches):
            result = self.data_service.get_partner_performace(min_matches=2)
            
            # Should only include partnerships with 2+ matches
            self.assertTrue(all(result['Matches'] >= 2))


class TestUtilityFunctions(unittest.TestCase):
    """Unit tests for utility functions"""

    def test_check_value_exists_with_valid_values(self):
        """Test check_value_exists with valid values"""
        self.assertTrue(check_value_exists("John"))
        self.assertTrue(check_value_exists("A"))
        self.assertTrue(check_value_exists("   "))

    def test_check_value_exists_with_invalid_values(self):
        """Test check_value_exists with invalid values"""
        self.assertFalse(check_value_exists(None))
        self.assertFalse(check_value_exists(""))
        self.assertFalse(check_value_exists(""))

    def test_get_match_result_for_player_function(self):
        """Test get_match_result_for_player standalone function"""
        # Test win scenarios
        self.assertEqual(get_match_result_for_player('Blue', 'Blue'), 'Win')
        self.assertEqual(get_match_result_for_player('Red', 'Red'), 'Win')
        
        # Test loss scenarios
        self.assertEqual(get_match_result_for_player('Blue', 'Red'), 'Loss')
        self.assertEqual(get_match_result_for_player('Red', 'Blue'), 'Loss')
        
        # Test half scenarios
        self.assertEqual(get_match_result_for_player('Half', 'Blue'), 'Half')
        self.assertEqual(get_match_result_for_player('Half', 'Red'), 'Half')


if __name__ == '__main__':
    unittest.main()