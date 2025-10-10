"""
Migration script to load CSV data into database
Run this once to migrate from CSV to database
"""
from db_service import DatabaseService

def migrate():
    print("Starting migration from CSV to database...")

    db_service = DatabaseService('golf_trips.db')

    # Import from CSV
    successful, failed = db_service.import_from_csv('matches.csv')

    print(f"\nMigration complete!")
    print(f"Successfully imported: {successful} matches")
    print(f"Failed to import: {failed} matches")

    # Display summary
    print("\n" + "="*50)
    print("Database Summary:")
    print("="*50)

    players = db_service.get_players_from_matches()
    print(f"Total players: {len(players)}")

    years = db_service.get_years_list()
    print(f"Years with data: {', '.join(map(str, years))}")

    all_matches = db_service.get_all_matches()
    print(f"Total matches: {len(all_matches)}")

    print("\n" + "="*50)
    print("You can now run: python dash_app_new.py")
    print("="*50)

if __name__ == "__main__":
    migrate()
