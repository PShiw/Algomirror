# AlgoMirror - Database Schema Documentation

## Database Overview

AlgoMirror uses SQLAlchemy ORM with support for both SQLite (development) and PostgreSQL (production). The schema is designed for scalability, data integrity, and efficient querying.

## Core Tables

### 1. Users Table

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    
    INDEX idx_username (username),
    INDEX idx_email (email)
);
```

**Model Definition:**
```python
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    trading_accounts = db.relationship('TradingAccount', backref='user', lazy='dynamic')
    activity_logs = db.relationship('ActivityLog', backref='user', lazy='dynamic')
```

### 2. Trading Accounts Table

```sql
CREATE TABLE trading_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    broker VARCHAR(50) NOT NULL,
    api_key_encrypted TEXT,
    host_url VARCHAR(200) DEFAULT 'http://127.0.0.1:5000',
    websocket_url VARCHAR(200) DEFAULT 'ws://127.0.0.1:8765',
    is_primary BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    last_connected TIMESTAMP,
    connection_status VARCHAR(20) DEFAULT 'disconnected',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_is_primary (is_primary),
    INDEX idx_is_active (is_active)
);
```

**Model Definition:**
```python
class TradingAccount(db.Model):
    __tablename__ = 'trading_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    broker = db.Column(db.String(50), nullable=False)
    api_key_encrypted = db.Column(db.Text)
    host_url = db.Column(db.String(200), default='http://127.0.0.1:5000')
    websocket_url = db.Column(db.String(200), default='ws://127.0.0.1:8765')
    is_primary = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    last_connected = db.Column(db.DateTime)
    connection_status = db.Column(db.String(20), default='disconnected')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    orders = db.relationship('Order', backref='account', lazy='dynamic')
    positions = db.relationship('Position', backref='account', lazy='dynamic')
    holdings = db.relationship('Holding', backref='account', lazy='dynamic')
```

### 3. Orders Table

```sql
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    order_id VARCHAR(50) NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- BUY/SELL
    quantity INTEGER NOT NULL,
    order_type VARCHAR(20) NOT NULL,  -- MARKET/LIMIT/SL/SLM
    price DECIMAL(10,2),
    trigger_price DECIMAL(10,2),
    product VARCHAR(10),  -- MIS/CNC/NRML
    status VARCHAR(20) NOT NULL,  -- PENDING/EXECUTED/CANCELLED/REJECTED
    filled_quantity INTEGER DEFAULT 0,
    average_price DECIMAL(10,2),
    placed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE,
    INDEX idx_account_id (account_id),
    INDEX idx_order_id (order_id),
    INDEX idx_symbol (symbol),
    INDEX idx_status (status),
    INDEX idx_placed_at (placed_at)
);
```

**Model Definition:**
```python
class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('trading_accounts.id'), nullable=False)
    order_id = db.Column(db.String(50), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    exchange = db.Column(db.String(10), nullable=False)
    action = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    order_type = db.Column(db.String(20), nullable=False)
    price = db.Column(db.Float)
    trigger_price = db.Column(db.Float)
    product = db.Column(db.String(10))
    status = db.Column(db.String(20), nullable=False)
    filled_quantity = db.Column(db.Integer, default=0)
    average_price = db.Column(db.Float)
    placed_at = db.Column(db.DateTime, default=datetime.utcnow)
    executed_at = db.Column(db.DateTime)
```

### 4. Positions Table

```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    product VARCHAR(10),
    average_price DECIMAL(10,2) NOT NULL,
    current_price DECIMAL(10,2),
    pnl DECIMAL(10,2),
    pnl_percent DECIMAL(5,2),
    day_change DECIMAL(10,2),
    day_change_percent DECIMAL(5,2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE,
    INDEX idx_account_id (account_id),
    INDEX idx_symbol (symbol),
    UNIQUE KEY unique_position (account_id, symbol, product)
);
```

**Model Definition:**
```python
class Position(db.Model):
    __tablename__ = 'positions'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('trading_accounts.id'), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    exchange = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    product = db.Column(db.String(10))
    average_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float)
    pnl = db.Column(db.Float)
    pnl_percent = db.Column(db.Float)
    day_change = db.Column(db.Float)
    day_change_percent = db.Column(db.Float)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('account_id', 'symbol', 'product', name='unique_position'),
    )
