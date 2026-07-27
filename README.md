# ⛳ Golf Match Analysis

A comprehensive web application for managing and analyzing golf match statistics, built with Python Dash.

## Features

- 📊 **Team & Player Summary** - Overall statistics and standings
- 👤 **Player Details** - Individual player performance analysis
- 👥 **Player Management** - Add players and manage handicaps by year
- 🏌️ **Course Management** - Maintain course database with ratings
- ➕ **Add Matches** - Create matches with auto-calculated handicaps
- ✏️ **Edit Matches** - Update results and delete matches
- ⚔️ **Head-to-Head** - Compare players directly
- 📈 **Course Statistics** - Performance by course

## Quick Start

### 1. Configure Database (Optional)

The app supports both **SQLite** (default) and **PostgreSQL** (Supabase):

```bash
# Copy example environment file
cp .env.example .env

# Edit .env to configure your database
# For SQLite (default): USE_POSTGRES=false
# For PostgreSQL/Supabase: USE_POSTGRES=true and set DATABASE_URL
```

**Environment Variables:**
- `USE_POSTGRES` - Set to `true` for PostgreSQL, `false` for SQLite (default: `false`)
- `DATABASE_URL` - PostgreSQL connection string (required if `USE_POSTGRES=true`)
- `SQLITE_DB_PATH` - Path to SQLite database file (default: `data/golf_trips.db`)

**Example Supabase Connection:**
```env
USE_POSTGRES=true
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
```

### 2. Run the Application

```bash
# Run the application
./run.sh

# Or manually:
source .venv/bin/activate
python src/app.py
```

Then visit: **http://localhost:8050**

## Project Structure

```
golf-trips/
├── src/                    # Source code
│   ├── app.py             # Main Dash application
│   ├── db_service.py      # Database factory & SQLite implementation
│   ├── db_service_postgres.py  # PostgreSQL implementation
│   ├── db_service_base.py # Abstract base class
│   ├── data_service.py    # Business logic
│   ├── handicap_calculator.py  # WHS calculations
│   └── model.py           # Data models
├── tests/                  # Test files
│   ├── test_handicap_calculator.py
│   ├── test_integration.py
│   ├── test_match_features.py
│   └── verify_setup.py
├── data/                   # Data files
│   ├── golf_trips.db      # SQLite database
│   └── matches.csv        # Match data (backup)
├── scripts/                # Utility scripts
│   ├── migrate_courses.py # Course migration tool
│   └── migrate_data.py    # Data migration
├── docs/                   # Documentation
│   ├── README.md          # Detailed documentation
│   ├── QUICK_START.md     # Quick start guide
│   ├── BUG_FIXES.md       # Bug fix documentation
│   ├── MATCH_FEATURES.md  # Match management features
│   └── IMPLEMENTATION_SUMMARY.md  # Implementation details
└── run.sh                  # Start script

```

## Key Features

### Auto-Calculate Handicaps
The system automatically calculates match handicaps using the World Handicap System (WHS):
- **Singles**: 100% allowance
- **Fourball**: 85% allowance

Simply add player handicap indexes and course ratings, and the system handles the rest!

### Player Management
- Add players and track handicaps by year
- Update handicaps as they change
- View complete handicap history

### Course Database
- Store course details (par, slope rating, course rating)
- Essential for accurate handicap calculations
- Easy to add and update

### Match Management
- Duplicate prevention
- Easy result editing
- Delete matches when needed
- Automatic statistics updates

## Technology Stack

- **Python 3.x**
- **Dash** - Web framework
- **Plotly** - Interactive charts
- **Dash Bootstrap Components** - UI components
- **Pandas** - Data manipulation
- **SQLite / PostgreSQL** - Database (configurable via environment variables)
- **Supabase** - Optional PostgreSQL hosting

## Requirements

```
dash>=2.14.0
dash-bootstrap-components>=1.5.0
pandas>=2.0.0
plotly>=5.17.0
psycopg2-binary>=2.9.0  # For PostgreSQL support
python-dotenv>=1.0.0     # For environment configuration
```

Install dependencies:
```bash
uv sync
```

## Documentation

- **[Quick Start Guide](docs/QUICK_START.md)** - Get started quickly
- **[Implementation Summary](docs/IMPLEMENTATION_SUMMARY.md)** - Technical details
- **[Bug Fixes](docs/BUG_FIXES.md)** - Recent fixes
- **[Match Features](docs/MATCH_FEATURES.md)** - Match management docs

## Testing

Run tests:
```bash
# All tests
python -m pytest tests/

# Specific test
python tests/test_handicap_calculator.py
python tests/test_integration.py

# Verification
python tests/verify_setup.py
```

## Migration Tools

### Migrate Courses from Matches
```bash
python scripts/migrate_courses.py
```

This populates the courses table with courses used in existing matches.

## Contributing

When making changes:
1. Update tests in `tests/`
2. Update documentation in `docs/`
3. Follow existing code style
4. Test thoroughly before committing

## License

Private project for personal use.

## Support

For issues or questions, check the documentation in the `docs/` folder:
- Start with [QUICK_START.md](docs/QUICK_START.md)
- See [README.md](docs/README.md) for detailed info
- Check [BUG_FIXES.md](docs/BUG_FIXES.md) for known issues

---

**Version**: 2.0
**Last Updated**: October 2025
