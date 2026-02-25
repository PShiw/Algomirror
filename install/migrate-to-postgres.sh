#!/bin/bash

# ============================================
# AlgoMirror SQLite to PostgreSQL Migration
# Copies all data from SQLite to PostgreSQL
# ============================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════════════╗"
echo "║     AlgoMirror - SQLite to PostgreSQL Migration        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo -e "${NC}"

log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}"
}

# ============================================
# CONFIGURATION
# ============================================
BASE_PATH="/var/python/algomirror"
SQLITE_DB="$BASE_PATH/instance/algomirror.db"
ENV_FILE="$BASE_PATH/.env"
VENV_PYTHON="$BASE_PATH/venv/bin/python"
FLASK_CMD="$BASE_PATH/venv/bin/flask"

# Detect pip: UV-managed venvs don't have pip, use 'uv pip' instead
if [ -f "$BASE_PATH/venv/bin/pip" ]; then
    VENV_PIP="$BASE_PATH/venv/bin/pip"
elif command -v uv &>/dev/null; then
    VENV_PIP="uv pip --python $VENV_PYTHON"
else
    VENV_PIP="$VENV_PYTHON -m pip"
fi

# ============================================
# ROOT CHECK
# ============================================
if [ "$EUID" -ne 0 ]; then
    log_message "Please run as root (sudo bash migrate-to-postgres.sh)" "$RED"
    exit 1
fi

# ============================================
# PRE-FLIGHT CHECKS
# ============================================
log_message "Running pre-flight checks..." "$BLUE"

# Check SQLite database exists
if [ ! -f "$SQLITE_DB" ]; then
    log_message "SQLite database not found at: $SQLITE_DB" "$RED"
    exit 1
fi
SQLITE_SIZE=$(du -h "$SQLITE_DB" | cut -f1)
log_message "  SQLite database found: $SQLITE_DB ($SQLITE_SIZE)" "$GREEN"

# Check PostgreSQL is running
if ! systemctl is-active --quiet postgresql; then
    log_message "  PostgreSQL is not running. Start it first:" "$RED"
    log_message "    systemctl start postgresql" "$NC"
    exit 1
fi
log_message "  PostgreSQL is running" "$GREEN"

# Check venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    log_message "  Python venv not found at: $VENV_PYTHON" "$RED"
    exit 1
fi
log_message "  Python venv found" "$GREEN"

# Get PostgreSQL URL
if [ -f /tmp/algomirror_pg_url.tmp ]; then
    PG_URL=$(cat /tmp/algomirror_pg_url.tmp)
    log_message "  PostgreSQL URL loaded from install-postgres.sh output" "$GREEN"
else
    echo ""
    log_message "No saved PostgreSQL URL found." "$YELLOW"
    log_message "Enter your PostgreSQL DATABASE_URL:" "$YELLOW"
    log_message "  Format: postgresql://user:password@localhost:5432/algomirror" "$NC"
    echo ""
    read -p "DATABASE_URL: " PG_URL

    if [ -z "$PG_URL" ]; then
        log_message "No URL provided. Exiting." "$RED"
        exit 1
    fi
fi

