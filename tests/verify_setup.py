#!/usr/bin/env python3
"""
Verification script to check that all new features are properly set up
"""
from db_service import DatabaseService
from handicap_calculator import HandicapCalculator

def main():
    print("=" * 60)
    print("Golf Trips Application - Setup Verification")
    print("=" * 60)

    # Initialize database service
    print("\n1. Testing Database Connection...")
    try:
        db = DatabaseService('golf_trips.db')
        print("   ✓ Database connection successful")
    except Exception as e:
        print(f"   ✗ Database connection failed: {e}")
        return

    # Test players
    print("\n2. Testing Player Management...")
    try:
        players = db.get_all_players_with_handicaps()
        print(f"   ✓ Found {len(players)} players")

        # Show sample players with handicaps
        players_with_handicaps = [p for p in players if p['handicaps']]
        if players_with_handicaps:
            print(f"   ✓ {len(players_with_handicaps)} players have handicaps")
            sample = players_with_handicaps[0]
            print(f"   Example: {sample['name']}")
            for year, hcp in sorted(sample['handicaps'].items(), reverse=True):
                print(f"     - {year}: {hcp}")
        else:
            print("   ⚠ No players with handicaps found")
    except Exception as e:
        print(f"   ✗ Player management test failed: {e}")

    # Test courses
    print("\n3. Testing Course Management...")
    try:
        courses = db.get_all_courses()
        print(f"   ✓ Found {len(courses)} courses")
        if courses:
            sample = courses[0]
            print(f"   Example: {sample['name']}")
            print(f"     Par: {sample['par']}, Slope: {sample['slope_rating']}, Rating: {sample['course_rating']}")
        else:
            print("   ⚠ No courses found")
    except Exception as e:
        print(f"   ✗ Course management test failed: {e}")

    # Test handicap calculator
    print("\n4. Testing Handicap Calculator...")
    try:
        # Test singles calculation
        handicaps = HandicapCalculator.calculate_match_handicaps(
            match_type='Single',
            handicap_index_p1=10.0,
            handicap_index_p2=None,
            handicap_index_p3=15.0,
            handicap_index_p4=None,
            slope_rating=130,
            par=72
        )
        print(f"   ✓ Singles calculation: Player 1 gets {handicaps[0]} strokes, Player 2 gets {handicaps[1]} strokes")

        # Test fourball calculation
        handicaps = HandicapCalculator.calculate_match_handicaps(
            match_type='Fourball',
            handicap_index_p1=10.0,
            handicap_index_p2=15.0,
            handicap_index_p3=8.0,
            handicap_index_p4=12.0,
            slope_rating=130,
            par=72
        )
        print(f"   ✓ Fourball calculation: {handicaps}")
    except Exception as e:
        print(f"   ✗ Handicap calculator test failed: {e}")

    # Test match operations
    print("\n5. Testing Match Operations...")
    try:
        matches = db.get_all_matches()
        print(f"   ✓ Found {len(matches)} matches in database")

        # Check for courses in matches
        if not matches.empty:
            courses_in_matches = matches['Course'].unique()
            print(f"   ✓ Matches played at {len(courses_in_matches)} different courses")
    except Exception as e:
        print(f"   ✗ Match operations test failed: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("Setup Verification Complete!")
    print("=" * 60)
    print("\nTo start the application, run:")
    print("  source .venv/bin/activate")
    print("  python dash_app_new.py")
    print("\nThen visit: http://localhost:8050")
    print("\nNew pages available:")
    print("  - /manage-players  (Player & Handicap Management)")
    print("  - /manage-courses  (Course Management)")
    print("  - /add-match       (Enhanced with auto-calculation)")
    print("  - /edit-matches    (Edit Match Results)")
    print("=" * 60)

if __name__ == '__main__':
    main()
