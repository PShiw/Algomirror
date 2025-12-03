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
        try:
            result = db.session.execute(text(
                "SELECT migration_name FROM applied_migrations ORDER BY applied_at"
            ))
            return [row[0] for row in result.fetchall()]
        except Exception:
            # Table doesn't exist yet, create it
            db.session.execute(text("""
                CREATE TABLE IF NOT EXISTS applied_migrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    migration_name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            db.session.commit()
            return []


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
