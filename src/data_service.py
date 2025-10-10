"""
Data service layer that provides business logic and statistics
Built on top of DatabaseService
"""
import pandas as pd
from src.db_service import DatabaseService
from typing import Optional


class DataService:
    """Service layer for data processing and statistics"""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service
        self._df_cache = None
        self._cache_valid = False

    def invalidate_cache(self):
        """Invalidate the dataframe cache"""
        self._cache_valid = False

    @property
    def df(self) -> pd.DataFrame:
        """Get cached dataframe of all matches"""
        if not self._cache_valid or self._df_cache is None:
            self._df_cache = self.db.get_all_matches()
            self._cache_valid = True
        return self._df_cache

    @property
    def players(self) -> list:
        """Get list of all players from matches"""
        return self.db.get_players_from_matches()

    def get_players_list(self) -> list:
        """Get unique player names from matches"""
        return self.players

    def summarise_team_results(self) -> pd.DataFrame:
        """Calculate team summary by year"""
        df = self.df
        if df.empty:
            return pd.DataFrame()

        team_summary = df.groupby(['Year', 'Result']).size().unstack(fill_value=0)
        team_summary['Blue_Points'] = team_summary.get('Blue', 0) + team_summary.get('Half', 0) * 0.5
        team_summary['Red_Points'] = team_summary.get('Red', 0) + team_summary.get('Half', 0) * 0.5
        team_summary['Winner'] = team_summary.apply(
            lambda row: 'Blue' if row['Blue_Points'] > row['Red_Points']
            else 'Red' if row['Red_Points'] > row['Blue_Points']
            else 'Tie', axis=1
        )
        team_summary = team_summary.reset_index()[['Year', 'Blue_Points', 'Red_Points', 'Winner']]
        return team_summary

    def get_player_team(self, player_name: str, year: int) -> Optional[str]:
        """Get the team of a player for a specific year"""
        df = self.df
        player_team = df[(df['Year'] == year) & (
            (df['BluePlayer1'] == player_name) | (df['BluePlayer2'] == player_name) |
            (df['RedPlayer1'] == player_name) | (df['RedPlayer2'] == player_name)
        )]

        if player_team.empty:
            return None

        if player_team['BluePlayer1'].eq(player_name).any() or player_team['BluePlayer2'].eq(player_name).any():
            return 'Blue'
        elif player_team['RedPlayer1'].eq(player_name).any() or player_team['RedPlayer2'].eq(player_name).any():
            return 'Red'
        return None

    def build_results_per_player(self) -> pd.DataFrame:
        """Build detailed results for each player"""
        df = self.df
        if df.empty:
            return pd.DataFrame()

        results = []
        for player in self.players:
            player_matches = df[(df['BluePlayer1'] == player) | (df['BluePlayer2'] == player) |
                               (df['RedPlayer1'] == player) | (df['RedPlayer2'] == player)]
            for _, match in player_matches.iterrows():
                team = self.get_player_team(player, match['Year'])
                results.append({
                    'Player': player,
                    'Year': match['Year'],
                    'MatchNumber': match['MatchNumber'],
                    'Day': match['Day'],
                    'Result': self.get_match_result_for_player(match['Result'], team),
                    'Score': match['Score'],
                    'Team': team,
                    'MatchType': match['MatchType']
                })

        return pd.DataFrame(results)

    def get_match_result_for_player(self, result: str, player_team: str) -> str:
        """Convert match result to player perspective"""
        if result == 'Half':
            return 'Half'
        elif player_team == 'Blue' and result == 'Blue':
            return 'Win'
        elif player_team == 'Red' and result == 'Red':
            return 'Win'
        else:
            return 'Loss'

    def get_player_performance_all_players(self, match_type: Optional[str] = None) -> pd.DataFrame:
        """Get performance statistics for all players"""
        df = self.build_results_per_player()
        if df.empty:
            return pd.DataFrame()

        cols = ['Player', 'Matches', 'Wins', 'Losses', 'Halves', 'Points', 'Win %', 'PPG']

        # Filter by match type if specified
        if match_type:
            df = df[df['MatchType'] == match_type]

        # Group by player and calculate performance metrics
        player_stats = df.groupby('Player').agg(
            Matches=('Year', 'count'),
            Wins=('Result', lambda x: (x == 'Win').sum()),
            Losses=('Result', lambda x: (x == 'Loss').sum()),
            Halves=('Result', lambda x: (x == 'Half').sum()),
            Points=('Result', lambda x: (x == 'Win').sum() + 0.5 * (x == 'Half').sum())
        ).reset_index()

        player_stats['Win %'] = round(player_stats['Wins'] / player_stats['Matches'] * 100, 2)
        player_stats['PPG'] = round((player_stats['Wins'] + 0.5 * player_stats['Halves']) / player_stats['Matches'], 2)

        return player_stats[cols].sort_values(by='Points', ascending=False)

    def get_head_to_head_stats(self, player1: str, player2: str) -> dict:
        """Get head-to-head statistics between two players"""
        return self.db.get_head_to_head(player1, player2)

    def get_course_statistics(self) -> pd.DataFrame:
        """Get statistics by course"""
        return self.db.get_course_statistics()

    def get_player_course_performance(self, player_name: str) -> pd.DataFrame:
        """Get player's performance by course"""
        return self.db.get_player_course_performance(player_name)
