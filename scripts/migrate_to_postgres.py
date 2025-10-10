#!/usr/bin/env python
"""
Migrate data from SQLite to PostgreSQL/Supabase

This script:
1. Reads all data from SQLite database
2. Connects to PostgreSQL database
3. Creates tables if they don't exist
4. Migrates all data (players, handicaps, courses, matches)
5. Validates the migration

Usage:
    python scripts/migrate_to_postgres.py

Prerequisites:
    - .env file configured with DATABASE_URL
    - SQLite database exists at SQLITE_DB_PATH
"""

import os
import sys
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db_service import SQLiteDatabaseService
from src.db_service_postgres import PostgresDatabaseService

# Load environment variables
load_dotenv()


def migrate_data():
    """Migrate all data from SQLite to PostgreSQL"""

    print("=" * 60)
    print("Golf Match Data Migration: SQLite → PostgreSQL")
    print("=" * 60)
    print()

    # Get configuration
    sqlite_path = os.getenv('SQLITE_DB_PATH', 'data/golf_trips.db')
    postgres_url = os.getenv('DATABASE_URL')

    if not postgres_url:
        print("❌ ERROR: DATABASE_URL not set in .env file")
        print("Please add your PostgreSQL connection string to .env")
        print("Example: DATABASE_URL=postgresql://postgres:password@host:5432/database")
        sys.exit(1)

    # Verify SQLite database exists
    if not os.path.exists(sqlite_path):
        print(f"❌ ERROR: SQLite database not found at: {sqlite_path}")
        sys.exit(1)

    print(f"📂 Source (SQLite): {sqlite_path}")
    print(f"🌐 Target (PostgreSQL): {postgres_url.split('@')[1] if '@' in postgres_url else 'configured'}")
    print()

    # Connect to databases
    print("Connecting to databases...")
    try:
        sqlite_db = SQLiteDatabaseService(sqlite_path)
        postgres_db = PostgresDatabaseService(postgres_url)
        print("✅ Connected to both databases")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

    print()

    # Get data counts from SQLite
    print("📊 Analyzing source data...")
    try:
        sqlite_players = sqlite_db.get_all_players()
        sqlite_players_with_handicaps = sqlite_db.get_all_players_with_handicaps()
        sqlite_courses = sqlite_db.get_all_courses()
        sqlite_matches = sqlite_db.get_all_matches()

        # Count total handicaps
        total_handicaps = sum(len(p['handicaps']) for p in sqlite_players_with_handicaps)

        print(f"  Players: {len(sqlite_players)}")
        print(f"  Handicaps: {total_handicaps}")
        print(f"  Courses: {len(sqlite_courses)}")
        print(f"  Matches: {len(sqlite_matches)}")
        print()
    except Exception as e:
        print(f"❌ Failed to read source data: {e}")
        sys.exit(1)

    # Confirm migration
    response = input("🤔 Proceed with migration? This will overwrite existing PostgreSQL data. (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("❌ Migration cancelled")
        sys.exit(0)

    print()
    print("🚀 Starting migration...")
    print()

    # Track migration statistics
    stats = {
        'players': {'success': 0, 'failed': 0},
        'handicaps': {'success': 0, 'failed': 0},
        'courses': {'success': 0, 'failed': 0},
        'matches': {'success': 0, 'failed': 0}
    }

    # Migrate Players
    print("1️⃣  Migrating players...")
    for player in sqlite_players:
        try:
            postgres_db.add_player(player)
            stats['players']['success'] += 1
        except Exception as e:
            print(f"   ⚠️  Failed to migrate player '{player}': {e}")
            stats['players']['failed'] += 1
    print(f"   ✅ Players: {stats['players']['success']} succeeded, {stats['players']['failed']} failed")
    print()

    # Migrate Handicaps
    print("2️⃣  Migrating handicaps...")
    for player_data in sqlite_players_with_handicaps:
        player_name = player_data['name']
        for year, handicap_index in player_data['handicaps'].items():
            try:
                postgres_db.add_or_update_handicap(player_name, year, handicap_index)
                stats['handicaps']['success'] += 1
            except Exception as e:
                print(f"   ⚠️  Failed to migrate handicap for '{player_name}' ({year}): {e}")
                stats['handicaps']['failed'] += 1
    print(f"   ✅ Handicaps: {stats['handicaps']['success']} succeeded, {stats['handicaps']['failed']} failed")
    print()

    # Migrate Courses
    print("3️⃣  Migrating courses...")
    for course in sqlite_courses:
        try:
            postgres_db.add_course(
                course['name'],
                course['par'],
                course['slope_rating'],
                course['course_rating']
            )
            stats['courses']['success'] += 1
        except Exception as e:
            print(f"   ⚠️  Failed to migrate course '{course['name']}': {e}")
            stats['courses']['failed'] += 1
    print(f"   ✅ Courses: {stats['courses']['success']} succeeded, {stats['courses']['failed']} failed")
    print()

    # Migrate Matches
    print("4️⃣  Migrating matches...")
    for _, match in sqlite_matches.iterrows():
        try:
            postgres_db.add_match(
                year=int(match['Year']),
                day=int(match['Day']),
                match_number=int(match['MatchNumber']),
                course=match['Course'],
                match_type=match['MatchType'],
                blue_player1=match['BluePlayer1'],
                blue_player1_handicap=float(match['BluePlayer1MatchHandicap']),
                blue_player2=match['BluePlayer2'] if match['BluePlayer2'] else None,
                blue_player2_handicap=float(match['BluePlayer2MatchHandicap']) if match['BluePlayer2MatchHandicap'] else None,
                red_player1=match['RedPlayer1'],
                red_player1_handicap=float(match['RedPlayer1MatchHandicap']),
                red_player2=match['RedPlayer2'] if match['RedPlayer2'] else None,
                red_player2_handicap=float(match['RedPlayer2MatchHandicap']) if match['RedPlayer2MatchHandicap'] else None,
                result=match['Result'] if match['Result'] else None,
                score=match['Score'] if match['Score'] else None
            )
            stats['matches']['success'] += 1
        except Exception as e:
            print(f"   ⚠️  Failed to migrate match {match['Year']}-{match['Day']}-{match['MatchNumber']}: {e}")
            stats['matches']['failed'] += 1
    print(f"   ✅ Matches: {stats['matches']['success']} succeeded, {stats['matches']['failed']} failed")
    print()

    # Validation
    print("=" * 60)
    print("🔍 Validating migration...")
    print()

    try:
        postgres_players = postgres_db.get_all_players()
        postgres_courses = postgres_db.get_all_courses()
        postgres_matches = postgres_db.get_all_matches()
        postgres_players_with_handicaps = postgres_db.get_all_players_with_handicaps()

        postgres_handicaps = sum(len(p['handicaps']) for p in postgres_players_with_handicaps)

        print("Source (SQLite) → Target (PostgreSQL):")
        print(f"  Players:   {len(sqlite_players):3d} → {len(postgres_players):3d} {'✅' if len(sqlite_players) == len(postgres_players) else '❌'}")
        print(f"  Handicaps: {total_handicaps:3d} → {postgres_handicaps:3d} {'✅' if total_handicaps == postgres_handicaps else '❌'}")
        print(f"  Courses:   {len(sqlite_courses):3d} → {len(postgres_courses):3d} {'✅' if len(sqlite_courses) == len(postgres_courses) else '❌'}")
        print(f"  Matches:   {len(sqlite_matches):3d} → {len(postgres_matches):3d} {'✅' if len(sqlite_matches) == len(postgres_matches) else '❌'}")
        print()

        # Check for any failures
        total_failed = sum(s['failed'] for s in stats.values())

        if total_failed == 0:
            print("=" * 60)
            print("🎉 Migration completed successfully!")
            print("=" * 60)
            print()
            print("Next steps:")
            print("1. Update your .env file:")
            print("   USE_POSTGRES=true")
            print("2. Restart the application:")
            print("   python src/app.py")
            print()
        else:
            print("=" * 60)
            print(f"⚠️  Migration completed with {total_failed} errors")
            print("=" * 60)
            print("Please review the errors above and retry if necessary.")
            print()

    except Exception as e:
        print(f"❌ Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        migrate_data()
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
