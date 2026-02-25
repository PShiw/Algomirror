"""
Database Migration Runner
Run all pending migrations from the upgrade folder.

Usage:
    cd migrate
    uv run migrate_all.py
"""

import os
import sys
import importlib.util

# Add parent directory to path for app imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text


def get_applied_migrations(app):
    """Get list of already applied migrations from database"""
    with app.app_context():
        # Detect database type for compatible DDL
        db_uri = str(db.engine.url)
        is_postgres = 'postgresql' in db_uri

        # Create table if it doesn't exist (database-agnostic syntax)
        if is_postgres:
            create_sql = """
                CREATE TABLE IF NOT EXISTS applied_migrations (
                    id SERIAL PRIMARY KEY,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
        else:
            create_sql = """
                CREATE TABLE IF NOT EXISTS applied_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """

        db.session.execute(text(create_sql))
        db.session.commit()

        try:
            result = db.session.execute(text(
                "SELECT migration_name FROM applied_migrations ORDER BY applied_at"
            ))
            applied = [row[0] for row in result.fetchall()]
        except Exception:
            applied = []

        # On PostgreSQL with empty tracking table, seed all SQLite-era migrations
        # as already applied (they ran on SQLite before the PostgreSQL migration)
        if is_postgres and not applied:
            sqlite_migrations = [
                '001_add_next_month_lot_size',
                '002_add_product_to_strategy_executions',
                '003_add_trailing_sl_tracking',
                '004_add_supertrend_exit_reason',
                '005_add_risk_exit_reasons',
                '006_add_trailing_sl_initial_stop',
                '007_add_margin_source_to_trade_qualities',
                '008_add_option_buying_premium',
                '009_add_performance_indexes',
                '010_add_2026_holidays',
                '011_update_nifty_banknifty_lot_sizes',
            ]
            for mig in sqlite_migrations:
                db.session.execute(
                    text("INSERT INTO applied_migrations (migration_name) VALUES (:name) ON CONFLICT DO NOTHING"),
                    {"name": mig}
                )
            db.session.commit()
            print(f"Seeded {len(sqlite_migrations)} pre-existing migrations (SQLite era)")
            applied = sqlite_migrations

        return applied


def mark_migration_applied(app, migration_name):
    """Mark a migration as applied"""
    with app.app_context():
        db.session.execute(
            text("INSERT INTO applied_migrations (migration_name) VALUES (:name)"),
            {"name": migration_name}
        )
        db.session.commit()


def run_migrations():
    """Run all pending migrations"""
    app = create_app()

    # Get already applied migrations
    applied = get_applied_migrations(app)
    print(f"Already applied migrations: {len(applied)}")

    # Get all migration files from upgrade folder
    upgrade_dir = os.path.join(os.path.dirname(__file__), 'upgrade')
    migration_files = sorted([
        f for f in os.listdir(upgrade_dir)
        if f.endswith('.py') and not f.startswith('__')
    ])

    pending_count = 0
    for migration_file in migration_files:
        migration_name = migration_file[:-3]  # Remove .py extension

        if migration_name in applied:
            print(f"  [SKIP] {migration_name} (already applied)")
            continue

        print(f"  [RUN]  {migration_name}...", end=" ")

        # Load and run the migration
        spec = importlib.util.spec_from_file_location(
            migration_name,
            os.path.join(upgrade_dir, migration_file)
        )
        module = importlib.util.module_from_spec(spec)

        try:
            spec.loader.exec_module(module)

            # Run the upgrade function
            with app.app_context():
                module.upgrade(db)

            # Mark as applied
            mark_migration_applied(app, migration_name)
            print("OK")
            pending_count += 1

        except Exception as e:
            print(f"FAILED: {e}")
            return False

    if pending_count == 0:
        print("\nNo pending migrations.")
    else:
        print(f"\nApplied {pending_count} migration(s) successfully.")

    return True


if __name__ == "__main__":
    print("=" * 50)
    print("AlgoMirror Database Migration")
    print("=" * 50)

    success = run_migrations()
    sys.exit(0 if success else 1)
