# AlgoMirror - Features Implementation Guide

## Feature Overview

This guide provides detailed implementation instructions for all major features in AlgoMirror, including multi-account management, WebSocket integration, option chain monitoring, and trading operations.

## 1. Multi-Account Management

### Account Model Implementation

```python
# app/models.py
class TradingAccount(db.Model):
    __tablename__ = 'trading_accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    broker = db.Column(db.String(50), nullable=False)
    api_key_encrypted = db.Column(db.Text)
    host_url = db.Column(db.String(200), default='http://127.0.0.1:5000')
    websocket_url = db.Column(db.String(200), default='ws://127.0.0.1:8765')
    is_primary = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', backref='trading_accounts')
    
    def set_as_primary(self):
        """Set this account as primary, unset others"""
        TradingAccount.query.filter_by(
            user_id=self.user_id
        ).update({'is_primary': False})
        
        self.is_primary = True
        db.session.commit()
        
        # Trigger option chain startup
        from app.utils.option_chain import start_option_chains
        start_option_chains(self)
```

### Account Management Routes

```python
# app/accounts/routes.py
@accounts_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_account():
    form = AccountForm()
    
    if form.validate_on_submit():
        # Test connection before saving
        test_result = test_connection(
            form.host_url.data,
            form.api_key.data
        )
        
        if test_result['success']:
            account = TradingAccount(
                user_id=current_user.id,
                account_name=form.account_name.data,
                broker=test_result.get('broker', 'Unknown'),
                host_url=form.host_url.data,
                websocket_url=form.websocket_url.data
            )
            account.set_api_key(form.api_key.data)
            
            # Set as primary if first account
            if current_user.trading_accounts.count() == 0:
                account.is_primary = True
            
            db.session.add(account)
            db.session.commit()
            
            flash(f'Account {account.account_name} added successfully')
            return redirect(url_for('accounts.list'))
        else:
            flash(f'Connection failed: {test_result["message"]}')
    
    return render_template('accounts/add.html', form=form)
```

### Account Switching

```python
@accounts_bp.route('/switch/<int:account_id>', methods=['POST'])
@login_required
def switch_primary(account_id):
    account = TradingAccount.query.get_or_404(account_id)
    
    if account.user_id != current_user.id:
        abort(403)
    
    account.set_as_primary()
    
    # Update WebSocket connections
    websocket_manager.switch_account(account)
    
    flash(f'Switched to {account.account_name}')
    return redirect(url_for('main.dashboard'))
```

## 2. WebSocket Real-Time Data

### WebSocket Manager Implementation

```python
# app/utils/websocket_manager.py
class ProfessionalWebSocketManager:
    def __init__(self):
        self.connection_pool = {}
        self.data_processor = WebSocketDataProcessor()
        self.subscriptions = set()
        self.active = False
        
    def initialize_for_account(self, account, backup_accounts=None):
        """Initialize WebSocket for account with failover"""
        self.create_connection_pool(account, backup_accounts)
        
        # Connect to primary account
        success = self.connect(
            account.websocket_url,
            account.get_api_key()
        )
        
        if success:
            logger.info(f"WebSocket connected for {account.account_name}")
            return True
        else:
            logger.error(f"Failed to connect WebSocket for {account.account_name}")
            return False
    
    def subscribe_option_chain(self, underlying, expiry, strikes):
        """Subscribe to option chain symbols"""
        instruments = []
        
        for strike in strikes:
            # Call option
            instruments.append({
                'symbol': f"{underlying}{expiry}{strike}CE",
                'exchange': 'NFO'
            })
            
            # Put option
            instruments.append({
                'symbol': f"{underlying}{expiry}{strike}PE",
                'exchange': 'NFO'
            })
        
        # Subscribe with depth mode for market depth
        self.subscribe_batch(instruments, mode='depth')
```

### WebSocket Data Processing

```python
class WebSocketDataProcessor:
    def __init__(self):
        self.handlers = {
            'quote': [],
            'depth': [],
            'ltp': []
        }
        
    def process_market_data(self, data):
        """Route data to appropriate handlers"""
        mode = data.get('mode', 'ltp')
        
        for handler in self.handlers.get(mode, []):
            try:
                handler(data)
            except Exception as e:
                logger.error(f"Handler error: {e}")
```

### Real-Time UI Updates

