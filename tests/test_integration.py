"""
Integration tests for the golf trips application
Tests end-to-end workflows for player management, course management,
match creation with auto-calculations, and match editing
"""
import unittest
import os
import tempfile
from src.db_service import DatabaseService
from src.handicap_calculator import HandicapCalculator


class TestPlayerManagementIntegration(unittest.TestCase):
    """Test player management workflows"""

    def setUp(self):
        """Create temporary database for testing"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)

    def tearDown(self):
        """Clean up temporary database"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_add_player_with_handicap(self):
        """Test adding a new player with handicap"""
        # Add player
        success = self.db_service.add_player("John Doe")
        self.assertTrue(success)

        # Add handicap for 2024
        success = self.db_service.add_or_update_handicap("John Doe", 2024, 12.5)
        self.assertTrue(success)

        # Verify handicap was added
        handicap = self.db_service.get_player_handicap("John Doe", 2024)
        self.assertEqual(handicap, 12.5)

    def test_update_player_handicap(self):
        """Test updating an existing player's handicap"""
        # Add player and handicap
        self.db_service.add_player("Jane Smith")
        self.db_service.add_or_update_handicap("Jane Smith", 2024, 15.0)

        # Update handicap
        success = self.db_service.add_or_update_handicap("Jane Smith", 2024, 14.5)
        self.assertTrue(success)

        # Verify update
        handicap = self.db_service.get_player_handicap("Jane Smith", 2024)
        self.assertEqual(handicap, 14.5)

    def test_multiple_years_handicaps(self):
        """Test managing handicaps across multiple years"""
        player = "Bob Wilson"
        self.db_service.add_player(player)

        # Add handicaps for different years
        self.db_service.add_or_update_handicap(player, 2022, 18.0)
        self.db_service.add_or_update_handicap(player, 2023, 16.5)
        self.db_service.add_or_update_handicap(player, 2024, 15.2)

        # Verify all handicaps
        self.assertEqual(self.db_service.get_player_handicap(player, 2022), 18.0)
        self.assertEqual(self.db_service.get_player_handicap(player, 2023), 16.5)
        self.assertEqual(self.db_service.get_player_handicap(player, 2024), 15.2)

    def test_delete_handicap(self):
        """Test deleting a player's handicap"""
        player = "Alice Brown"
        self.db_service.add_player(player)
        self.db_service.add_or_update_handicap(player, 2024, 10.0)

        # Delete handicap
        success = self.db_service.delete_handicap(player, 2024)
        self.assertTrue(success)

        # Verify deletion
        handicap = self.db_service.get_player_handicap(player, 2024)
        self.assertIsNone(handicap)

    def test_get_all_players_with_handicaps(self):
        """Test retrieving all players with their handicaps"""
        # Add multiple players with handicaps
        self.db_service.add_player("Player1")
        self.db_service.add_or_update_handicap("Player1", 2024, 12.0)
        self.db_service.add_or_update_handicap("Player1", 2023, 13.0)

        self.db_service.add_player("Player2")
        self.db_service.add_or_update_handicap("Player2", 2024, 8.5)

        players = self.db_service.get_all_players_with_handicaps()

        # Verify structure
        self.assertGreater(len(players), 0)
        player1_data = next((p for p in players if p['name'] == 'Player1'), None)
        self.assertIsNotNone(player1_data)
        self.assertEqual(player1_data['handicaps'][2024], 12.0)
        self.assertEqual(player1_data['handicaps'][2023], 13.0)


class TestCourseManagementIntegration(unittest.TestCase):
    """Test course management workflows"""

    def setUp(self):
        """Create temporary database for testing"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)

    def tearDown(self):
        """Clean up temporary database"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_add_course(self):
        """Test adding a new course"""
        success = self.db_service.add_course(
            name="St Andrews Old Course",
            par=72,
            slope_rating=130,
            course_rating=73.5
        )
        self.assertTrue(success)

        # Verify course was added
        course = self.db_service.get_course("St Andrews Old Course")
        self.assertIsNotNone(course)
        self.assertEqual(course['par'], 72)
        self.assertEqual(course['slope_rating'], 130)
        self.assertEqual(course['course_rating'], 73.5)

    def test_update_course(self):
        """Test updating an existing course"""
        # Add course
        self.db_service.add_course("Pebble Beach", 72, 145, 75.5)

        # Update course
        success = self.db_service.update_course("Pebble Beach", 72, 142, 74.8)
        self.assertTrue(success)

        # Verify update
        course = self.db_service.get_course("Pebble Beach")
        self.assertEqual(course['slope_rating'], 142)
        self.assertEqual(course['course_rating'], 74.8)

    def test_get_all_courses(self):
        """Test retrieving all courses"""
        # Add multiple courses
        self.db_service.add_course("Course A", 72, 113, 72.0)
        self.db_service.add_course("Course B", 70, 120, 70.5)

        courses = self.db_service.get_all_courses()
        self.assertGreaterEqual(len(courses), 2)

        course_names = [c['name'] for c in courses]
        self.assertIn("Course A", course_names)
        self.assertIn("Course B", course_names)

    def test_delete_course(self):
        """Test deleting a course"""
        self.db_service.add_course("Temp Course", 72, 113, 72.0)

        # Delete course
        success = self.db_service.delete_course("Temp Course")
        self.assertTrue(success)

        # Verify deletion
        course = self.db_service.get_course("Temp Course")
        self.assertIsNone(course)


