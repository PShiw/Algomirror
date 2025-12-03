"""
Migration: Add next_month_lot_size column to trading_settings table

This column stores the lot size for next month contracts which may differ
from current month due to NSE circular changes (effective Jan 2025).
"""

from sqlalchemy import text


def upgrade(db):
    """Add next_month_lot_size column to trading_settings table"""

    # Check if column already exists
    result = db.session.execute(text("PRAGMA table_info(trading_settings)"))
    columns = [row[1] for row in result.fetchall()]

    if 'next_month_lot_size' not in columns:
        db.session.execute(text(
            "ALTER TABLE trading_settings ADD COLUMN next_month_lot_size INTEGER"
        ))
        db.session.commit()
        print("Added next_month_lot_size column")
    else:
        print("Column already exists, skipping")


def downgrade(db):
    """Remove next_month_lot_size column (SQLite doesn't support DROP COLUMN easily)"""
    # SQLite doesn't support DROP COLUMN directly
    # Would need to recreate table - not implemented for simplicity
    pass