```javascript
// app/static/js/websocket_client.js
class WebSocketClient {
    constructor(accountId) {
        this.accountId = accountId;
        this.eventSource = null;
        this.reconnectAttempts = 0;
    }
    
    connect() {
        // Use Server-Sent Events for real-time updates
        this.eventSource = new EventSource(`/api/stream/${this.accountId}`);
        
        this.eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleUpdate(data);
        };
        
        this.eventSource.onerror = () => {
            this.handleError();
        };
    }
    
    handleUpdate(data) {
        // Update UI based on data type
        if (data.type === 'position') {
            this.updatePosition(data);
        } else if (data.type === 'option_chain') {
            this.updateOptionChain(data);
        }
    }
    
    updatePosition(data) {
        const row = document.querySelector(`[data-symbol="${data.symbol}"]`);
        if (row) {
            row.querySelector('.ltp').textContent = data.ltp.toFixed(2);
            row.querySelector('.pnl').textContent = data.pnl.toFixed(2);
            
            // Color code P&L
            const pnlCell = row.querySelector('.pnl');
            pnlCell.className = data.pnl >= 0 ? 'text-success' : 'text-danger';
        }
    }
}
```

## 3. Option Chain Monitoring

### Option Chain Manager

```python
# app/utils/option_chain.py
class OptionChainManager:
    def __init__(self, underlying, expiry):
        self.underlying = underlying
        self.expiry = expiry
        self.strike_step = 50 if underlying == 'NIFTY' else 100
        self.option_data = {}
        self.monitoring_active = False
        
    def start_monitoring(self):
        """Start background monitoring"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        
        # Calculate strikes
        self.calculate_strikes()
        
        # Subscribe via WebSocket
        self.subscribe_to_websocket()
        
        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self.monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
    
    def calculate_strikes(self):
        """Calculate strike range around ATM"""
        # Get underlying LTP
        ltp = self.get_underlying_ltp()
        
        # Calculate ATM
        self.atm_strike = round(ltp / self.strike_step) * self.strike_step
        
        # Generate strike range (ATM ± 20 strikes)
        self.strikes = []
        for i in range(-20, 21):
            strike = self.atm_strike + (i * self.strike_step)
            self.strikes.append({
                'strike': strike,
                'tag': self.get_strike_tag(i)
            })
    
    def get_strike_tag(self, offset):
        """Generate strike tag (ITM20...ATM...OTM20)"""
        if offset == 0:
            return 'ATM'
        elif offset < 0:
            return f'ITM{abs(offset)}'
        else:
            return f'OTM{offset}'
    
    def process_depth_update(self, data):
        """Process market depth update"""
        symbol = data['symbol']
        
        # Parse symbol to get strike and type
        strike_info = self.parse_option_symbol(symbol)
        
        if strike_info:
            # Update option data with depth
            self.option_data[symbol] = {
                'strike': strike_info['strike'],
                'type': strike_info['type'],
                'ltp': data.get('ltp', 0),
                'bid': data.get('bids', [{}])[0].get('price', 0),
                'ask': data.get('asks', [{}])[0].get('price', 0),
                'bid_qty': data.get('bids', [{}])[0].get('quantity', 0),
                'ask_qty': data.get('asks', [{}])[0].get('quantity', 0),
                'volume': data.get('volume', 0),
                'oi': data.get('oi', 0),
                'updated_at': datetime.now()
            }
```

### Option Chain Display

```html
<!-- app/templates/trading/option_chain.html -->
<div class="option-chain-container">
    <div class="controls">
        <select id="underlying">
            <option value="NIFTY">NIFTY</option>
            <option value="BANKNIFTY">BANKNIFTY</option>
        </select>
        
        <select id="expiry">
            {% for expiry in expiries %}
            <option value="{{ expiry }}">{{ expiry }}</option>
            {% endfor %}
        </select>
    </div>
    
    <table class="option-chain-table">
        <thead>
            <tr>
                <th colspan="8">CALL</th>
                <th>Strike</th>
                <th>Tag</th>
                <th colspan="8">PUT</th>
            </tr>
            <tr>
                <!-- Call headers -->
                <th>OI</th>
                <th>Vol</th>
                <th>Bid Q</th>
                <th>Bid</th>
                <th>LTP</th>
                <th>Ask</th>
                <th>Ask Q</th>
                <th>Spread</th>
                <!-- Strike -->
                <th></th>
                <th></th>
                <!-- Put headers -->
                <th>Spread</th>
                <th>Ask Q</th>
                <th>Ask</th>
                <th>LTP</th>
                <th>Bid</th>
                <th>Bid Q</th>
                <th>Vol</th>
                <th>OI</th>
            </tr>
        </thead>
        <tbody id="option-chain-data">
            <!-- Dynamic rows -->
        </tbody>
    </table>
</div>
```

## 4. Trading Operations

### Order Management

