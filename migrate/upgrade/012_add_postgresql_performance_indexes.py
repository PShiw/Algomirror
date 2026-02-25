"""
Migration: Add performance indexes for PostgreSQL

Migration 009 used sqlite_master (SQLite-specific) to check indexes.
After migrating to PostgreSQL, those indexes don't exist. This migration
creates all performance indexes using CREATE INDEX IF NOT EXISTS which
works on both SQLite (3.3+) and PostgreSQL (9.5+).

These indexes match the index=True declarations in models.py and cover
frequently queried foreign keys and filter columns.
"""

from sqlalchemy import text


def upgrade(db):
    """Add performance indexes (database-agnostic)"""

    indexes = [
        # Single-column FK indexes - PostgreSQL does NOT auto-index foreign keys
        ('ix_trading_accounts_user_id',
         'CREATE INDEX IF NOT EXISTS ix_trading_accounts_user_id ON trading_accounts(user_id)'),
        ('ix_trading_accounts_is_active',
         'CREATE INDEX IF NOT EXISTS ix_trading_accounts_is_active ON trading_accounts(is_active)'),

        ('ix_activity_logs_user_id',
         'CREATE INDEX IF NOT EXISTS ix_activity_logs_user_id ON activity_logs(user_id)'),
        ('ix_activity_logs_created_at',
         'CREATE INDEX IF NOT EXISTS ix_activity_logs_created_at ON activity_logs(created_at)'),

        ('ix_orders_account_id',
         'CREATE INDEX IF NOT EXISTS ix_orders_account_id ON orders(account_id)'),

        ('ix_strategies_user_id',
         'CREATE INDEX IF NOT EXISTS ix_strategies_user_id ON strategies(user_id)'),
        ('ix_strategies_is_active',
         'CREATE INDEX IF NOT EXISTS ix_strategies_is_active ON strategies(is_active)'),

        ('ix_strategy_executions_strategy_id',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_strategy_id ON strategy_executions(strategy_id)'),
        ('ix_strategy_executions_account_id',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_account_id ON strategy_executions(account_id)'),
        ('ix_strategy_executions_status',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_status ON strategy_executions(status)'),
        ('ix_strategy_executions_created_at',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_created_at ON strategy_executions(created_at)'),

        ('ix_trading_settings_user_id',
         'CREATE INDEX IF NOT EXISTS ix_trading_settings_user_id ON trading_settings(user_id)'),
        ('ix_trading_settings_symbol',
         'CREATE INDEX IF NOT EXISTS ix_trading_settings_symbol ON trading_settings(symbol)'),

        # Composite indexes for common query patterns
        ('ix_strategy_executions_strategy_status',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_strategy_status ON strategy_executions(strategy_id, status)'),
        ('ix_strategy_executions_account_status',
         'CREATE INDEX IF NOT EXISTS ix_strategy_executions_account_status ON strategy_executions(account_id, status)'),
        ('ix_strategies_user_active',
         'CREATE INDEX IF NOT EXISTS ix_strategies_user_active ON strategies(user_id, is_active)'),
        ('ix_trading_accounts_user_active',
         'CREATE INDEX IF NOT EXISTS ix_trading_accounts_user_active ON trading_accounts(user_id, is_active)'),
    ]

    created_count = 0
    skipped_count = 0

    for index_name, create_sql in indexes:
        try:
            db.session.execute(text(create_sql))
            print(f"  Created index {index_name}")
            created_count += 1
        except Exception as e:
            error_msg = str(e).lower()
            if 'already exists' in error_msg or 'duplicate' in error_msg:
                print(f"  Index {index_name} already exists, skipping")
                skipped_count += 1
            else:
                print(f"  Failed to create {index_name}: {e}")

    db.session.commit()
    print(f"\nIndexes: {created_count} created, {skipped_count} already existed")
