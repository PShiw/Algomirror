"""
Migration: Add exit retry tracking columns to strategy_executions table

These columns prevent duplicate exit orders by tracking exit attempts:
- exit_retry_after: Don't retry before this timestamp (10s after attempt)
- exit_attempt_count: Number of exit attempts made
- exit_pending_since: When exit was first attempted (for timeout tracking)
- exit_broker_verified: True if broker confirmed no exit order exists

The duplicate exit order problem occurs when:
1. Exit order is placed but confirmation is delayed/lost
2. Code treats it as failure and reverts status to 'entered'
3. Next risk check sees status='entered' and places another exit order

This fix:
1. Keeps status as 'exit_pending' even on failures (not reverting to 'entered')
2. Waits 10 seconds before allowing retry
3. Verifies with broker if exit order exists before placing new one
"""

from sqlalchemy import text


def upgrade(db):
    """Add exit retry tracking columns to strategy_executions table"""

    # Check existing columns
    result = db.session.execute(text("PRAGMA table_info(strategy_executions)"))
    columns = [row[1] for row in result.fetchall()]

    # Columns to add with their SQL definitions
    columns_to_add = [
        ('exit_retry_after', 'DATETIME'),
        ('exit_attempt_count', 'INTEGER DEFAULT 0'),
        ('exit_pending_since', 'DATETIME'),
        ('exit_broker_verified', 'BOOLEAN DEFAULT 0')
    ]

    added_count = 0
    for col_name, col_type in columns_to_add:
        if col_name not in columns:
            db.session.execute(text(
                f"ALTER TABLE strategy_executions ADD COLUMN {col_name} {col_type}"
            ))
            print(f"  Added column: {col_name}")
            added_count += 1
        else:
            print(f"  Column {col_name} already exists, skipping")

    if added_count > 0:
        db.session.commit()
        print(f"  Added {added_count} new column(s)")
    else:
        print("  No new columns added")


def downgrade(db):
    """Remove exit retry tracking columns (SQLite doesn't support DROP COLUMN easily)"""
    # SQLite doesn't support DROP COLUMN directly
    # Would need to recreate table - not implemented for simplicity
    pass