```python
# app/trading/routes.py
@trading_bp.route('/place_order', methods=['POST'])
@login_required
def place_order():
    data = request.json
    account = get_primary_account()
    
    # Validate order parameters
    order_params = {
        'symbol': data['symbol'],
        'exchange': data['exchange'],
        'action': data['action'],  # BUY/SELL
        'quantity': int(data['quantity']),
        'order_type': data['order_type'],  # MARKET/LIMIT
        'price': float(data.get('price', 0)),
        'product': data.get('product', 'MIS')
    }
    
    # Place order via OpenAlgo
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    try:
        response = client.placeorder(order_params)
        
        if response.get('status') == 'success':
            # Store order in database
            order = Order(
                account_id=account.id,
                order_id=response['order_id'],
                symbol=order_params['symbol'],
                quantity=order_params['quantity'],
                price=order_params['price'],
                order_type=order_params['order_type'],
                status='PENDING'
            )
            db.session.add(order)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'order_id': response['order_id']
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400
```

### Position Management

```python
@trading_bp.route('/positions')
@login_required
def positions():
    account = get_primary_account()
    
    if not account:
        flash('No primary account configured')
        return redirect(url_for('accounts.add'))
    
    try:
        client = ExtendedOpenAlgoAPI(
            api_key=account.get_api_key(),
            host=account.host_url
        )
        
        positions = client.positionbook()
        
        # Calculate additional metrics
        for position in positions:
            position['pnl'] = calculate_pnl(position)
            position['pnl_percent'] = calculate_pnl_percent(position)
        
        return render_template(
            'trading/positions.html',
            positions=positions,
            account=account
        )
    except Exception as e:
        flash(f'Error fetching positions: {e}')
        return redirect(url_for('main.dashboard'))
```

### Smart Order Execution

```python
class SmartOrderExecutor:
    def __init__(self, option_chain_manager):
        self.option_chain = option_chain_manager
        
    def place_smart_order(self, symbol, action, quantity):
        """Place order with optimal pricing"""
        # Get market depth
        depth = self.option_chain.get_option_depth(symbol)
        
        if not depth:
            raise ValueError(f"No market data for {symbol}")
        
        # Determine execution price
        if action == 'BUY':
            # Place slightly above ask for quick execution
            execution_price = depth['ask'] * 1.001
        else:  # SELL
            # Place slightly below bid
            execution_price = depth['bid'] * 0.999
        
        # Check spread
        spread_percent = ((depth['ask'] - depth['bid']) / depth['ltp']) * 100
        
        if spread_percent > 2:  # Wide spread
            # Use limit order at mid price
            execution_price = (depth['ask'] + depth['bid']) / 2
            order_type = 'LIMIT'
        else:
            order_type = 'LIMIT'
        
        return {
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'order_type': order_type,
            'price': round(execution_price, 2)
        }
```

## 5. Dashboard Implementation

### Main Dashboard

```python
# app/main/routes.py
@main_bp.route('/dashboard')
@login_required
def dashboard():
    # Get user's accounts
    accounts = current_user.trading_accounts.filter_by(
        is_active=True
    ).all()
    
    primary_account = next(
        (acc for acc in accounts if acc.is_primary), 
        None
    )
    
    # Aggregate data
    dashboard_data = {
        'total_accounts': len(accounts),
        'primary_account': primary_account,
        'total_positions': 0,
        'total_pnl': 0,
        'websocket_status': 'disconnected'
    }
    
    if primary_account:
        try:
            # Get account data
            client = ExtendedOpenAlgoAPI(
                api_key=primary_account.get_api_key(),
                host=primary_account.host_url
            )
            
            # Funds
            funds = client.funds()
            dashboard_data['available_balance'] = funds.get('available_balance', 0)
            
            # Positions
            positions = client.positionbook()
            dashboard_data['total_positions'] = len(positions)
            dashboard_data['total_pnl'] = sum(
                p.get('pnl', 0) for p in positions
            )
            
            # WebSocket status
            dashboard_data['websocket_status'] = websocket_manager.get_status()
            
        except Exception as e:
            logger.error(f"Dashboard data error: {e}")
    
    return render_template(
        'main/dashboard.html',
        **dashboard_data
    )
```

### Dashboard UI

```html
<!-- app/templates/main/dashboard.html -->
{% extends "layout.html" %}

{% block content %}
<div class="dashboard">
    <!-- Account Summary -->
    <div class="stats-grid">
        <div class="stat-card">
            <h3>Active Accounts</h3>
            <div class="stat-value">{{ total_accounts }}</div>
        </div>
        
        <div class="stat-card">
            <h3>Available Balance</h3>
            <div class="stat-value">₹{{ available_balance|format_number }}</div>
        </div>
        
        <div class="stat-card">
            <h3>Open Positions</h3>
            <div class="stat-value">{{ total_positions }}</div>
        </div>
        
        <div class="stat-card">
            <h3>Total P&L</h3>
            <div class="stat-value {{ 'text-success' if total_pnl >= 0 else 'text-danger' }}">
                ₹{{ total_pnl|format_number }}
            </div>
        </div>
    </div>
    
    <!-- WebSocket Status -->
    <div class="connection-status">
        <span class="status-indicator {{ 'active' if websocket_status == 'connected' else 'inactive' }}"></span>
        WebSocket: {{ websocket_status }}
    </div>
    
    <!-- Quick Actions -->
    <div class="quick-actions">
        <a href="{{ url_for('trading.positions') }}" class="btn btn-primary">View Positions</a>
        <a href="{{ url_for('trading.option_chain') }}" class="btn btn-secondary">Option Chain</a>
        <a href="{{ url_for('accounts.list') }}" class="btn btn-outline">Manage Accounts</a>
    </div>
</div>
{% endblock %}
```

