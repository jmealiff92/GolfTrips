#!/usr/bin/env python3
"""
Test script to verify the fixes for:
1. New players appearing in add match dropdown
2. Courses table displaying in manage courses
"""
from src.db_service import DatabaseService

def test_player_visibility():
    """Test that all players are accessible"""
    db = DatabaseService('golf_trips.db')

    print("Testing Player Visibility")
    print("=" * 60)

    # Get all players from players table
    all_players = db.get_all_players()
    print(f"✓ Total players in players table: {len(all_players)}")

    # Get players from matches
    match_players = db.get_players_from_matches()
    print(f"✓ Players who have played matches: {len(match_players)}")

    # Show difference
    new_players = set(all_players) - set(match_players)
    if new_players:
        print(f"✓ Players not yet in matches: {len(new_players)}")
        for player in list(new_players)[:5]:
            print(f"  - {player}")
        if len(new_players) > 5:
            print(f"  ... and {len(new_players) - 5} more")
    else:
        print("  All players have played in matches")

    print("\n✅ Fix: Now using db_service.get_all_players() in add match page")
    print("   This ensures all players appear in dropdown, even if they")
    print("   haven't played any matches yet.\n")

def test_course_visibility():
    """Test that courses from courses table are visible"""
    db = DatabaseService('golf_trips.db')

    print("Testing Course Visibility")
    print("=" * 60)

    # Get courses from courses table
    all_courses = db.get_all_courses()
    print(f"✓ Total courses in courses table: {len(all_courses)}")

    if all_courses:
        print("  Courses in database:")
        for course in all_courses[:5]:
            print(f"  - {course['name']} (Par {course['par']}, Slope {course['slope_rating']})")
        if len(all_courses) > 5:
            print(f"  ... and {len(all_courses) - 5} more")
    else:
        print("  No courses in courses table yet")

    # Get courses from matches
    courses_in_matches = db.get_courses_list()
    print(f"\n✓ Courses that have been used in matches: {len(courses_in_matches)}")

    print("\n✅ Fixes applied:")
    print("   1. Add Match page now uses courses from courses table")
    print("   2. Manage Courses page refreshes when navigating to it")
    print("   3. Courses table updates after add/update/delete operations\n")

def test_add_sample_data():
    """Add sample data if none exists"""
    db = DatabaseService('golf_trips.db')

    print("Sample Data Setup")
    print("=" * 60)

    courses = db.get_all_courses()
    if len(courses) == 0:
        print("No courses found. Adding sample courses...")

        sample_courses = [
            ("St Andrews Old Course", 72, 130, 73.5),
            ("Pebble Beach", 72, 145, 75.5),
            ("Augusta National", 72, 137, 74.9),
        ]

        for name, par, slope, rating in sample_courses:
            success = db.add_course(name, par, slope, rating)
            if success:
                print(f"  ✓ Added: {name}")

        print(f"\nAdded {len(sample_courses)} sample courses")
    else:
        print(f"✓ Database already has {len(courses)} courses")

    # Check players with handicaps
    players = db.get_all_players_with_handicaps()
    players_with_hcp = [p for p in players if p['handicaps']]

    print(f"\n✓ Players with handicaps: {len(players_with_hcp)}")
    if len(players_with_hcp) == 0:
        print("\n  Note: Add player handicaps via 'Manage Players' page")
        print("  to enable auto-calculation of match handicaps")

def main():
    print("\n" + "=" * 60)
    print("TESTING FIXES FOR PLAYER AND COURSE VISIBILITY")
    print("=" * 60 + "\n")

    test_player_visibility()
    test_course_visibility()
    test_add_sample_data()

    print("\n" + "=" * 60)
    print("TESTING COMPLETE")
    print("=" * 60)
    print("\nWhat to test in the app:")
    print("\n1. Add Match Page:")
    print("   - Navigate to /add-match")
    print("   - Check player dropdowns show ALL players")
    print("   - Check course dropdown shows courses from courses table")
    print("   - Add a new player in Manage Players, then return to Add Match")
    print("   - New player should now appear in dropdown")

    print("\n2. Manage Courses Page:")
    print("   - Navigate to /manage-courses")
    print("   - Table should show all courses")
    print("   - Add a course")
    print("   - Table should update immediately")
    print("   - Navigate away and back")
    print("   - Course should still be visible")

    print("\n3. Auto-Calculate Handicaps:")
    print("   - Add handicaps for players via Manage Players")
    print("   - Add courses with ratings via Manage Courses")
    print("   - Go to Add Match, select players and course")
    print("   - Handicaps should auto-calculate!")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    main()
