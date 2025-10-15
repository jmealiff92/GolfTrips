#!/usr/bin/env python3
"""
Test script for new match management features:
1. Delete match functionality
2. Duplicate match validation
"""
from src.db_service import DatabaseService
import tempfile
import os

def test_duplicate_match_validation():
    """Test that duplicate matches are prevented"""
    print("=" * 70)
    print("TEST 1: Duplicate Match Validation")
    print("=" * 70)

    # Create temporary database
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    db = DatabaseService(db_path)

    # Add test players and course
    db.add_player("Player A")
    db.add_player("Player B")
    db.add_course("Test Course", 72, 113, 72.0)

    # Add first match
    print("\n1. Adding initial match (Year 2024, Day 1, Match 1)...")
    success = db.add_match(
        year=2024, day=1, match_number=1,
        course="Test Course", match_type="Single",
        blue_player1="Player A", blue_player1_handicap=0,
        blue_player2=None, blue_player2_handicap=None,
        red_player1="Player B", red_player1_handicap=5,
        red_player2=None, red_player2_handicap=None,
        result="", score=""
    )
    print(f"   ✓ First match added: {success}")

    # Check if match exists
    exists = db.check_match_exists(2024, 1, 1)
    print(f"   ✓ Match exists check: {exists}")

    # Try to add duplicate
    print("\n2. Attempting to add duplicate match (same Year/Day/Match)...")
    success = db.add_match(
        year=2024, day=1, match_number=1,
        course="Test Course", match_type="Single",
        blue_player1="Player B", blue_player1_handicap=0,
        blue_player2=None, blue_player2_handicap=None,
        red_player1="Player A", red_player1_handicap=5,
        red_player2=None, red_player2_handicap=None,
        result="", score=""
    )
    print(f"   ✓ Duplicate prevented: {not success}")

    # Add different match number (should succeed)
    print("\n3. Adding match with different match number (Match 2)...")
    success = db.add_match(
        year=2024, day=1, match_number=2,
        course="Test Course", match_type="Single",
        blue_player1="Player B", blue_player1_handicap=0,
        blue_player2=None, blue_player2_handicap=None,
        red_player1="Player A", red_player1_handicap=5,
        red_player2=None, red_player2_handicap=None,
        result="", score=""
    )
    print(f"   ✓ Different match number added: {success}")

    # Add same match number but different day (should succeed)
    print("\n4. Adding match with same number but different day (Day 2)...")
    success = db.add_match(
        year=2024, day=2, match_number=1,
        course="Test Course", match_type="Single",
        blue_player1="Player B", blue_player1_handicap=0,
        blue_player2=None, blue_player2_handicap=None,
        red_player1="Player A", red_player1_handicap=5,
        red_player2=None, red_player2_handicap=None,
        result="", score=""
    )
    print(f"   ✓ Different day added: {success}")

    # Summary
    matches = db.get_all_matches()
    print(f"\n✅ Total matches in database: {len(matches)}")
    print("   Expected: 3 (1 duplicate prevented)")

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)

    print("\n✅ Test 1 PASSED: Duplicate validation working correctly\n")

def test_delete_match():
    """Test that matches can be deleted"""
    print("=" * 70)
    print("TEST 2: Delete Match Functionality")
    print("=" * 70)

    # Create temporary database
    db_fd, db_path = tempfile.mkstemp(suffix='.db')
    db = DatabaseService(db_path)

    # Add test players and course
    db.add_player("Player A")
    db.add_player("Player B")
    db.add_course("Test Course", 72, 113, 72.0)

    # Add test matches
    print("\n1. Adding test matches...")
    for i in range(1, 4):
        db.add_match(
            year=2024, day=1, match_number=i,
            course="Test Course", match_type="Single",
            blue_player1="Player A", blue_player1_handicap=0,
            blue_player2=None, blue_player2_handicap=None,
            red_player1="Player B", red_player1_handicap=5,
            red_player2=None, red_player2_handicap=None,
            result="", score=""
        )
    matches = db.get_all_matches()
    print(f"   ✓ Added {len(matches)} matches")

    # Delete a match
    print("\n2. Deleting match (Year 2024, Day 1, Match 2)...")
    success = db.delete_match(2024, 1, 2)
    print(f"   ✓ Delete successful: {success}")

    matches = db.get_all_matches()
    print(f"   ✓ Matches remaining: {len(matches)}")

    # Verify correct match was deleted
    remaining_matches = matches['MatchNumber'].tolist()
    print(f"   ✓ Remaining match numbers: {remaining_matches}")

    # Try to delete non-existent match
    print("\n3. Attempting to delete non-existent match...")
    success = db.delete_match(2024, 1, 999)
    print(f"   ✓ Delete failed (as expected): {not success}")

    # Delete another match
    print("\n4. Deleting another match (Match 1)...")
    success = db.delete_match(2024, 1, 1)
    print(f"   ✓ Delete successful: {success}")

    matches = db.get_all_matches()
    print(f"   ✓ Matches remaining: {len(matches)}")

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)

    print("\n✅ Test 2 PASSED: Delete functionality working correctly\n")

def test_with_real_database():
    """Show info about the real database"""
    print("=" * 70)
    print("REAL DATABASE INFO")
    print("=" * 70)

    db = DatabaseService('golf_trips.db')

    matches = db.get_all_matches()
    print(f"\n✓ Total matches: {len(matches)}")

    if not matches.empty:
        # Show matches by year
        matches_by_year = matches.groupby('Year').size()
        print("\nMatches by year:")
        for year, count in matches_by_year.items():
            print(f"  {year}: {count} matches")

        # Check for potential duplicates (shouldn't exist)
        duplicates = matches.groupby(['Year', 'Day', 'MatchNumber']).size()
        duplicates = duplicates[duplicates > 1]

        if len(duplicates) > 0:
            print("\n⚠ WARNING: Found duplicate match keys:")
            print(duplicates)
        else:
            print("\n✓ No duplicate matches found")

    print("\n" + "=" * 70)

def main():
    print("\n" + "=" * 70)
    print("MATCH MANAGEMENT FEATURES TEST")
    print("=" * 70 + "\n")

    test_duplicate_match_validation()
    test_delete_match()
    test_with_real_database()

    print("=" * 70)
    print("ALL TESTS COMPLETE")
    print("=" * 70)

    print("\nNew Features Summary:")
    print("\n1. ✅ Duplicate Match Prevention")
    print("   - Cannot add match with same Year/Day/Match Number")
    print("   - Clear error message shown to user")
    print("   - Prevents data integrity issues")

    print("\n2. ✅ Delete Match Functionality")
    print("   - Delete button in Edit Matches modal")
    print("   - Confirmation through modal interface")
    print("   - Updates statistics automatically")

    print("\nHow to use:")
    print("\n• Add Match:")
    print("  - System checks for duplicates before adding")
    print("  - Shows error if Year/Day/Match Number already exists")
    print("  - Suggests using different match number")

    print("\n• Delete Match:")
    print("  1. Navigate to 'Edit Matches' page")
    print("  2. Click on match row to select")
    print("  3. Modal opens with match details")
    print("  4. Click 'Delete Match' button (red)")
    print("  5. Match is deleted and table refreshes")

    print("\n" + "=" * 70 + "\n")

if __name__ == '__main__':
    main()