# Validate URL format
if [[ ! "$PG_URL" =~ ^postgresql:// ]]; then
    log_message "Invalid PostgreSQL URL. Must start with postgresql://" "$RED"
    exit 1
fi
log_message "  PostgreSQL URL: ${PG_URL%%@*}@..." "$GREEN"

# ============================================
# ENSURE PostgreSQL DRIVER IS INSTALLED
# ============================================
log_message "\nChecking PostgreSQL driver..." "$BLUE"

# Install system dependency for PostgreSQL client library
apt-get install -y -qq libpq-dev >/dev/null 2>&1

# Check if any PostgreSQL driver is already installed
DRIVER_INSTALLED=false
for pkg in psycopg2-binary psycopg2 psycopg; do
    $VENV_PIP show "$pkg" >/dev/null 2>&1 && DRIVER_INSTALLED=true && break
done

if [ "$DRIVER_INSTALLED" = false ]; then
    log_message "Installing psycopg[binary] (latest PostgreSQL driver)..." "$YELLOW"
    $VENV_PIP install "psycopg[binary]"
    if [ $? -ne 0 ]; then
        log_message "Trying psycopg2-binary as fallback..." "$YELLOW"
        $VENV_PIP install psycopg2-binary
        if [ $? -ne 0 ]; then
            log_message "Failed to install PostgreSQL driver. Check errors above." "$RED"
            exit 1
        fi
    fi
fi

# Verify driver is importable
$VENV_PYTHON -c "import psycopg" 2>/dev/null || $VENV_PYTHON -c "import psycopg2" 2>/dev/null
if [ $? -ne 0 ]; then
    log_message "PostgreSQL driver installed but not importable. Check errors." "$RED"
    exit 1
fi
log_message "psycopg2-binary is installed" "$GREEN"

# ============================================
# CONFIRMATION
# ============================================
echo ""
log_message "============================================" "$YELLOW"
log_message "  Migration Summary" "$YELLOW"
log_message "============================================" "$YELLOW"
log_message "  Source: $SQLITE_DB ($SQLITE_SIZE)" "$NC"
log_message "  Target: PostgreSQL (${PG_URL%%@*}@...)" "$NC"
log_message "  Action: Copy all data, update .env, restart service" "$NC"
log_message "============================================" "$YELLOW"
echo ""
read -p "Proceed with migration? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    log_message "Migration cancelled." "$YELLOW"
    exit 0
fi

# ============================================
# STOP SERVICE
# ============================================
log_message "\nStopping AlgoMirror service..." "$BLUE"
systemctl stop algomirror 2>/dev/null || true
sleep 2
log_message "Service stopped" "$GREEN"

# ============================================
# BACKUP SQLITE
# ============================================
BACKUP_FILE="${SQLITE_DB}.backup_$(date +%Y%m%d_%H%M%S)"
cp "$SQLITE_DB" "$BACKUP_FILE"
log_message "SQLite backup created: $BACKUP_FILE" "$GREEN"

# ============================================
# RUN MIGRATION
# ============================================
log_message "\nStarting data migration..." "$BLUE"

cd "$BASE_PATH"

# Create the Python migration script
cat > /tmp/algomirror_migrate.py << 'MIGRATE_SCRIPT'
#!/usr/bin/env python3
"""
AlgoMirror SQLite to PostgreSQL Migration Script
Copies all data preserving foreign key relationships
"""
import os
import sys
import json
from datetime import datetime

# Read PostgreSQL URL from environment (set by shell wrapper)
PG_URL = os.environ.get('ALGOMIRROR_PG_URL')
SQLITE_DB = os.environ.get('ALGOMIRROR_SQLITE_DB')

if not PG_URL or not SQLITE_DB:
    print("[ERROR] Missing ALGOMIRROR_PG_URL or ALGOMIRROR_SQLITE_DB environment variables")
    sys.exit(1)

# Override DATABASE_URL before importing app
os.environ['DATABASE_URL'] = PG_URL

# Import SQLAlchemy for direct SQLite access
from sqlalchemy import create_engine, text, inspect

# Import Flask app (will use PG_URL from env)
from app import create_app, db

# ============================================
# TABLE ORDER (respects foreign key dependencies)
# ============================================
TABLE_ORDER = [
    'users',
    'trading_accounts',
    'activity_logs',
    'orders',
    'positions',
    'holdings',
    'strategies',
    'strategy_legs',
    'strategy_executions',
    'trading_settings',
    'margin_requirements',
    'trade_qualities',
    'margin_trackers',
    'trading_hours_templates',
    'trading_sessions',
    'market_holidays',
    'special_trading_sessions',
    'websocket_sessions',
    'risk_events',
]

# ============================================
# JSON COLUMNS (SQLite stores as text, PG needs dict/list)
# ============================================
JSON_COLUMNS = {
    'trading_accounts': ['last_funds_data', 'last_positions_data', 'last_holdings_data'],
    'activity_logs': ['details'],
    'strategies': ['selected_accounts'],
    'margin_trackers': ['allocated_margins'],
    'websocket_sessions': ['subscribed_symbols'],
    'risk_events': ['exit_order_ids'],
}

# ============================================
# CONNECT TO SQLITE
# ============================================
print(f"[INFO] Connecting to SQLite: {SQLITE_DB}")
sqlite_engine = create_engine(f'sqlite:///{SQLITE_DB}')
sqlite_inspector = inspect(sqlite_engine)
sqlite_tables = sqlite_inspector.get_table_names()
print(f"[INFO] SQLite tables found: {len(sqlite_tables)}")

# ============================================
# CREATE FLASK APP (uses PostgreSQL)
# ============================================
print(f"[INFO] Connecting to PostgreSQL...")
app = create_app('production')

with app.app_context():
    # ============================================
    # CREATE TABLES IN POSTGRESQL
    # ============================================
    print("[INFO] Creating tables in PostgreSQL...")
    db.create_all()
    print("[INFO] Tables created")

    # ============================================
    # COPY DATA TABLE BY TABLE
    # ============================================
    print("\n[INFO] Copying data...")
    sqlite_conn = sqlite_engine.connect()
    total_rows = 0
    table_counts = {}

    for table_name in TABLE_ORDER:
        # Check if table exists in SQLite
        if table_name not in sqlite_tables:
            print(f"  [SKIP] {table_name}: not in SQLite")
            continue

        # Check if PostgreSQL table already has data
        pg_count = db.session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        if pg_count > 0:
            print(f"  [SKIP] {table_name}: PostgreSQL already has {pg_count} rows (already migrated?)")
            table_counts[table_name] = pg_count
            continue

        # Read all rows from SQLite
        try:
            result = sqlite_conn.execute(text(f"SELECT * FROM {table_name}"))
            columns = list(result.keys())
            rows = result.fetchall()
        except Exception as e:
            print(f"  [ERROR] {table_name}: could not read from SQLite: {e}")
            continue

        if not rows:
            print(f"  [SKIP] {table_name}: 0 rows")
            table_counts[table_name] = 0
            continue

        # Get JSON columns for this table
        json_cols = JSON_COLUMNS.get(table_name, [])

        # Build parameterized INSERT statement
        col_list = ', '.join([f'"{c}"' for c in columns])
        param_list = ', '.join([f':{c}' for c in columns])
        insert_sql = text(f'INSERT INTO {table_name} ({col_list}) VALUES ({param_list})')

        # Insert in batches
        batch_size = 100
        inserted = 0

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            row_dicts = []

            for row in batch:
                row_dict = dict(zip(columns, row))

                # Convert JSON text to Python objects for PostgreSQL
                for json_col in json_cols:
                    if json_col in row_dict and row_dict[json_col] is not None:
                        val = row_dict[json_col]
                        if isinstance(val, str):
                            try:
                                row_dict[json_col] = json.loads(val)
                            except (json.JSONDecodeError, TypeError):
                                pass  # Keep as-is if not valid JSON

                row_dicts.append(row_dict)

            try:
                db.session.execute(insert_sql, row_dicts)
                inserted += len(batch)
            except Exception as e:
                db.session.rollback()
                print(f"  [ERROR] {table_name}: batch insert failed at row {i}: {e}")
                # Try row-by-row for this batch
                for row_dict in row_dicts:
                    try:
                        db.session.execute(insert_sql, row_dict)
                        inserted += 1
                    except Exception as row_error:
                        print(f"    [WARN] Skipping row in {table_name}: {row_error}")

        db.session.commit()
        total_rows += inserted
        table_counts[table_name] = inserted
        print(f"  [OK] {table_name}: {inserted}/{len(rows)} rows copied")

    sqlite_conn.close()
    print(f"\n[INFO] Total rows copied: {total_rows}")

    # ============================================
    # RESET POSTGRESQL SEQUENCES
    # ============================================
    print("\n[INFO] Resetting PostgreSQL sequences...")
    for table_name in TABLE_ORDER:
        try:
            # Check if table has a sequence for 'id' column
            result = db.session.execute(text(
                f"SELECT pg_get_serial_sequence('{table_name}', 'id')"
            ))
            seq_name = result.scalar()
            if seq_name:
                # Get max id
                max_id = db.session.execute(text(
                    f"SELECT COALESCE(MAX(id), 0) FROM {table_name}"
                )).scalar()
                if max_id and max_id > 0:
                    db.session.execute(text(
                        f"SELECT setval('{seq_name}', {max_id})"
                    ))
                    print(f"  [SEQ] {table_name}: reset to {max_id}")
        except Exception as e:
            # Table might not have an 'id' column or sequence
            pass

    db.session.commit()

    # ============================================
    # VERIFY MIGRATION (compare row counts)
    # ============================================
    print("\n[INFO] Verifying migration...")
    sqlite_conn = sqlite_engine.connect()
    all_ok = True

    for table_name in TABLE_ORDER:
        if table_name not in sqlite_tables:
            continue

        sqlite_count = sqlite_conn.execute(
            text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar()

        pg_count = db.session.execute(
            text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar()

        status = "OK" if sqlite_count == pg_count else "MISMATCH"
        if status == "MISMATCH":
            all_ok = False

        if sqlite_count > 0 or pg_count > 0:
            print(f"  {table_name}: SQLite={sqlite_count} PostgreSQL={pg_count} [{status}]")

    sqlite_conn.close()

    if all_ok:
        print("\n[SUCCESS] All row counts match!")
    else:
        print("\n[WARNING] Some row counts don't match. Check the output above.")
        sys.exit(1)

print("\n[DONE] Migration completed successfully!")
MIGRATE_SCRIPT

# Run the migration script with proper environment
log_message "Running migration..." "$BLUE"
ALGOMIRROR_PG_URL="$PG_URL" \
ALGOMIRROR_SQLITE_DB="$SQLITE_DB" \
$VENV_PYTHON /tmp/algomirror_migrate.py

MIGRATE_EXIT=$?
rm -f /tmp/algomirror_migrate.py

if [ $MIGRATE_EXIT -ne 0 ]; then
    log_message "\nMigration failed! Your SQLite database is untouched." "$RED"
    log_message "Backup: $BACKUP_FILE" "$NC"
    log_message "Starting AlgoMirror with original SQLite..." "$YELLOW"
    systemctl start algomirror
    exit 1
fi

# ============================================
# STAMP ALEMBIC VERSION
# ============================================
log_message "\nStamping Alembic migration version..." "$BLUE"
cd "$BASE_PATH"
DATABASE_URL="$PG_URL" $FLASK_CMD db stamp head 2>/dev/null || true
log_message "Alembic version stamped" "$GREEN"

# ============================================
# UPDATE .env FILE
# ============================================
log_message "\nUpdating .env configuration..." "$BLUE"

if [ -f "$ENV_FILE" ]; then
    # Backup current .env
    ENV_BACKUP="${ENV_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
    cp "$ENV_FILE" "$ENV_BACKUP"
    log_message "  .env backup: $ENV_BACKUP" "$GREEN"

    # Update DATABASE_URL
    if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$PG_URL|" "$ENV_FILE"
        log_message "  Updated DATABASE_URL in .env" "$GREEN"
    else
        echo "DATABASE_URL=$PG_URL" >> "$ENV_FILE"
        log_message "  Added DATABASE_URL to .env" "$GREEN"
    fi
else
    log_message "  .env not found at $ENV_FILE" "$YELLOW"
    log_message "  You must manually set: DATABASE_URL=$PG_URL" "$YELLOW"
fi

# ============================================
# RESTART SERVICE
# ============================================
log_message "\nStarting AlgoMirror with PostgreSQL..." "$BLUE"
systemctl start algomirror
sleep 3

if systemctl is-active --quiet algomirror; then
    log_message "AlgoMirror is running with PostgreSQL" "$GREEN"
else
    log_message "AlgoMirror failed to start. Check logs:" "$RED"
    log_message "  sudo journalctl -u algomirror -n 50" "$NC"
    log_message "\nTo revert to SQLite:" "$YELLOW"
    log_message "  cp $ENV_BACKUP $ENV_FILE" "$NC"
    log_message "  systemctl restart algomirror" "$NC"
fi

# ============================================
# CLEANUP
# ============================================
rm -f /tmp/algomirror_pg_url.tmp

# ============================================
# SUMMARY
# ============================================
echo ""
log_message "============================================" "$GREEN"
log_message "  Migration Complete" "$GREEN"
log_message "============================================" "$GREEN"
echo ""
log_message "Database:     PostgreSQL" "$NC"
log_message "SQLite backup: $BACKUP_FILE" "$NC"
log_message ".env backup:   $ENV_BACKUP" "$NC"
echo ""
log_message "To verify:" "$YELLOW"
log_message "  1. Open AlgoMirror in browser" "$NC"
log_message "  2. Check dashboard loads correctly" "$NC"
log_message "  3. Verify strategy tracking shows existing data" "$NC"
echo ""
log_message "To revert to SQLite if needed:" "$YELLOW"
log_message "  cp $ENV_BACKUP $ENV_FILE" "$NC"
log_message "  systemctl restart algomirror" "$NC"
log_message "============================================" "$GREEN"
