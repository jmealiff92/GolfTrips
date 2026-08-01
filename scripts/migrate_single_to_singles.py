#!/usr/bin/env python3
"""
Migration script to update existing matches with MatchType='Single'
to the corrected value 'Singles', matching the app/UI naming.

Works against whichever backend get_database_service() resolves
(SQLite or Postgres, based on USE_POSTGRES/DATABASE_URL env vars).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_service import get_database_service


def migrate():
    db = get_database_service(os.getenv('SQLITE_DB_PATH', 'data/golf_trips.db'))

    is_postgres = type(db).__name__ == 'PostgresDatabaseService'
    placeholder = '%s' if is_postgres else '?'

    with db.get_connection() as conn:
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM matches WHERE MatchType = {placeholder}", ('Single',))
        count = c.fetchone()[0]

        if not count:
            print("No matches found with MatchType='Single'. Nothing to migrate.")
            return

        print(f"Found {count} match(es) with MatchType='Single'. Updating to 'Singles'...")
        c.execute(
            f"UPDATE matches SET MatchType = {placeholder} WHERE MatchType = {placeholder}",
            ('Singles', 'Single')
        )
        print(f"Updated {count} match(es).")


if __name__ == '__main__':
    migrate()
