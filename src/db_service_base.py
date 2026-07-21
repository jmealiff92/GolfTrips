from abc import ABC, abstractmethod
import pandas as pd
from typing import Optional, List, Dict, Tuple


class DatabaseServiceBase(ABC):
    """Abstract base class for database operations"""

    @abstractmethod
    def get_connection(self):
        """Get database connection context manager"""
        pass

    @abstractmethod
    def init_db(self):
        """Initialize database schema"""
        pass

    # Match Operations
    @abstractmethod
    def add_match(self, year: int, day: int, match_number: int, course: str,
                  match_type: str, blue_player1: str, blue_player1_handicap: float,
                  blue_player2: Optional[str], blue_player2_handicap: Optional[float],
                  red_player1: str, red_player1_handicap: float,
                  red_player2: Optional[str], red_player2_handicap: Optional[float],
                  result: Optional[str] = None, score: Optional[str] = None) -> bool:
        pass

    @abstractmethod
    def update_match_result(self, year: int, day: int, match_number: int,
                           result: str, score: str) -> bool:
        pass

    @abstractmethod
    def delete_match(self, year: int, day: int, match_number: int) -> bool:
        pass

    @abstractmethod
    def check_match_exists(self, year: int, day: int, match_number: int) -> bool:
        pass

    @abstractmethod
    def get_all_matches(self) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_matches_by_year(self, year: int) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_next_match_number(self, year: int, day: int) -> int:
        pass

    # Player Operations
    @abstractmethod
    def add_player(self, name: str) -> bool:
        pass

    @abstractmethod
    def get_all_players(self) -> List[str]:
        pass

    @abstractmethod
    def get_players_from_matches(self) -> List[str]:
        pass

    @abstractmethod
    def get_player_with_handicaps(self, name: str) -> Optional[Dict]:
        pass

    @abstractmethod
    def get_all_players_with_handicaps(self) -> List[Dict]:
        pass

    # Handicap Operations
    @abstractmethod
    def add_or_update_handicap(self, name: str, year: int, handicap_index: float) -> bool:
        pass

    @abstractmethod
    def get_player_handicap(self, name: str, year: int) -> Optional[float]:
        pass

    @abstractmethod
    def delete_handicap(self, name: str, year: int) -> bool:
        pass

    # Team Operations
    @abstractmethod
    def assign_player_team(self, name: str, year: int, team: str) -> bool:
        pass

    @abstractmethod
    def get_player_team_assignment(self, name: str, year: int) -> Optional[str]:
        pass

    @abstractmethod
    def get_team_assignments_by_year(self, year: int) -> List[Dict]:
        pass

    @abstractmethod
    def delete_player_team(self, name: str, year: int) -> bool:
        pass

    @abstractmethod
    def get_team_years_list(self) -> List[int]:
        pass

    # Course Operations
    @abstractmethod
    def add_course(self, name: str, par: int, slope_rating: float, course_rating: float) -> bool:
        pass

    @abstractmethod
    def update_course(self, name: str, par: int, slope_rating: float, course_rating: float) -> bool:
        pass

    @abstractmethod
    def get_course(self, name: str) -> Optional[Dict]:
        pass

    @abstractmethod
    def get_all_courses(self) -> List[Dict]:
        pass

    @abstractmethod
    def delete_course(self, name: str) -> bool:
        pass

    # Statistics Operations
    @abstractmethod
    def get_player_matches(self, player_name: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_head_to_head(self, player1: str, player2: str) -> Dict:
        pass

    @abstractmethod
    def get_course_statistics(self) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_player_course_performance(self, player_name: str) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_years_list(self) -> List[int]:
        pass

    @abstractmethod
    def get_courses_list(self) -> List[str]:
        pass

    # Migration Utility
    @abstractmethod
    def import_from_csv(self, csv_path: str) -> Tuple[int, int]:
        pass
