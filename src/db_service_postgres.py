import pandas as pd
from typing import Optional, List, Dict, Tuple
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import DictCursor
from src.db_service_base import DatabaseServiceBase
import warnings

# Suppress pandas SQLAlchemy warning for psycopg2 connections
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy.*')


class PostgresDatabaseService(DatabaseServiceBase):
    """PostgreSQL implementation of database operations for Supabase"""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.init_db()

    def _normalize_column_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize PostgreSQL lowercase column names to match expected capitalized format.
        PostgreSQL returns columns in lowercase, but pandas code expects capitalized names.
        """
        if df.empty:
            return df

        # Define the mapping from lowercase to expected capitalized names
        column_mapping = {
            'year': 'Year',
            'day': 'Day',
            'matchnumber': 'MatchNumber',
            'course': 'Course',
            'matchtype': 'MatchType',
            'blueplayer1': 'BluePlayer1',
            'blueplayer1matchhandicap': 'BluePlayer1MatchHandicap',
            'blueplayer2': 'BluePlayer2',
            'blueplayer2matchhandicap': 'BluePlayer2MatchHandicap',
            'redplayer1': 'RedPlayer1',
            'redplayer1matchhandicap': 'RedPlayer1MatchHandicap',
            'redplayer2': 'RedPlayer2',
            'redplayer2matchhandicap': 'RedPlayer2MatchHandicap',
            'result': 'Result',
            'score': 'Score',
            'created_at': 'created_at',
            'updated_at': 'updated_at',
            'matches': 'Matches',
            'blue_wins': 'Blue_Wins',
            'red_wins': 'Red_Wins',
            'halves': 'Halves',
            'wins': 'Wins',
            'losses': 'Losses',
            'points': 'Points',
            'ppg': 'PPG'
        }

        # Rename columns that exist in the dataframe and have a mapping
        rename_dict = {col: column_mapping[col] for col in df.columns if col in column_mapping}
        return df.rename(columns=rename_dict)

    @contextmanager
    def get_connection(self):
        """Context manager for PostgreSQL connections"""
        conn = psycopg2.connect(self.database_url, cursor_factory=DictCursor)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_db(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            c = conn.cursor()

            # Players table
            c.execute('''CREATE TABLE IF NOT EXISTS players
                         (name TEXT PRIMARY KEY,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

            # Handicaps table
            c.execute('''CREATE TABLE IF NOT EXISTS handicaps
                         (name TEXT,
                          year INTEGER,
                          handicap_index REAL,
                          PRIMARY KEY (name, year),
                          FOREIGN KEY (name) REFERENCES players(name))''')

            # Courses table
            c.execute('''CREATE TABLE IF NOT EXISTS courses
                         (name TEXT PRIMARY KEY,
                          par INTEGER,
                          slope_rating REAL,
                          course_rating REAL,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

            # Matches table
            c.execute('''
                CREATE TABLE IF NOT EXISTS matches (
                    Year INTEGER,
                    Day INTEGER,
                    MatchNumber INTEGER,
                    Course TEXT,
                    MatchType TEXT,
                    BluePlayer1 TEXT,
                    BluePlayer1MatchHandicap REAL,
                    BluePlayer2 TEXT,
                    BluePlayer2MatchHandicap REAL,
                    RedPlayer1 TEXT,
                    RedPlayer1MatchHandicap REAL,
                    RedPlayer2 TEXT,
                    RedPlayer2MatchHandicap REAL,
                    Result TEXT,
                    Score TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (Year, Day, MatchNumber),
                    FOREIGN KEY (Course) REFERENCES courses(name)
                )
            ''')

    # ============ Match Operations ============

    def add_match(self, year: int, day: int, match_number: int, course: str,
                  match_type: str, blue_player1: str, blue_player1_handicap: float,
                  blue_player2: Optional[str], blue_player2_handicap: Optional[float],
                  red_player1: str, red_player1_handicap: float,
                  red_player2: Optional[str], red_player2_handicap: Optional[float],
                  result: Optional[str] = None, score: Optional[str] = None) -> bool:
        """Add a new match to the database"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()

                # Add players if they don't exist
                for player in [blue_player1, blue_player2, red_player1, red_player2]:
                    if player and player not in ['N/A', 'Ghost', '']:
                        self._add_player_if_not_exists(player, c)

                # Insert match
                c.execute('''
                    INSERT INTO matches (Year, Day, MatchNumber, Course, MatchType,
                                        BluePlayer1, BluePlayer1MatchHandicap,
                                        BluePlayer2, BluePlayer2MatchHandicap,
                                        RedPlayer1, RedPlayer1MatchHandicap,
                                        RedPlayer2, RedPlayer2MatchHandicap,
                                        Result, Score)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ''', (year, day, match_number, course, match_type,
                      blue_player1, blue_player1_handicap,
                      blue_player2 or '', blue_player2_handicap or 0,
                      red_player1, red_player1_handicap,
                      red_player2 or '', red_player2_handicap or 0,
                      result or '', score or ''))
                return True
        except psycopg2.IntegrityError:
            return False

    def update_match_result(self, year: int, day: int, match_number: int,
                           result: str, score: str) -> bool:
        """Update match result and score"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                UPDATE matches
                SET Result = %s, Score = %s, updated_at = CURRENT_TIMESTAMP
                WHERE Year = %s AND Day = %s AND MatchNumber = %s
            ''', (result, score, year, day, match_number))
            return c.rowcount > 0

    def delete_match(self, year: int, day: int, match_number: int) -> bool:
        """Delete a match"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                DELETE FROM matches
                WHERE Year = %s AND Day = %s AND MatchNumber = %s
            ''', (year, day, match_number))
            return c.rowcount > 0

    def check_match_exists(self, year: int, day: int, match_number: int) -> bool:
        """Check if a match already exists"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT COUNT(*) FROM matches
                WHERE Year = %s AND Day = %s AND MatchNumber = %s
            ''', (year, day, match_number))
            count = c.fetchone()[0]
            return count > 0

    def get_all_matches(self) -> pd.DataFrame:
        """Get all matches as a DataFrame"""
        with self.get_connection() as conn:
            df = pd.read_sql_query('SELECT * FROM matches ORDER BY Year DESC, Day, MatchNumber', conn)
            # Normalize column names to match expected capitalized format
            return self._normalize_column_names(df)

    def get_matches_by_year(self, year: int) -> pd.DataFrame:
        """Get matches for a specific year"""
        with self.get_connection() as conn:
            df = pd.read_sql_query('SELECT * FROM matches WHERE Year = %s ORDER BY Day, MatchNumber',
                                    conn, params=(year,))
            # Normalize column names to match expected capitalized format
            return self._normalize_column_names(df)

    def get_next_match_number(self, year: int, day: int) -> int:
        """Get the next available match number for a given year and day"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT MAX(MatchNumber) FROM matches WHERE Year = %s AND Day = %s', (year, day))
            result = c.fetchone()[0]
            return (result + 1) if result else 1

    # ============ Player Operations ============

    def _add_player_if_not_exists(self, name: str, cursor):
        """Add player if they don't exist (internal method)"""
        cursor.execute('INSERT INTO players (name) VALUES (%s) ON CONFLICT (name) DO NOTHING', (name,))

    def add_player(self, name: str) -> bool:
        """Add a new player"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                self._add_player_if_not_exists(name, c)
                return True
        except Exception:
            return False

    def get_all_players(self) -> List[str]:
        """Get list of all players"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT name FROM players ORDER BY name')
            return [row[0] for row in c.fetchall()]

    def get_players_from_matches(self) -> List[str]:
        """Get unique players from matches table"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                SELECT DISTINCT player FROM (
                    SELECT BluePlayer1 as player FROM matches
                    UNION SELECT BluePlayer2 FROM matches
                    UNION SELECT RedPlayer1 FROM matches
                    UNION SELECT RedPlayer2 FROM matches
                ) AS all_players WHERE player != '' AND player IS NOT NULL
                  AND player NOT IN ('N/A', 'Ghost')
                ORDER BY player
            ''')
            return [row[0] for row in c.fetchall()]

    def get_player_with_handicaps(self, name: str) -> Optional[Dict]:
        """Get player with all their handicaps by year"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM players WHERE name = %s', (name,))
            player = c.fetchone()
            if not player:
                return None

            c.execute('SELECT year, handicap_index FROM handicaps WHERE name = %s ORDER BY year DESC', (name,))
            handicaps = {row[0]: row[1] for row in c.fetchall()}

            return {
                'name': name,
                'handicaps': handicaps
            }

    def get_all_players_with_handicaps(self) -> List[Dict]:
        """Get all players with their handicaps"""
        with self.get_connection() as conn:
            query = '''
                SELECT p.name, h.year, h.handicap_index
                FROM players p
                LEFT JOIN handicaps h ON p.name = h.name
                ORDER BY p.name, h.year DESC
            '''
            df = pd.read_sql_query(query, conn)

            players_dict = {}
            for _, row in df.iterrows():
                name = row['name']
                if name not in players_dict:
                    players_dict[name] = {'name': name, 'handicaps': {}}
                if pd.notna(row['year']):
                    players_dict[name]['handicaps'][int(row['year'])] = row['handicap_index']

            return list(players_dict.values())

    # ============ Handicap Operations ============

    def add_or_update_handicap(self, name: str, year: int, handicap_index: float) -> bool:
        """Add or update a player's handicap for a specific year"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                # Ensure player exists
                self._add_player_if_not_exists(name, c)

                c.execute('''
                    INSERT INTO handicaps (name, year, handicap_index)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(name, year)
                    DO UPDATE SET handicap_index = EXCLUDED.handicap_index
                ''', (name, year, handicap_index))
                return True
        except Exception as e:
            print(f"Error adding/updating handicap: {e}")
            return False

    def get_player_handicap(self, name: str, year: int) -> Optional[float]:
        """Get a player's handicap index for a specific year"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT handicap_index FROM handicaps WHERE name = %s AND year = %s', (name, year))
            result = c.fetchone()
            return result[0] if result else None

    def delete_handicap(self, name: str, year: int) -> bool:
        """Delete a player's handicap for a specific year"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM handicaps WHERE name = %s AND year = %s', (name, year))
            return c.rowcount > 0

    # ============ Course Operations ============

    def add_course(self, name: str, par: int, slope_rating: float, course_rating: float) -> bool:
        """Add a new course"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute('''
                    INSERT INTO courses (name, par, slope_rating, course_rating)
                    VALUES (%s, %s, %s, %s)
                ''', (name, par, slope_rating, course_rating))
                return True
        except psycopg2.IntegrityError:
            return False

    def update_course(self, name: str, par: int, slope_rating: float, course_rating: float) -> bool:
        """Update an existing course"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('''
                UPDATE courses
                SET par = %s, slope_rating = %s, course_rating = %s, updated_at = CURRENT_TIMESTAMP
                WHERE name = %s
            ''', (par, slope_rating, course_rating, name))
            return c.rowcount > 0

    def get_course(self, name: str) -> Optional[Dict]:
        """Get course details"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT * FROM courses WHERE name = %s', (name,))
            row = c.fetchone()
            if row:
                return {
                    'name': row['name'],
                    'par': row['par'],
                    'slope_rating': row['slope_rating'],
                    'course_rating': row['course_rating']
                }
            return None

    def get_all_courses(self) -> List[Dict]:
        """Get all courses"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT name, par, slope_rating, course_rating FROM courses ORDER BY name')
            return [{'name': row[0], 'par': row[1], 'slope_rating': row[2], 'course_rating': row[3]}
                    for row in c.fetchall()]

    def delete_course(self, name: str) -> bool:
        """Delete a course (only if not used in matches)"""
        try:
            with self.get_connection() as conn:
                c = conn.cursor()
                c.execute('DELETE FROM courses WHERE name = %s', (name,))
                return c.rowcount > 0
        except psycopg2.IntegrityError:
            return False

    # ============ Statistics Operations ============

    def get_player_matches(self, player_name: str) -> pd.DataFrame:
        """Get all matches for a specific player"""
        with self.get_connection() as conn:
            query = '''
                SELECT * FROM matches
                WHERE BluePlayer1 = %s OR BluePlayer2 = %s
                   OR RedPlayer1 = %s OR RedPlayer2 = %s
                ORDER BY Year DESC, Day, MatchNumber
            '''
            df = pd.read_sql_query(query, conn, params=(player_name, player_name, player_name, player_name))
            # Normalize column names to match expected capitalized format
            return self._normalize_column_names(df)

    def get_head_to_head(self, player1: str, player2: str) -> Dict:
        """Get head-to-head statistics between two players"""
        with self.get_connection() as conn:
            query = '''
                SELECT * FROM matches
                WHERE (BluePlayer1 IN (%s, %s) OR BluePlayer2 IN (%s, %s))
                  AND (RedPlayer1 IN (%s, %s) OR RedPlayer2 IN (%s, %s))
            '''
            df = pd.read_sql_query(query, conn,
                                  params=(player1, player2, player1, player2,
                                         player1, player2, player1, player2))

            # Normalize column names to match expected capitalized format
            df = self._normalize_column_names(df)

            if df.empty:
                return {'matches': 0, 'player1_wins': 0, 'player2_wins': 0, 'halves': 0}

            player1_wins = 0
            player2_wins = 0
            halves = 0

            for _, match in df.iterrows():
                # Determine which team each player is on
                player1_team = 'Blue' if player1 in [match['BluePlayer1'], match['BluePlayer2']] else 'Red'
                player2_team = 'Red' if player1_team == 'Blue' else 'Blue'

                result = match['Result']
                if result == 'Half':
                    halves += 1
                elif result == player1_team:
                    player1_wins += 1
                elif result == player2_team:
                    player2_wins += 1

            return {
                'matches': len(df),
                'player1_wins': player1_wins,
                'player2_wins': player2_wins,
                'halves': halves
            }

    def get_course_statistics(self) -> pd.DataFrame:
        """Get statistics by course"""
        with self.get_connection() as conn:
            query = '''
                SELECT Course,
                       COUNT(*) as Matches,
                       SUM(CASE WHEN Result = 'Blue' THEN 1 ELSE 0 END) as Blue_Wins,
                       SUM(CASE WHEN Result = 'Red' THEN 1 ELSE 0 END) as Red_Wins,
                       SUM(CASE WHEN Result = 'Half' THEN 1 ELSE 0 END) as Halves
                FROM matches
                GROUP BY Course
                ORDER BY Matches DESC
            '''
            df = pd.read_sql_query(query, conn)
            # Normalize column names to match expected capitalized format
            return self._normalize_column_names(df)

    def get_player_course_performance(self, player_name: str) -> pd.DataFrame:
        """Get a player's performance by course"""
        with self.get_connection() as conn:
            query = '''
                SELECT
                    Course,
                    COUNT(*) as Matches,
                    SUM(CASE
                        WHEN (BluePlayer1 = %s OR BluePlayer2 = %s) AND Result = 'Blue' THEN 1
                        WHEN (RedPlayer1 = %s OR RedPlayer2 = %s) AND Result = 'Red' THEN 1
                        ELSE 0
                    END) as Wins,
                    SUM(CASE WHEN Result = 'Half' THEN 1 ELSE 0 END) as Halves,
                    SUM(CASE
                        WHEN (BluePlayer1 = %s OR BluePlayer2 = %s) AND Result = 'Red' THEN 1
                        WHEN (RedPlayer1 = %s OR RedPlayer2 = %s) AND Result = 'Blue' THEN 1
                        ELSE 0
                    END) as Losses
                FROM matches
                WHERE BluePlayer1 = %s OR BluePlayer2 = %s OR RedPlayer1 = %s OR RedPlayer2 = %s
                GROUP BY Course
                ORDER BY Matches DESC
            '''
            params = tuple([player_name] * 12)
            df = pd.read_sql_query(query, conn, params=params)
            # Normalize column names to match expected capitalized format
            df = self._normalize_column_names(df)
            df['Points'] = df['Wins'] + (df['Halves'] * 0.5)
            df['PPG'] = (df['Points'] / df['Matches']).round(2)
            return df

    def get_years_list(self) -> List[int]:
        """Get list of all years with matches"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT DISTINCT Year FROM matches ORDER BY Year DESC')
            return [row[0] for row in c.fetchall()]

    def get_courses_list(self) -> List[str]:
        """Get list of all courses"""
        with self.get_connection() as conn:
            c = conn.cursor()
            c.execute('SELECT DISTINCT Course FROM matches ORDER BY Course')
            return [row[0] for row in c.fetchall()]

    # ============ Migration Utility ============

    def import_from_csv(self, csv_path: str) -> Tuple[int, int]:
        """Import matches from CSV file. Returns (successful, failed) counts"""
        import csv
        successful = 0
        failed = 0

        with open(csv_path, 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    self.add_match(
                        year=int(row['Year']),
                        day=int(row['Day']),
                        match_number=int(row['MatchNumber']),
                        course=row['Course'],
                        match_type=row['MatchType'],
                        blue_player1=row['BluePlayer1'],
                        blue_player1_handicap=float(row['BluePlayer1MatchHandicap']) if row['BluePlayer1MatchHandicap'] else 0,
                        blue_player2=row['BluePlayer2'] if row['BluePlayer2'] else None,
                        blue_player2_handicap=float(row['BluePlayer2MatchHandicap']) if row['BluePlayer2MatchHandicap'] else None,
                        red_player1=row['RedPlayer1'],
                        red_player1_handicap=float(row['RedPlayer1MatchHandicap']) if row['RedPlayer1MatchHandicap'] else 0,
                        red_player2=row['RedPlayer2'] if row['RedPlayer2'] else None,
                        red_player2_handicap=float(row['RedPlayer2MatchHandicap']) if row['RedPlayer2MatchHandicap'] else None,
                        result=row['Result'],
                        score=row['Score']
                    )
                    successful += 1
                except Exception as e:
                    print(f"Failed to import row: {e}")
                    failed += 1

        return successful, failed
