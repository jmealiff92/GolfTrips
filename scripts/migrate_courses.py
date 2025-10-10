#!/usr/bin/env python3
"""
Migration script to populate courses table from existing matches

This script helps populate the courses table with courses that are
already being used in matches. It adds them with default ratings
that should be updated manually via the Manage Courses page.
"""
from db_service import DatabaseService
import sys

def migrate_courses():
    """Migrate courses from matches to courses table"""
    db = DatabaseService('golf_trips.db')

    print("=" * 70)
    print("COURSE MIGRATION SCRIPT")
    print("=" * 70)

    # Get all matches
    matches = db.get_all_matches()
    if matches.empty:
        print("\n⚠ No matches found in database")
        return

    # Get unique courses from matches
    courses_in_matches = matches['Course'].unique()
    print(f"\n✓ Found {len(courses_in_matches)} unique courses in matches:")
    for course in sorted(courses_in_matches):
        print(f"  - {course}")

    # Get existing courses in courses table
    existing_courses = db.get_all_courses()
    existing_course_names = [c['name'] for c in existing_courses]
    print(f"\n✓ Found {len(existing_courses)} courses already in courses table")

    # Find courses that need to be added
    courses_to_add = set(courses_in_matches) - set(existing_course_names)

    if not courses_to_add:
        print("\n✅ All courses from matches already exist in courses table!")
        print("\nYou can update course ratings via 'Manage Courses' page")
        return

    print(f"\n⚠ Found {len(courses_to_add)} courses in matches but not in courses table:")
    for course in sorted(courses_to_add):
        print(f"  - {course}")

    # Ask for confirmation
    print("\n" + "=" * 70)
    print("This script will add these courses with DEFAULT VALUES:")
    print("  - Par: 72")
    print("  - Slope Rating: 113 (standard)")
    print("  - Course Rating: 72.0")
    print("\n⚠ IMPORTANT: You MUST update these ratings via 'Manage Courses'")
    print("  for accurate handicap calculations!")
    print("=" * 70)

    response = input("\nProceed with migration? (yes/no): ").strip().lower()

    if response not in ['yes', 'y']:
        print("\n❌ Migration cancelled")
        return

    # Add courses
    print("\n📝 Adding courses...")
    added_count = 0
    failed_count = 0

    for course_name in sorted(courses_to_add):
        success = db.add_course(
            name=course_name,
            par=72,
            slope_rating=113,
            course_rating=72.0
        )

        if success:
            print(f"  ✓ Added: {course_name}")
            added_count += 1
        else:
            print(f"  ✗ Failed: {course_name}")
            failed_count += 1

    # Summary
    print("\n" + "=" * 70)
    print("MIGRATION COMPLETE")
    print("=" * 70)
    print(f"\n✅ Successfully added: {added_count} courses")
    if failed_count > 0:
        print(f"❌ Failed to add: {failed_count} courses")

    print("\n" + "⚠" * 35)
    print("NEXT STEPS - VERY IMPORTANT!")
    print("⚠" * 35)
    print("\n1. Start the application:")
    print("   source .venv/bin/activate")
    print("   python dash_app_new.py")
    print("\n2. Navigate to 'Manage Courses' page")
    print("\n3. For EACH course, update the ratings:")
    print("   - Click on course row to select it")
    print("   - Update Par (usually 70-72)")
    print("   - Update Slope Rating (typically 100-150)")
    print("   - Update Course Rating (typically similar to par)")
    print("   - Click 'Update Course'")
    print("\n4. These ratings are REQUIRED for auto-calculating handicaps!")
    print("\nWithout correct ratings, handicap calculations will be inaccurate.")
    print("=" * 70 + "\n")

def show_current_courses():
    """Show current courses and their ratings"""
    db = DatabaseService('golf_trips.db')

    courses = db.get_all_courses()
    if not courses:
        print("\n⚠ No courses in courses table")
        return

    print("\n" + "=" * 70)
    print("CURRENT COURSES IN DATABASE")
    print("=" * 70)

    for course in courses:
        print(f"\n{course['name']}:")
        print(f"  Par: {course['par']}")
        print(f"  Slope Rating: {course['slope_rating']}")
        print(f"  Course Rating: {course['course_rating']}")

        # Warn if using default values
        if (course['par'] == 72 and
            course['slope_rating'] == 113 and
            course['course_rating'] == 72.0):
            print("  ⚠ WARNING: Using default values - UPDATE THESE!")

    print("\n" + "=" * 70)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--show':
        show_current_courses()
        return

    if len(sys.argv) > 1 and sys.argv[1] == '--help':
        print("\nCourse Migration Script")
        print("=" * 70)
        print("\nUsage:")
        print("  python migrate_courses.py          # Run migration")
        print("  python migrate_courses.py --show   # Show current courses")
        print("  python migrate_courses.py --help   # Show this help")
        print("\nWhat this does:")
        print("  - Finds courses used in matches")
        print("  - Adds them to courses table if missing")
        print("  - Uses default ratings (MUST be updated!)")
        print("\n" + "=" * 70 + "\n")
        return

    migrate_courses()

if __name__ == '__main__':
    main()