```

### 5. Holdings Table

```sql
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    symbol VARCHAR(50) NOT NULL,
    exchange VARCHAR(10) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10,2) NOT NULL,
    current_price DECIMAL(10,2),
    pnl DECIMAL(10,2),
    pnl_percent DECIMAL(5,2),
    invested_value DECIMAL(10,2),
    current_value DECIMAL(10,2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE,
    INDEX idx_account_id (account_id),
    INDEX idx_symbol (symbol),
    UNIQUE KEY unique_holding (account_id, symbol)
);
```

**Model Definition:**
```python
class Holding(db.Model):
    __tablename__ = 'holdings'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('trading_accounts.id'), nullable=False)
    symbol = db.Column(db.String(50), nullable=False)
    exchange = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    average_price = db.Column(db.Float, nullable=False)
    current_price = db.Column(db.Float)
    pnl = db.Column(db.Float)
    pnl_percent = db.Column(db.Float)
    invested_value = db.Column(db.Float)
    current_value = db.Column(db.Float)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('account_id', 'symbol', name='unique_holding'),
    )
```

### 6. Activity Log Table

```sql
CREATE TABLE activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action VARCHAR(100) NOT NULL,
    details TEXT,
    ip_address VARCHAR(45),
    user_agent VARCHAR(200),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_user_id (user_id),
    INDEX idx_action (action),
    INDEX idx_timestamp (timestamp),
    INDEX idx_user_timestamp (user_id, timestamp)
);
```

**Model Definition:**
```python
class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.Index('idx_user_timestamp', 'user_id', 'timestamp'),
        db.Index('idx_action_timestamp', 'action', 'timestamp'),
    )
```

## Strategy-Related Tables

### 7. Strategies Table

```sql
CREATE TABLE strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    strategy_type VARCHAR(50),  -- momentum/mean_reversion/arbitrage
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Model Definition:**
```python
class Strategy(db.Model):
    __tablename__ = 'strategies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    strategy_type = db.Column(db.String(50))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    deployments = db.relationship('StrategyDeployment', backref='strategy', lazy='dynamic')
```

### 8. Strategy Deployments Table

```sql
CREATE TABLE strategy_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    capital_allocated DECIMAL(10,2),
    max_positions INTEGER DEFAULT 5,
    status VARCHAR(20) DEFAULT 'inactive',  -- active/inactive/paused
    started_at TIMESTAMP,
    stopped_at TIMESTAMP,
    total_pnl DECIMAL(10,2) DEFAULT 0,
    
    FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE,
    INDEX idx_strategy_id (strategy_id),
    INDEX idx_account_id (account_id),
    INDEX idx_status (status)
);
```

**Model Definition:**
```python
class StrategyDeployment(db.Model):
    __tablename__ = 'strategy_deployments'
    
    id = db.Column(db.Integer, primary_key=True)
    strategy_id = db.Column(db.Integer, db.ForeignKey('strategies.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('trading_accounts.id'), nullable=False)
    capital_allocated = db.Column(db.Float)
    max_positions = db.Column(db.Integer, default=5)
    status = db.Column(db.String(20), default='inactive')
    started_at = db.Column(db.DateTime)
    stopped_at = db.Column(db.DateTime)
    total_pnl = db.Column(db.Float, default=0)
```

## Configuration Tables

### 9. Trading Hours Template Table

```sql
CREATE TABLE trading_hours_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'Asia/Kolkata',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 10. Trading Sessions Table

```sql
CREATE TABLE trading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,  -- 0=Monday, 6=Sunday
    pre_market_start TIME,
    pre_market_end TIME,
    market_open TIME,
    market_close TIME,
    post_market_start TIME,
    post_market_end TIME,
    is_trading_day BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (template_id) REFERENCES trading_hours_templates(id) ON DELETE CASCADE,
    INDEX idx_template_id (template_id),
    INDEX idx_day_of_week (day_of_week)
);
```

### 11. Market Holidays Table

```sql
CREATE TABLE market_holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    date DATE NOT NULL,
    description VARCHAR(200),
    holiday_type VARCHAR(50),  -- full_day/muhurat/special
    
    FOREIGN KEY (template_id) REFERENCES trading_hours_templates(id) ON DELETE CASCADE,
    INDEX idx_template_id (template_id),
    INDEX idx_date (date)
);
```

## WebSocket & Failover Tables

### 12. WebSocket Connections Table

```sql
CREATE TABLE websocket_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    connection_id VARCHAR(100) UNIQUE,
    status VARCHAR(20) DEFAULT 'disconnected',
    connected_at TIMESTAMP,
    disconnected_at TIMESTAMP,
    messages_received INTEGER DEFAULT 0,
    last_heartbeat TIMESTAMP,
    
    FOREIGN KEY (account_id) REFERENCES trading_accounts(id) ON DELETE CASCADE,
    INDEX idx_account_id (account_id),
    INDEX idx_status (status)
);
```

### 13. Failover Events Table

```sql
CREATE TABLE failover_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_account_id INTEGER,
    to_account_id INTEGER,
    reason VARCHAR(100),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    
    FOREIGN KEY (from_account_id) REFERENCES trading_accounts(id) ON DELETE SET NULL,
    FOREIGN KEY (to_account_id) REFERENCES trading_accounts(id) ON DELETE SET NULL,
    INDEX idx_timestamp (timestamp)
);
```

## Database Migrations

### Using Flask-Migrate

```bash
# Initialize migrations
flask db init

