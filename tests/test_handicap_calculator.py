"""
Unit tests for handicap calculator
Tests WHS/R&A handicap calculation methods
"""
import unittest
from handicap_calculator import HandicapCalculator


class TestHandicapCalculator(unittest.TestCase):
    """Test cases for HandicapCalculator"""

    def test_course_handicap_standard_slope(self):
        """Test course handicap calculation with standard slope (113)"""
        # Standard slope should give course handicap = handicap index
        result = HandicapCalculator.calculate_course_handicap(
            handicap_index=10.0, slope_rating=113, par=72)
        self.assertEqual(result, 10)

    def test_course_handicap_high_slope(self):
        """Test course handicap calculation with high slope"""
        # Higher slope should increase course handicap
        result = HandicapCalculator.calculate_course_handicap(
            handicap_index=10.0, slope_rating=140, par=72)
        # 10 * (140/113) = 12.39 -> rounds to 12
        self.assertEqual(result, 12)

    def test_course_handicap_low_slope(self):
        """Test course handicap calculation with low slope"""
        # Lower slope should decrease course handicap
        result = HandicapCalculator.calculate_course_handicap(
            handicap_index=10.0, slope_rating=100, par=72)
        # 10 * (100/113) = 8.85 -> rounds to 9
        self.assertEqual(result, 9)

    def test_course_handicap_rounding(self):
        """Test course handicap rounding"""
        # Test rounding down
        result1 = HandicapCalculator.calculate_course_handicap(
            handicap_index=10.4, slope_rating=113, par=72)
        self.assertEqual(result1, 10)

        # Test rounding up
        result2 = HandicapCalculator.calculate_course_handicap(
            handicap_index=10.6, slope_rating=113, par=72)
        self.assertEqual(result2, 11)

    def test_singles_equal_handicaps(self):
        """Test singles match with equal handicaps"""
        p1_hcp, p2_hcp = HandicapCalculator.calculate_playing_handicap_singles(
            course_handicap_p1=10, course_handicap_p2=10)
        self.assertEqual(p1_hcp, 0)
        self.assertEqual(p2_hcp, 0)

    def test_singles_player1_lower(self):
        """Test singles match where player 1 has lower handicap"""
        p1_hcp, p2_hcp = HandicapCalculator.calculate_playing_handicap_singles(
            course_handicap_p1=8, course_handicap_p2=12)
        self.assertEqual(p1_hcp, 0)
        self.assertEqual(p2_hcp, 4)

    def test_singles_player2_lower(self):
        """Test singles match where player 2 has lower handicap"""
        p1_hcp, p2_hcp = HandicapCalculator.calculate_playing_handicap_singles(
            course_handicap_p1=15, course_handicap_p2=10)
        self.assertEqual(p1_hcp, 5)
        self.assertEqual(p2_hcp, 0)

    def test_singles_large_difference(self):
        """Test singles match with large handicap difference"""
        p1_hcp, p2_hcp = HandicapCalculator.calculate_playing_handicap_singles(
            course_handicap_p1=5, course_handicap_p2=25)
        self.assertEqual(p1_hcp, 0)
        self.assertEqual(p2_hcp, 20)

    def test_fourball_all_equal(self):
        """Test fourball with all players having equal handicaps"""
        result = HandicapCalculator.calculate_playing_handicap_fourball(
            course_handicap_p1=10,
            course_handicap_p2=10,
            course_handicap_p3=10,
            course_handicap_p4=10
        )
        self.assertEqual(result, (0, 0, 0, 0))

    def test_fourball_one_low_rest_equal(self):
        """Test fourball with one low handicap, rest equal"""
        result = HandicapCalculator.calculate_playing_handicap_fourball(
            course_handicap_p1=5,
            course_handicap_p2=10,
            course_handicap_p3=10,
            course_handicap_p4=10
        )
        # Lowest is 5, others get (10-5)*0.85 = 4.25 -> 4
        self.assertEqual(result, (0, 4, 4, 4))

    def test_fourball_varied_handicaps(self):
        """Test fourball with varied handicaps"""
        result = HandicapCalculator.calculate_playing_handicap_fourball(
            course_handicap_p1=8,
            course_handicap_p2=12,
            course_handicap_p3=10,
            course_handicap_p4=15
        )
        # Lowest is 8
        # p1: (8-8)*0.85 = 0
        # p2: (12-8)*0.85 = 3.4 -> 3
        # p3: (10-8)*0.85 = 1.7 -> 2
        # p4: (15-8)*0.85 = 5.95 -> 6
        self.assertEqual(result, (0, 3, 2, 6))

    def test_fourball_85_percent_allowance(self):
        """Test that fourball uses 85% allowance"""
        result = HandicapCalculator.calculate_playing_handicap_fourball(
            course_handicap_p1=10,
            course_handicap_p2=10,
            course_handicap_p3=10,
            course_handicap_p4=20
        )
        # Lowest is 10, p4 gets (20-10)*0.85 = 8.5 -> 9 (not 10)
        self.assertEqual(result[3], 9)

    def test_fourball_rounding(self):
        """Test fourball handicap rounding"""
        result = HandicapCalculator.calculate_playing_handicap_fourball(
            course_handicap_p1=10,
            course_handicap_p2=11,
            course_handicap_p3=12,
            course_handicap_p4=13
        )
        # Lowest is 10
        # p2: (11-10)*0.85 = 0.85 -> 1
        # p3: (12-10)*0.85 = 1.7 -> 2
        # p4: (13-10)*0.85 = 2.55 -> 3
        self.assertEqual(result, (0, 1, 2, 3))

    def test_complete_singles_calculation(self):
        """Test complete singles calculation from indexes"""
        result = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=10.5,
            handicap_index_p2=None,
            handicap_index_p3=15.2,
            handicap_index_p4=None,
            slope_rating=130,
            par=72
        )
        # Course handicaps: 10.5*(130/113)=12.08->12, 15.2*(130/113)=17.49->17
        # Playing handicaps: lower plays 0, higher plays 5
        self.assertEqual(len(result), 2)
        self.assertEqual(result, (0, 5))

    def test_complete_fourball_calculation(self):
        """Test complete fourball calculation from indexes"""
        result = HandicapCalculator.calculate_match_handicaps(
            match_type='Fourball',
            handicap_index_p1=8.0,
            handicap_index_p2=12.0,
            handicap_index_p3=10.0,
            handicap_index_p4=15.0,
            slope_rating=120,
            par=72
        )
        # Course handicaps with slope 120:
        # p1: 8*(120/113)=8.496->8 (rounds to 8)
        # p2: 12*(120/113)=12.74->13 (rounds to 13)
        # p3: 10*(120/113)=10.62->11 (rounds to 11)
        # p4: 15*(120/113)=15.93->16 (rounds to 16)
        # Lowest is 8 (p1)
        # Playing handicaps with 85% allowance (using standard round-half-up):
        # p1: 0
        # p2: (13-8)*0.85=4.25->4 (rounds up)
        # p3: (11-8)*0.85=2.55->3 (rounds up)
        # p4: (16-8)*0.85=6.8->7 (rounds up)
        self.assertEqual(len(result), 4)
        self.assertEqual(result, (0, 4, 3, 7))

    def test_invalid_match_type(self):
        """Test that invalid match type raises error"""
        with self.assertRaises(ValueError):
            HandicapCalculator.calculate_match_handicaps(
                match_type='Invalid',
                handicap_index_p1=10.0,
                handicap_index_p2=None,
                handicap_index_p3=10.0,
                handicap_index_p4=None,
                slope_rating=113,
                par=72
            )

    def test_scratch_player(self):
        """Test calculations with scratch player (0 handicap)"""
        # Singles
        result = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=0.0,
            handicap_index_p2=None,
            handicap_index_p3=10.0,
            handicap_index_p4=None,
            slope_rating=113,
            par=72
        )
        # Scratch player gets 0, other gets 10
        self.assertEqual(result, (0, 10))

    def test_plus_handicap(self):
        """Test calculations with plus handicap (negative)"""
        result = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=-2.0,
            handicap_index_p2=None,
            handicap_index_p3=5.0,
            handicap_index_p4=None,
            slope_rating=113,
            par=72
        )
        # p1: -2, p3: 5, difference is 7
        # p1 (better player with -2) plays off 0
        # p3 (higher handicap) receives 7 strokes
        self.assertEqual(result, (0, 7))

    def test_realistic_scenario_st_andrews(self):
        """Test realistic scenario: St Andrews Old Course"""
        # St Andrews Old Course: Par 72, Slope ~130
        result = HandicapCalculator.calculate_match_handicaps(
            match_type='Fourball',
            handicap_index_p1=12.5,
            handicap_index_p2=18.3,
            handicap_index_p3=9.2,
            handicap_index_p4=15.7,
            slope_rating=130,
            par=72
        )
        # Verify we get 4 handicaps for fourball
        self.assertEqual(len(result), 4)
        # Verify all are non-negative integers
        for hcp in result:
            self.assertGreaterEqual(hcp, 0)
            self.assertIsInstance(hcp, int)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