class TestMatchCreationWithAutoCalculation(unittest.TestCase):
    """Test match creation with automatic handicap calculation"""

    def setUp(self):
        """Create temporary database and set up test data"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)

        # Set up test players with handicaps
        self.db_service.add_player("Player A")
        self.db_service.add_or_update_handicap("Player A", 2024, 10.0)

        self.db_service.add_player("Player B")
        self.db_service.add_or_update_handicap("Player B", 2024, 15.0)

        self.db_service.add_player("Player C")
        self.db_service.add_or_update_handicap("Player C", 2024, 8.0)

        self.db_service.add_player("Player D")
        self.db_service.add_or_update_handicap("Player D", 2024, 12.0)

        # Set up test course
        self.db_service.add_course("Test Course", 72, 130, 73.0)

    def tearDown(self):
        """Clean up temporary database"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_singles_match_auto_calculation(self):
        """Test singles match with auto-calculated handicaps"""
        # Get player handicaps
        p1_index = self.db_service.get_player_handicap("Player A", 2024)
        p2_index = self.db_service.get_player_handicap("Player B", 2024)

        # Get course info
        course = self.db_service.get_course("Test Course")

        # Calculate handicaps
        handicaps = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=p1_index,
            handicap_index_p2=None,
            handicap_index_p3=p2_index,
            handicap_index_p4=None,
            slope_rating=course['slope_rating'],
            par=course['par']
        )

        # Add match with calculated handicaps
        success = self.db_service.add_match(
            year=2024, day=1, match_number=1,
            course="Test Course", match_type="Single",
            blue_player1="Player A", blue_player1_handicap=handicaps[0],
            blue_player2=None, blue_player2_handicap=None,
            red_player1="Player B", red_player1_handicap=handicaps[1],
            red_player2=None, red_player2_handicap=None,
            result="", score=""
        )

        self.assertTrue(success)

        # Verify match was added
        matches = self.db_service.get_matches_by_year(2024)
        self.assertEqual(len(matches), 1)

        match = matches.iloc[0]
        # Player A (10.0 index) should get 0 strokes (lower handicap)
        # Player B (15.0 index) should get strokes (higher handicap)
        self.assertEqual(match['BluePlayer1MatchHandicap'], handicaps[0])
        self.assertEqual(match['RedPlayer1MatchHandicap'], handicaps[1])
        self.assertGreater(handicaps[1], handicaps[0])

    def test_fourball_match_auto_calculation(self):
        """Test fourball match with auto-calculated handicaps"""
        # Get player handicaps
        p1_index = self.db_service.get_player_handicap("Player A", 2024)
        p2_index = self.db_service.get_player_handicap("Player B", 2024)
        p3_index = self.db_service.get_player_handicap("Player C", 2024)
        p4_index = self.db_service.get_player_handicap("Player D", 2024)

        # Get course info
        course = self.db_service.get_course("Test Course")

        # Calculate handicaps (85% for fourball)
        handicaps = HandicapCalculator.calculate_match_handicaps(
            match_type='Fourball',
            handicap_index_p1=p1_index,
            handicap_index_p2=p2_index,
            handicap_index_p3=p3_index,
            handicap_index_p4=p4_index,
            slope_rating=course['slope_rating'],
            par=course['par']
        )

        # Add match
        success = self.db_service.add_match(
            year=2024, day=1, match_number=2,
            course="Test Course", match_type="Fourball",
            blue_player1="Player A", blue_player1_handicap=handicaps[0],
            blue_player2="Player B", blue_player2_handicap=handicaps[1],
            red_player1="Player C", red_player1_handicap=handicaps[2],
            red_player2="Player D", red_player2_handicap=handicaps[3],
            result="", score=""
        )

        self.assertTrue(success)

        # Verify match was added
        matches = self.db_service.get_matches_by_year(2024)
        match = matches[matches['MatchNumber'] == 2].iloc[0]

        # Player C has lowest handicap (8.0), should get 0 strokes
        self.assertEqual(match['RedPlayer1MatchHandicap'], 0)

        # Other players should have positive handicaps
        self.assertGreater(match['BluePlayer1MatchHandicap'] + match['BluePlayer2MatchHandicap'] +
                          match['RedPlayer2MatchHandicap'], 0)