# Create a new migration
flask db migrate -m "Add new table"

# Apply migrations
flask db upgrade

# Rollback migrations
flask db downgrade
```

### Migration Example

```python
"""Add trading_accounts table

Revision ID: 001
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table('trading_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('account_name', sa.String(100), nullable=False),
        sa.Column('broker', sa.String(50), nullable=False),
        sa.Column('api_key_encrypted', sa.Text()),
        sa.Column('host_url', sa.String(200)),
        sa.Column('websocket_url', sa.String(200)),
        sa.Column('is_primary', sa.Boolean(), default=False),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_user_id', 'trading_accounts', ['user_id'])
    op.create_index('idx_is_primary', 'trading_accounts', ['is_primary'])

def downgrade():
    op.drop_index('idx_is_primary', 'trading_accounts')
    op.drop_index('idx_user_id', 'trading_accounts')
    op.drop_table('trading_accounts')
```

## Database Optimization

### 1. Indexes

```sql
-- Composite indexes for common queries
CREATE INDEX idx_orders_account_status ON orders(account_id, status);
CREATE INDEX idx_positions_account_symbol ON positions(account_id, symbol);
CREATE INDEX idx_activity_user_action ON activity_logs(user_id, action);

-- Covering indexes for performance
CREATE INDEX idx_accounts_user_primary ON trading_accounts(user_id, is_primary) 
    INCLUDE (account_name, broker);
```

### 2. Query Optimization

```python
# Efficient query with joins
def get_user_positions_summary(user_id):
    return db.session.query(
        TradingAccount.account_name,
        func.count(Position.id).label('position_count'),
        func.sum(Position.pnl).label('total_pnl')
    ).join(
        Position, TradingAccount.id == Position.account_id
    ).filter(
        TradingAccount.user_id == user_id
    ).group_by(
        TradingAccount.id
    ).all()
```

### 3. Connection Pooling

```python
# config.py
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
    'max_overflow': 20
}
```

## Database Maintenance

### 1. Regular Tasks

```sql
-- Cleanup old activity logs (keep 90 days)
DELETE FROM activity_logs 
WHERE timestamp < datetime('now', '-90 days');

-- Archive old orders (move to archive table)
INSERT INTO orders_archive 
SELECT * FROM orders 
WHERE placed_at < datetime('now', '-30 days');

DELETE FROM orders 
WHERE placed_at < datetime('now', '-30 days');
```

### 2. Backup Strategy

```bash
# SQLite backup
sqlite3 instance/algomirror.db ".backup backup/algomirror_$(date +%Y%m%d).db"

# PostgreSQL backup
pg_dump -U username -d algomirror > backup/algomirror_$(date +%Y%m%d).sql
```

### 3. Performance Monitoring

```sql
-- Check table sizes
SELECT 
    table_name,
    pg_size_pretty(pg_total_relation_size(table_name::regclass)) AS size
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY pg_total_relation_size(table_name::regclass) DESC;

-- Find slow queries
SELECT 
    query,
    calls,
    mean_exec_time,
    total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

## Data Integrity

### 1. Constraints

```python
# Ensure data integrity with constraints
class TradingAccount(db.Model):
    __table_args__ = (
        db.CheckConstraint('length(account_name) >= 3', name='check_account_name_length'),
        db.CheckConstraint("broker IN ('Zerodha', 'Upstox', 'AngelOne', ...)", name='check_valid_broker'),
        db.UniqueConstraint('user_id', 'account_name', name='unique_user_account'),
    )
```

### 2. Triggers

```sql
-- Update timestamp trigger
CREATE TRIGGER update_timestamp
AFTER UPDATE ON trading_accounts
FOR EACH ROW
BEGIN
    UPDATE trading_accounts 
    SET updated_at = CURRENT_TIMESTAMP 
    WHERE id = NEW.id;
END;
```

### 3. Foreign Key Actions

```python
# Cascade deletes for related data
account_id = db.Column(
    db.Integer, 
    db.ForeignKey('trading_accounts.id', ondelete='CASCADE'),
    nullable=False
)
```

This comprehensive database schema documentation provides the complete structure for AlgoMirror's data persistence layer.