## 6. Failover Implementation

### Account Failover Logic

```python
class FailoverController:
    def __init__(self):
        self.primary_account = None
        self.backup_accounts = []
        self.failover_history = []
        
    def setup_failover_chain(self, user_id):
        """Setup failover hierarchy"""
        accounts = TradingAccount.query.filter_by(
            user_id=user_id,
            is_active=True
        ).order_by(
            TradingAccount.is_primary.desc()
        ).all()
        
        if accounts:
            self.primary_account = accounts[0]
            self.backup_accounts = accounts[1:]
    
    def handle_connection_failure(self):
        """Handle primary account failure"""
        if not self.backup_accounts:
            logger.error("No backup accounts available")
            return False
        
        # Get next backup
        next_account = self.backup_accounts.pop(0)
        
        # Record failover
        self.failover_history.append({
            'from': self.primary_account.account_name,
            'to': next_account.account_name,
            'timestamp': datetime.now(),
            'reason': 'connection_failure'
        })
        
        # Switch to backup
        self.primary_account = next_account
        
        # Reconnect WebSocket
        return websocket_manager.switch_account(next_account)
```

## 7. Activity Logging

### Comprehensive Logging

```python
# app/utils/logging.py
def log_user_activity(action, details=None):
    """Log user activity for audit"""
    activity = ActivityLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        details=details,
        ip_address=request.remote_addr,
        user_agent=request.user_agent.string,
        timestamp=datetime.utcnow()
    )
    
    db.session.add(activity)
    db.session.commit()

# Decorator for automatic logging
def log_activity(action):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            result = f(*args, **kwargs)
            log_user_activity(action, request.url)
            return result
        return decorated_function
    return decorator
```

## 8. Theme System

### Theme Implementation

```javascript
// app/static/js/theme.js
class ThemeManager {
    constructor() {
        this.theme = localStorage.getItem('theme') || 'light';
        this.applyTheme();
    }
    
    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.theme);
        this.updateToggleButton();
    }
    
    toggle() {
        this.theme = this.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('theme', this.theme);
        this.applyTheme();
    }
    
    updateToggleButton() {
        const btn = document.querySelector('.theme-toggle');
        if (btn) {
            btn.innerHTML = this.theme === 'light' 
                ? '<i class="fas fa-moon"></i>' 
                : '<i class="fas fa-sun"></i>';
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.themeManager = new ThemeManager();
});
```

## 9. Performance Optimization

### Caching Implementation

```python
# app/utils/cache.py
from cachetools import TTLCache
import threading

class DataCache:
    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=30)
        self.lock = threading.Lock()
    
    def get_or_fetch(self, key, fetch_func):
        """Get from cache or fetch fresh"""
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            
            data = fetch_func()
            self.cache[key] = data
            return data

# Usage
cache = DataCache()

def get_cached_positions(account_id):
    return cache.get_or_fetch(
        f'positions_{account_id}',
        lambda: fetch_positions_from_api(account_id)
    )
```

## 10. Error Handling

### Global Error Handler

```python
# app/__init__.py
@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    logger.error(f"Internal error: {error}")
    return render_template('errors/500.html'), 500

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"Unhandled exception: {error}", exc_info=True)
    
    if app.config['DEBUG']:
        raise error
    
    return render_template('errors/500.html'), 500
```

## Testing Features

### Unit Tests

```python
# tests/test_features.py
import unittest
from app import create_app, db
from app.models import User, TradingAccount

class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        
    def test_account_creation(self):
        """Test account creation"""
        with self.app.app_context():
            user = User(username='test')
            user.set_password('Test@1234')
            
            account = TradingAccount(
                user_id=user.id,
                account_name='Test Account',
                broker='TEST'
            )
            
            db.session.add(user)
            db.session.add(account)
            db.session.commit()
            
            self.assertIsNotNone(account.id)
    
    def test_websocket_connection(self):
        """Test WebSocket initialization"""
        # Test implementation
        pass
```

This comprehensive features implementation guide provides all the necessary code and instructions to build AlgoMirror's complete functionality.