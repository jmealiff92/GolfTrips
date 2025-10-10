# Database Configuration

The Golf Match Analysis app supports both **SQLite** (default) and **PostgreSQL** databases with seamless switching via environment variables.

## Architecture

The application uses a **factory pattern** with separate database implementations:

- **`db_service_base.py`** - Abstract base class defining the database interface
- **`db_service.py`** - SQLite implementation and factory method
- **`db_service_postgres.py`** - PostgreSQL/Supabase implementation

This architecture provides:
- ✅ Clean separation of concerns
- ✅ Easy maintenance and testing
- ✅ Simple switching between databases
- ✅ Backward compatibility

## Configuration

### Quick Setup

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` to configure your database

### Option 1: SQLite (Default - No Configuration Required)

SQLite is the default and requires no setup:

```env
USE_POSTGRES=false
SQLITE_DB_PATH=data/golf_trips.db
```

**Pros:**
- ✅ Zero configuration
- ✅ Perfect for local development
- ✅ No external dependencies
- ✅ Database file committed to repo

**Cons:**
- ❌ Single file, not ideal for multiple users
- ❌ Limited scalability

### Option 2: PostgreSQL (Supabase)

For production or shared hosting, use PostgreSQL:

```env
USE_POSTGRES=true
DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
SQLITE_DB_PATH=data/golf_trips.db
```

**Pros:**
- ✅ Multi-user support
- ✅ Better scalability
- ✅ Cloud-hosted (Supabase free tier available)
- ✅ Real-time capabilities

**Cons:**
- ❌ Requires configuration
- ❌ External dependency

## Supabase Setup

### Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create a new project
3. Wait for the database to initialize

### Step 2: Get Connection String

1. In your Supabase project dashboard, go to **Settings** → **Database**
2. Find the **Connection String** section
3. Copy the **URI** format connection string
4. Replace `[YOUR-PASSWORD]` with your database password

Example:
```
postgresql://postgres:your_password@db.abcdefghij.supabase.co:5432/postgres
```

### Step 3: Configure Environment

Add to your `.env` file:
```env
USE_POSTGRES=true
DATABASE_URL=postgresql://postgres:your_password@db.abcdefghij.supabase.co:5432/postgres
```

### Step 4: Initialize Database

The app will automatically create all tables when it starts. Just run:
```bash
python src/app.py
```

### Step 5: Migrate Data (Optional)

If you have existing SQLite data, you can migrate:

1. Export from SQLite:
   ```bash
   python scripts/export_data.py
   ```

2. Switch to PostgreSQL in `.env`

3. Import to PostgreSQL:
   ```bash
   python scripts/import_data.py
   ```

## Usage in Code

### Recommended: Use Factory Method

```python
from src.db_service import get_database_service

# Automatically uses correct database based on .env
db_service = get_database_service('data/golf_trips.db')

# Use normally - works with both databases
players = db_service.get_all_players()
```

### Direct Instantiation (Not Recommended)

```python
# SQLite
from src.db_service import SQLiteDatabaseService
db = SQLiteDatabaseService('data/golf_trips.db')

# PostgreSQL
from src.db_service_postgres import PostgresDatabaseService
db = PostgresDatabaseService('postgresql://...')
```

## SQL Differences Handled

The implementation handles these key differences automatically:

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Placeholders | `?` | `%s` |
| Upsert | `INSERT OR IGNORE` | `ON CONFLICT DO NOTHING` |
| Dict Results | `row_factory = Row` | `DictCursor` |
| Exceptions | `sqlite3.IntegrityError` | `psycopg2.IntegrityError` |

## Testing

Test the database configuration:

```bash
python test_db.py
```

Expected output:
```
✓ Using: SQLiteDatabaseService (or PostgresDatabaseService)
✓ Database type: SQLite (or PostgreSQL)
✓ Found X players
✓ Found X matches
✓ Found X courses
✅ Database service is working correctly!
```

## Troubleshooting

### Error: "DATABASE_URL must be set when USE_POSTGRES=true"

**Solution:** Add `DATABASE_URL` to your `.env` file with a valid PostgreSQL connection string.

### Error: "psycopg2-binary is required"

**Solution:** Install the PostgreSQL driver:
```bash
pip install psycopg2-binary
```

### Error: "relation does not exist"

**Solution:** The tables haven't been created. Restart the app - it will auto-create tables on startup.

### Connection Issues

**Symptoms:** Can't connect to Supabase

**Solutions:**
1. Verify your password is correct in the connection string
2. Check your Supabase project is running (not paused)
3. Ensure your IP is allowed (Supabase auto-allows all by default)
4. Test connection with `psql`:
   ```bash
   psql "postgresql://postgres:password@db.xxx.supabase.co:5432/postgres"
   ```

## Performance Considerations

### SQLite
- Best for: Single user, local development
- Concurrent writes: Not supported
- Max database size: ~140TB (practical limit much lower)
- Queries: Fast for small-medium datasets

### PostgreSQL
- Best for: Multiple users, production
- Concurrent writes: Fully supported
- Max database size: Unlimited (practical)
- Queries: Optimized for large datasets

## Security

### SQLite
- Database file should not be publicly accessible
- No authentication required
- Consider encrypting the database file

### PostgreSQL
- Use strong passwords (Supabase generates these)
- Connection string contains sensitive data - keep `.env` secret
- `.env` is in `.gitignore` by default
- Supabase provides SSL by default
- Consider using connection pooling for production

## Migration Between Databases

### SQLite → PostgreSQL

1. Keep both configurations available
2. Set `USE_POSTGRES=false`
3. Export data to CSV/JSON
4. Set `USE_POSTGRES=true`
5. Import data

### PostgreSQL → SQLite

Same process in reverse.

## Backup

### SQLite Backup
```bash
# Simple file copy
cp data/golf_trips.db data/golf_trips_backup.db

# Or use SQLite backup
sqlite3 data/golf_trips.db ".backup data/golf_trips_backup.db"
```

### PostgreSQL Backup
```bash
# Using pg_dump
pg_dump "postgresql://..." > backup.sql

# Or use Supabase dashboard
# Settings → Database → Backups
```

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USE_POSTGRES` | No | `false` | Set to `true` to use PostgreSQL |
| `DATABASE_URL` | If `USE_POSTGRES=true` | None | PostgreSQL connection string |
| `SQLITE_DB_PATH` | No | `golf_trips.db` | Path to SQLite database file |

## Best Practices

1. **Development**: Use SQLite (no config needed)
2. **Production**: Use PostgreSQL (better for multiple users)
3. **Never commit** `.env` file (it's in `.gitignore`)
4. **Always set** both `SQLITE_DB_PATH` and `DATABASE_URL` in `.env` for easy switching
5. **Test locally** with SQLite before deploying with PostgreSQL
6. **Backup regularly** regardless of database choice

---

**Last Updated:** October 2025
**Version:** 2.0
