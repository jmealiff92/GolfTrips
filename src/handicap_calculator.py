"""
Handicap calculation utilities for golf matches
Based on WHS (World Handicap System) as implemented by R&A
"""
from typing import Optional
from decimal import Decimal, ROUND_HALF_UP


class HandicapCalculator:
    """Calculate match handicaps for golf matches using WHS/R&A methods"""

    @staticmethod
    def _round_half_up(value: float) -> int:
        """
        Round using standard rounding (round half up) for golf handicaps
        Python's round() uses banker's rounding which isn't appropriate here
        """
        return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    @staticmethod
    def calculate_course_handicap(handicap_index: float, slope_rating: float, par: int) -> int:
        """
        Calculate course handicap using WHS formula (R&A)

        Formula: Course Handicap = Handicap Index × (Slope Rating / 113)

        The par adjustment is NOT included in the WHS course handicap calculation.
        Par is used separately for playing handicap calculations if needed.

        Args:
            handicap_index: Player's handicap index
            slope_rating: Course slope rating (typically 55-155, standard is 113)
            par: Course par (included for completeness but not used in basic calculation)

        Returns:
            Course handicap (rounded to nearest integer using standard rounding)
        """
        course_handicap = handicap_index * (slope_rating / 113)
        return HandicapCalculator._round_half_up(course_handicap)

    @staticmethod
    def calculate_playing_handicap_singles(course_handicap_p1: int,
                                          course_handicap_p2: int,
                                          allowance: float = 1.0) -> tuple[int, int]:
        """
        Calculate playing handicaps for singles match play (R&A WHS)

        In match play singles:
        - 100% allowance is standard
        - Lower handicap player receives 0 strokes
        - Higher handicap player receives the difference

        Args:
            course_handicap_p1: Course handicap for player 1
            course_handicap_p2: Course handicap for player 2
            allowance: Percentage allowance (default 1.0 = 100% for match play)

        Returns:
            Tuple of (player1_playing_handicap, player2_playing_handicap)
        """
        # Apply allowance
        ph1 = HandicapCalculator._round_half_up(course_handicap_p1 * allowance)
        ph2 = HandicapCalculator._round_half_up(course_handicap_p2 * allowance)

        # Calculate difference (lower handicap plays off scratch)
        diff = abs(ph1 - ph2)

        if ph1 < ph2:
            return (0, diff)
        elif ph2 < ph1:
            return (diff, 0)
        else:
            return (0, 0)

    @staticmethod
    def calculate_playing_handicap_fourball(course_handicap_p1: int,
                                           course_handicap_p2: int,
                                           course_handicap_p3: int,
                                           course_handicap_p4: int,
                                           allowance: float = 0.85) -> tuple[int, int, int, int]:
        """
        Calculate playing handicaps for fourball (better ball) match play (R&A WHS)

        In fourball match play:
        - 85% allowance is standard (per R&A recommendation)
        - Lowest course handicap plays off 0
        - Others receive allowanced difference from the lowest

        Args:
            course_handicap_p1: Course handicap for team 1 player 1
            course_handicap_p2: Course handicap for team 1 player 2
            course_handicap_p3: Course handicap for team 2 player 1
            course_handicap_p4: Course handicap for team 2 player 2
            allowance: Percentage allowance (default 0.85 = 85% for fourball)

        Returns:
            Tuple of (p1_playing_hcp, p2_playing_hcp, p3_playing_hcp, p4_playing_hcp)
        """
        # Find the lowest course handicap in the match
        lowest = min(course_handicap_p1, course_handicap_p2,
                    course_handicap_p3, course_handicap_p4)

        # Calculate playing handicap: (Course Handicap - Lowest) × Allowance
        p1_playing = HandicapCalculator._round_half_up((course_handicap_p1 - lowest) * allowance)
        p2_playing = HandicapCalculator._round_half_up((course_handicap_p2 - lowest) * allowance)
        p3_playing = HandicapCalculator._round_half_up((course_handicap_p3 - lowest) * allowance)
        p4_playing = HandicapCalculator._round_half_up((course_handicap_p4 - lowest) * allowance)

        return (p1_playing, p2_playing, p3_playing, p4_playing)

    @staticmethod
    def calculate_match_handicaps(match_type: str,
                                 handicap_index_p1: float,
                                 handicap_index_p2: Optional[float],
                                 handicap_index_p3: float,
                                 handicap_index_p4: Optional[float],
                                 slope_rating: float,
                                 par: int) -> tuple:
        """
        Complete calculation from handicap indexes to playing handicaps for match play

        Uses WHS (World Handicap System) as implemented by R&A:
        - Singles: 100% allowance
        - Fourball: 85% allowance

        Args:
            match_type: 'Single' or 'Fourball'
            handicap_index_p1: Player 1 handicap index (Team 1)
            handicap_index_p2: Player 2 handicap index (Team 1) - None for singles
            handicap_index_p3: Player 3 handicap index (Team 2)
            handicap_index_p4: Player 4 handicap index (Team 2) - None for singles
            slope_rating: Course slope rating
            par: Course par

        Returns:
            For Singles: (p1_match_hcp, p3_match_hcp)
            For Fourball: (p1_match_hcp, p2_match_hcp, p3_match_hcp, p4_match_hcp)
        """
        if match_type == 'Single':
            # Calculate course handicaps
            ch_p1 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p1, slope_rating, par)
            ch_p3 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p3, slope_rating, par)

            # Calculate playing handicaps with 100% allowance (match play standard)
            return HandicapCalculator.calculate_playing_handicap_singles(
                ch_p1, ch_p3, allowance=1.0)

        elif match_type == 'Fourball':
            # Calculate course handicaps for all players
            ch_p1 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p1, slope_rating, par)
            ch_p2 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p2, slope_rating, par)
            ch_p3 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p3, slope_rating, par)
            ch_p4 = HandicapCalculator.calculate_course_handicap(
                handicap_index_p4, slope_rating, par)

            # Calculate playing handicaps with 85% allowance (fourball standard)
            return HandicapCalculator.calculate_playing_handicap_fourball(
                ch_p1, ch_p2, ch_p3, ch_p4, allowance=0.85)

        else:
            raise ValueError(f"Unknown match type: {match_type}")