class TestMatchEditFunctionality(unittest.TestCase):
    """Test match editing workflows"""

    def setUp(self):
        """Create temporary database and add test match"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)

        # Set up test data
        self.db_service.add_player("Player 1")
        self.db_service.add_player("Player 2")
        self.db_service.add_course("Test Course", 72, 113, 72.0)

        # Add a match without result
        self.db_service.add_match(
            year=2024, day=1, match_number=1,
            course="Test Course", match_type="Single",
            blue_player1="Player 1", blue_player1_handicap=0,
            blue_player2=None, blue_player2_handicap=None,
            red_player1="Player 2", red_player1_handicap=5,
            red_player2=None, red_player2_handicap=None,
            result="", score=""
        )

    def tearDown(self):
        """Clean up temporary database"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_update_match_result(self):
        """Test updating match result after it's played"""
        # Update match result
        success = self.db_service.update_match_result(
            year=2024, day=1, match_number=1,
            result="Blue", score="3&2"
        )
        self.assertTrue(success)

        # Verify update
        matches = self.db_service.get_matches_by_year(2024)
        match = matches.iloc[0]
        self.assertEqual(match['Result'], "Blue")
        self.assertEqual(match['Score'], "3&2")

    def test_update_match_to_halved(self):
        """Test updating match result to halved"""
        success = self.db_service.update_match_result(
            year=2024, day=1, match_number=1,
            result="Half", score="A/S"
        )
        self.assertTrue(success)

        matches = self.db_service.get_matches_by_year(2024)
        match = matches.iloc[0]
        self.assertEqual(match['Result'], "Half")
        self.assertEqual(match['Score'], "A/S")

    def test_update_nonexistent_match(self):
        """Test updating a match that doesn't exist"""
        success = self.db_service.update_match_result(
            year=2024, day=1, match_number=999,
            result="Blue", score="1UP"
        )
        self.assertFalse(success)

    def test_change_result_multiple_times(self):
        """Test changing match result multiple times"""
        # First update
        self.db_service.update_match_result(2024, 1, 1, "Blue", "2&1")
        matches = self.db_service.get_matches_by_year(2024)
        self.assertEqual(matches.iloc[0]['Result'], "Blue")

        # Second update
        self.db_service.update_match_result(2024, 1, 1, "Red", "1UP")
        matches = self.db_service.get_matches_by_year(2024)
        self.assertEqual(matches.iloc[0]['Result'], "Red")
        self.assertEqual(matches.iloc[0]['Score'], "1UP")


class TestEndToEndWorkflow(unittest.TestCase):
    """Test complete end-to-end workflow"""

    def setUp(self):
        """Create temporary database"""
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.db_service = DatabaseService(self.db_path)

    def tearDown(self):
        """Clean up temporary database"""
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_complete_workflow(self):
        """Test complete workflow: add players, courses, create match, edit result"""

        # Step 1: Add players with handicaps
        self.db_service.add_player("Tiger Woods")
        self.db_service.add_or_update_handicap("Tiger Woods", 2024, 2.5)

        self.db_service.add_player("Phil Mickelson")
        self.db_service.add_or_update_handicap("Phil Mickelson", 2024, 8.0)

        # Step 2: Add course
        self.db_service.add_course("Augusta National", 72, 137, 74.9)
        course = self.db_service.get_course("Augusta National")
        self.assertIsNotNone(course)

        # Step 3: Calculate handicaps
        tiger_index = self.db_service.get_player_handicap("Tiger Woods", 2024)
        phil_index = self.db_service.get_player_handicap("Phil Mickelson", 2024)

        handicaps = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=tiger_index,
            handicap_index_p2=None,
            handicap_index_p3=phil_index,
            handicap_index_p4=None,
            slope_rating=course['slope_rating'],
            par=course['par']
        )

        # Step 4: Create match
        success = self.db_service.add_match(
            year=2024, day=1, match_number=1,
            course="Augusta National", match_type="Single",
            blue_player1="Tiger Woods", blue_player1_handicap=handicaps[0],
            blue_player2=None, blue_player2_handicap=None,
            red_player1="Phil Mickelson", red_player1_handicap=handicaps[1],
            red_player2=None, red_player2_handicap=None,
            result="", score=""
        )
        self.assertTrue(success)

        # Step 5: Edit match result after it's played
        success = self.db_service.update_match_result(
            year=2024, day=1, match_number=1,
            result="Blue", score="4&3"
        )
        self.assertTrue(success)

        # Step 6: Verify complete match data
        matches = self.db_service.get_matches_by_year(2024)
        self.assertEqual(len(matches), 1)

        match = matches.iloc[0]
        self.assertEqual(match['BluePlayer1'], "Tiger Woods")
        self.assertEqual(match['RedPlayer1'], "Phil Mickelson")
        self.assertEqual(match['Course'], "Augusta National")
        self.assertEqual(match['Result'], "Blue")
        self.assertEqual(match['Score'], "4&3")

        # Tiger should have 0 strokes (lower handicap)
        self.assertEqual(match['BluePlayer1MatchHandicap'], 0)
        # Phil should have strokes (higher handicap)
        self.assertGreater(match['RedPlayer1MatchHandicap'], 0)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
