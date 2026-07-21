# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A Python Dash web app for tracking golf match results and player/team statistics across multi-day golf trips. Supports Singles and Fourball match play with WHS (World Handicap System) auto-calculated handicaps, Google OAuth login, and admin-gated write access.

## Commands

Dependencies are managed with `uv` (see `uv.lock`, `pyproject.toml`, Python 3.13 pinned in `.python-version`).

```bash
# Install dependencies
uv sync
# or: pip install -r requirements.txt

# Run the app locally (dev server, http://localhost:8050)
./run.sh
# or: source .venv/bin/activate && python src/app.py

# Run with Gunicorn (production-like, with --reload)
./start_gunicorn.sh

# Run with Gunicorn (production, no reload)
./start_production.sh

# Run all tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_handicap_calculator.py

# Run a single test case
python -m pytest tests/test_handicap_calculator.py::TestHandicapCalculator::test_course_handicap_standard_slope

# Verify environment/DB setup
python tests/verify_setup.py
```

Tests use `unittest.TestCase` classes (run via pytest). Integration/data-service tests spin up a temporary SQLite file per test (`tempfile.mkstemp`) via `setUp`/`tearDown` rather than mocking the database.

## Configuration

Copy `.env.example` to `.env` before running. Key variables:

- `USE_POSTGRES` — `false` (default, SQLite) or `true` (PostgreSQL/Supabase)
- `DATABASE_URL` — required if `USE_POSTGRES=true`
- `SQLITE_DB_PATH` — default `data/golf_trips.db`
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` — Google OAuth (from Google Cloud Console); redirect URI is `<host>/authorize`
- `SECRET_KEY` — Flask session secret
- `ADMIN_EMAILS` — comma-separated emails allowed to add/edit/delete data; if empty, **any authenticated user is treated as admin**

## Architecture

### Database layer: abstract base + two backends

`src/db_service_base.py` defines `DatabaseServiceBase`, an ABC covering all persistence operations (matches, players, handicaps, team assignments, courses, statistics queries, CSV import). Two concrete implementations satisfy it:

- `src/db_service.py` — `SQLiteDatabaseService` (also exports `DatabaseService` as a backward-compat alias) plus `get_database_service(db_path)`, a **factory function** that reads `USE_POSTGRES`/`DATABASE_URL` from the environment and returns either the SQLite or Postgres implementation.
- `src/db_service_postgres.py` — `PostgresDatabaseService`, same interface backed by `psycopg2`.

Both implementations call `init_db()` on construction, creating tables (`players`, `handicaps`, `player_teams`, `matches`, `courses`) if they don't exist — there's no separate migration/schema step for normal use. Always code against `get_database_service()` / the base-class interface, not against `SQLiteDatabaseService` directly, so both backends keep working.

### Business logic layer

`src/data_service.py` (`DataService`) wraps a `DatabaseServiceBase` and adds statistics/aggregation logic on top (team summaries, player performance tables, partner/head-to-head/course breakdowns). It caches the full matches dataframe in memory (`self.df` / `_cache_valid`) and **must have `invalidate_cache()` called after any write** to matches (the write callbacks in `app.py` do this already — remember to do it in any new write path).

### Handicap calculations

`src/handicap_calculator.py` (`HandicapCalculator`) implements WHS/R&A match-play formulas as static methods: course handicap = `index × slope/113`, then playing handicaps with 100% allowance for Singles and 85% allowance for Fourball (lowest handicap in the group plays off scratch). Rounding uses `ROUND_HALF_UP`, not Python's default banker's rounding — use `HandicapCalculator._round_half_up` for consistency rather than `round()`.

### App / UI layer

`src/app.py` is a single large Dash app (~2400 lines) — there is no separate router/component-file split. Structure to know when navigating it:

- App/OAuth/Flask setup, `/login`, `/authorize`, `/logout`, `/auth-status`, `/health` routes, and a large inline CSS block (`app.index_string`) all live at the top.
- Below that, one `create_..._page()` function per page (Summary, Player Details, Add Match, Head-to-Head, Course Stats, Manage Players, Manage Courses, Matches, Teams, Edit Matches), each returning a `dash.html`/`dbc` layout.
- A single `display_page` callback keyed on `dcc.Location(id='url')` routes between pages by pathname (no `dash.register_page`/multi-page framework).
- The rest of the file is `@app.callback` functions for interactivity: auto-calculating handicaps as players/course/match-type are chosen, adding/editing/deleting matches, players, courses, and team assignments.

`server = app.server` is the Flask instance exposed to Gunicorn as `src.app:server`.

### Auth model

`src/auth.py` wraps Authlib's Google OAuth flow. Two tiers: *authenticated* (logged in via Google) and *admin* (email in `ADMIN_EMAILS`, or anyone authenticated if that list is empty). Write-side Dash callbacks in `app.py` call an admin-check helper (`check_admin_access()`) before mutating data — new write callbacks should follow the same pattern rather than relying on UI hiding alone, since callbacks are reachable directly.

## Notes on repo state

- `data/golf_trips.db` is the tracked SQLite database (checked into the repo); `data/matches.csv` is a historical backup. A `golf_trips.db` also exists at the repo root — the app reads `data/golf_trips.db` via `src/app.py`'s `db_path` construction, not the root copy.
- `scripts/migrate_courses.py` and `scripts/migrate_data.py` are one-off/historical migration scripts (CSV → DB, backfilling courses table) rather than a repeatable migration system.
- `docs/README.md`, `docs/QUICK_START.md`, and `scripts/run_app.sh` describe an older, pre-`src/`-reorg layout (`dash_app_new.py`, `main.py`, `FileLoader.py` at repo root) that no longer exists — treat `src/app.py` and the top-level `README.md`/`run.sh` as current.
