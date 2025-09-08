# AlgoMirror - API Integration Guide

## Overview

AlgoMirror integrates with OpenAlgo's REST API and WebSocket services to provide real-time trading capabilities across multiple broker accounts. This guide covers all integration points, authentication methods, and implementation details.

## OpenAlgo API Integration

### 1. REST API Configuration

#### Base Configuration
```python
# Default OpenAlgo endpoints
OPENALGO_API_HOST = "http://127.0.0.1:5000"
OPENALGO_WS_HOST = "ws://127.0.0.1:8765"

# API Version
API_VERSION = "v1"
```

#### Extended OpenAlgo Client
```python
# app/utils/openalgo_client.py
from openalgo import api

class ExtendedOpenAlgoAPI(api):
    """Extended OpenAlgo client with additional features"""
    
    def __init__(self, api_key=None, host=None):
        super().__init__(api_key=api_key, host=host)
    
    def ping(self):
        """Test connection and validate API key"""
        endpoint = f"{self.host}/api/v1/ping"
        headers = {'Content-Type': 'application/json'}
        data = {'apikey': self.api_key}
        
        response = self.session.post(endpoint, json=data, headers=headers)
        return response.json()
```

### 2. Authentication Methods

#### API Key Authentication
```python
# Encrypted storage and retrieval
class TradingAccount(db.Model):
    api_key_encrypted = db.Column(db.Text)
    
    def set_api_key(self, api_key):
        """Encrypt and store API key"""
        cipher = Fernet(get_encryption_key())
        self.api_key_encrypted = cipher.encrypt(api_key.encode()).decode()
    
    def get_api_key(self):
        """Decrypt and return API key"""
        if not self.api_key_encrypted:
            return None
        cipher = Fernet(get_encryption_key())
        return cipher.decrypt(self.api_key_encrypted.encode()).decode()
```

#### Connection Testing
```python
def test_connection(host_url, api_key):
    """Validate OpenAlgo connection"""
    try:
        client = ExtendedOpenAlgoAPI(api_key=api_key, host=host_url)
        response = client.ping()
        
        if response.get('status') == 'success':
            return {
                'success': True,
                'broker': response.get('broker', 'Unknown'),
                'message': 'Connection successful'
            }
        else:
            return {
                'success': False,
                'message': response.get('message', 'Connection failed')
            }
    except Exception as e:
        return {
            'success': False,
            'message': str(e)
        }
```

## REST API Endpoints

### 1. Account Management APIs

#### Get Funds
```python
def get_funds(account):
    """Retrieve account funds"""
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    try:
        response = client.funds()
        return {
            'success': True,
            'data': response,
            'cached_at': datetime.now()
        }
    except Exception as e:
        logger.error(f"Failed to get funds: {e}")
        return {'success': False, 'error': str(e)}
```

#### Available Endpoints
```python
# Trading account endpoints
client.funds()           # Get account funds
client.orderbook()       # Get all orders
client.tradebook()       # Get executed trades
client.positionbook()    # Get open positions
client.holdings()        # Get holdings

# Order management endpoints
client.placeorder(data)  # Place new order
client.modifyorder(data) # Modify existing order
client.cancelorder(data) # Cancel order
client.closeposition(data) # Close position

# Market data endpoints
client.quotes(data)      # Get quotes
client.depth(data)       # Get market depth
client.history(data)     # Get historical data
```

### 2. Order Management APIs

#### Place Order
```python
def place_order(account, order_params):
    """Place order through OpenAlgo"""
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    order_data = {
        'symbol': order_params['symbol'],
        'exchange': order_params['exchange'],
        'action': order_params['action'],  # BUY/SELL
        'quantity': order_params['quantity'],
        'order_type': order_params['order_type'],  # MARKET/LIMIT
        'price': order_params.get('price', 0),
        'product': order_params.get('product', 'MIS'),  # MIS/CNC/NRML
        'trigger_price': order_params.get('trigger_price', 0)
    }
    
    try:
        response = client.placeorder(order_data)
        
        # Log order in database
        order = Order(
            account_id=account.id,
            order_id=response.get('order_id'),
            symbol=order_data['symbol'],
            quantity=order_data['quantity'],
            price=order_data['price'],
            status='PENDING'
        )
        db.session.add(order)
        db.session.commit()
        
        return {'success': True, 'order_id': response.get('order_id')}
    except Exception as e:
        return {'success': False, 'error': str(e)}
```

#### Modify Order
```python
def modify_order(account, order_id, modifications):
    """Modify existing order"""
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    modify_data = {
        'order_id': order_id,
        'quantity': modifications.get('quantity'),
        'order_type': modifications.get('order_type'),
        'price': modifications.get('price'),
        'trigger_price': modifications.get('trigger_price')
    }
    
    return client.modifyorder(modify_data)
```

### 3. Market Data APIs

#### Get Quotes
```python
def get_quotes(account, symbols):
    """Get real-time quotes for symbols"""
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    quotes_data = []
    for symbol in symbols:
        try:
            quote = client.quotes({
                'symbol': symbol['symbol'],
                'exchange': symbol['exchange']
            })
            quotes_data.append(quote)
        except Exception as e:
            logger.error(f"Failed to get quote for {symbol}: {e}")
    
    return quotes_data
```

#### Get Market Depth
```python
def get_market_depth(account, symbol, exchange):
    """Get market depth (order book)"""
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    return client.depth({
        'symbol': symbol,
        'exchange': exchange
    })
```

## WebSocket Integration

### 1. WebSocket Manager Implementation

#### Connection Setup
```python
class ProfessionalWebSocketManager:
    def connect(self, ws_url, api_key):
        """Establish WebSocket connection"""
        self.ws_url = ws_url
        self.api_key = api_key
        
        # Create WebSocket connection
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        # Start in separate thread
        self.ws_thread = threading.Thread(target=self.ws.run_forever)
        self.ws_thread.daemon = True
        self.ws_thread.start()
```

#### Authentication Protocol
```python
def authenticate(self):
    """Authenticate with WebSocket server"""
    auth_message = {
        "action": "authenticate",
        "api_key": self.api_key
    }
    self.ws.send(json.dumps(auth_message))
```

### 2. Subscription Management

#### Subscribe to Symbols
```python
def subscribe(self, symbol, exchange, mode='ltp'):
    """Subscribe to market data"""
    # Mode mapping
    mode_map = {
        'ltp': 1,      # Last traded price
        'quote': 2,    # Full quote
        'depth': 3     # Market depth
    }
    
    subscription = {
        'action': 'subscribe',
        'symbol': symbol,
        'exchange': exchange,
        'mode': mode_map.get(mode, 1),
        'depth': 5  # Depth levels for order book
    }
    
    self.ws.send(json.dumps(subscription))
```

#### Batch Subscriptions
```python
def subscribe_batch(self, instruments, mode='ltp'):
    """Subscribe to multiple instruments"""
    for instrument in instruments:
        self.subscribe(
            symbol=instrument['symbol'],
            exchange=instrument['exchange'],
            mode=mode
        )
        time.sleep(0.05)  # Prevent overwhelming server
```

### 3. Data Processing

#### Message Handler
```python
def on_message(self, ws, message):
    """Process incoming WebSocket messages"""
    try:
        data = json.loads(message)
        
        # Handle different message types
        if data.get("type") == "auth":
            self.handle_auth_response(data)
        elif data.get("type") == "subscribe":
            self.handle_subscription_response(data)
        elif data.get("type") == "market_data":
            self.handle_market_data(data)
        else:
            self.handle_unknown_message(data)
            
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON: {message}")
```

#### Market Data Processing
```python
def handle_market_data(self, data):
    """Process market data updates"""
    market_data = data.get('data', {})
    
    # Determine data type
    if data.get('mode') == 3:  # Depth mode
        self.process_depth_data(market_data)
    elif data.get('mode') == 2:  # Quote mode
        self.process_quote_data(market_data)
    else:  # LTP mode
        self.process_ltp_data(market_data)
```

## Option Chain Integration

### 1. Option Chain Setup

#### Initialize Option Chains
```python
class OptionChainManager:
    def initialize(self, underlying, expiry):
        """Setup option chain monitoring"""
        self.underlying = underlying  # NIFTY/BANKNIFTY
        self.expiry = expiry
        
        # Calculate strikes
        self.calculate_atm()
        self.generate_strikes()
        
        # Setup WebSocket subscriptions
        self.setup_subscriptions()
```

#### Strike Calculation
```python
def calculate_atm(self):
    """Calculate At-The-Money strike"""
    # Get underlying LTP
    quote = self.get_underlying_quote()
    ltp = quote['ltp']
    
    # Round to nearest strike
    if self.underlying == 'NIFTY':
        self.atm_strike = round(ltp / 50) * 50
    else:  # BANKNIFTY
        self.atm_strike = round(ltp / 100) * 100
```

### 2. Subscription Strategy

#### Generate Symbol List
```python
def generate_option_symbols(self):
    """Generate option symbols for subscription"""
    symbols = []
    
    for strike in self.strikes:
        # Call option
        ce_symbol = f"{self.underlying}{self.expiry}{strike}CE"
        symbols.append({
            'symbol': ce_symbol,
            'exchange': 'NFO',
            'type': 'CE',
            'strike': strike
        })
        
        # Put option
        pe_symbol = f"{self.underlying}{self.expiry}{strike}PE"
        symbols.append({
            'symbol': pe_symbol,
            'exchange': 'NFO',
            'type': 'PE',
            'strike': strike
        })
    
    return symbols
```

#### Subscribe to Options
```python
def subscribe_option_chain(self):
    """Subscribe to all option strikes"""
    symbols = self.generate_option_symbols()
    
    # Subscribe in depth mode for market depth
    self.websocket_manager.subscribe_batch(
        instruments=symbols,
        mode='depth'
    )
```

## Internal API Endpoints

### 1. RESTful API Routes

#### Account APIs
```python
@api_bp.route('/accounts', methods=['GET'])
@login_required
@api_rate_limit()
def get_accounts():
    """Get all user accounts"""
    accounts = TradingAccount.query.filter_by(
        user_id=current_user.id
    ).all()
    
    return jsonify([{
        'id': acc.id,
        'name': acc.account_name,
        'broker': acc.broker,
        'is_primary': acc.is_primary,
        'is_active': acc.is_active
    } for acc in accounts])
```

#### Trading Data APIs
```python
@api_bp.route('/positions/<int:account_id>', methods=['GET'])
@login_required
@api_rate_limit()
def get_positions(account_id):
    """Get positions for account"""
    account = TradingAccount.query.get_or_404(account_id)
    
    # Verify ownership
    if account.user_id != current_user.id:
        abort(403)
    
    client = ExtendedOpenAlgoAPI(
        api_key=account.get_api_key(),
        host=account.host_url
    )
    
    positions = client.positionbook()
    return jsonify(positions)
```

### 2. WebSocket API (Server-Sent Events)

#### SSE Endpoint
```python
@api_bp.route('/stream/<int:account_id>')
@login_required
def stream_market_data(account_id):
    """Stream real-time market data"""
    def generate():
        # Subscribe to WebSocket manager events
        queue = Queue()
        websocket_manager.add_listener(queue)
        
        try:
            while True:
                # Get data from queue
                data = queue.get(timeout=30)
                yield f"data: {json.dumps(data)}\n\n"
        except GeneratorExit:
            websocket_manager.remove_listener(queue)
    
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )
```

## Error Handling

### 1. API Error Codes

```python
ERROR_CODES = {
    'AUTH_FAILED': {'code': 401, 'message': 'Authentication failed'},
    'INVALID_API_KEY': {'code': 403, 'message': 'Invalid API key'},
    'RATE_LIMIT': {'code': 429, 'message': 'Rate limit exceeded'},
    'SERVER_ERROR': {'code': 500, 'message': 'Internal server error'},
    'CONNECTION_ERROR': {'code': 503, 'message': 'Service unavailable'}
}
```

### 2. Error Handler Implementation

```python
def handle_api_error(error):
    """Centralized API error handling"""
    error_code = error.get('code', 'UNKNOWN')
    
    if error_code in ERROR_CODES:
        return jsonify({
            'success': False,
            'error': ERROR_CODES[error_code]
        }), ERROR_CODES[error_code]['code']
    
    return jsonify({
        'success': False,
        'error': {'code': 500, 'message': str(error)}
    }), 500
```

### 3. Retry Logic

```python
def retry_with_backoff(func, max_retries=3):
    """Retry API calls with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            
            wait_time = 2 ** attempt
            logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time}s")
            time.sleep(wait_time)
```

## Rate Limiting

### 1. Rate Limit Configuration

```python
# Rate limit tiers
RATE_LIMITS = {
    'global': '1000 per minute',
    'auth': '10 per minute',
    'api': '100 per minute',
    'heavy': '20 per minute',
    'websocket': '50 per minute'
}
```

### 2. Decorator Implementation

```python
from flask_limiter import Limiter

limiter = Limiter(
    app,
    key_func=lambda: get_remote_address(),
    default_limits=["1000 per minute"],
    storage_uri="redis://localhost:6379"  # Production
)

# Custom decorators
def api_rate_limit():
    return limiter.limit("100 per minute")

def heavy_rate_limit():
    return limiter.limit("20 per minute")
```

## Caching Strategy

### 1. Cache Implementation

```python
class APICache:
    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=30)
        self.lock = threading.Lock()
    
    def get_or_fetch(self, key, fetch_func, ttl=30):
        """Get from cache or fetch from API"""
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            
            data = fetch_func()
            self.cache[key] = data
            return data
```

### 2. Cache Usage

```python
# Cache API responses
cache = APICache()

def get_cached_positions(account):
    cache_key = f"positions_{account.id}"
    
    return cache.get_or_fetch(
        key=cache_key,
        fetch_func=lambda: fetch_positions(account),
        ttl=30
    )
```

## Monitoring & Logging

### 1. API Call Logging

```python
def log_api_call(endpoint, params, response, duration):
    """Log API calls for monitoring"""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'endpoint': endpoint,
        'params': params,
        'response_code': response.get('status_code'),
        'duration_ms': duration * 1000,
        'success': response.get('success', False)
    }
    
    logger.info(json.dumps(log_entry))
```

### 2. Metrics Collection

```python
class APIMetrics:
    def __init__(self):
        self.call_count = Counter()
        self.error_count = Counter()
        self.response_time = Histogram()
    
    def record_call(self, endpoint, duration, success):
        self.call_count.inc()
        self.response_time.observe(duration)
        
        if not success:
            self.error_count.inc()
```

## Testing Integration

### 1. Mock API Client

```python
class MockOpenAlgoAPI:
    """Mock client for testing"""
    
    def ping(self):
        return {'status': 'success', 'broker': 'TEST'}
    
    def funds(self):
        return {'available_balance': 100000}
    
    def positionbook(self):
        return [{'symbol': 'NIFTY', 'quantity': 75}]
```

### 2. Integration Tests

```python
def test_account_connection():
    """Test account connection"""
    account = TradingAccount(
        host_url="http://localhost:5000",
        api_key="test_key"
    )
    
    result = test_connection(
        account.host_url,
        account.get_api_key()
    )
    
    assert result['success'] == True
```

## Best Practices

### 1. Security
- Always encrypt API keys at rest
- Use HTTPS for production APIs
- Implement request signing for sensitive operations
- Rate limit all endpoints
- Log all API activity

### 2. Performance
- Cache frequently accessed data
- Use connection pooling
- Batch API requests where possible
- Implement circuit breakers
- Monitor API latency

### 3. Reliability
- Implement retry logic with backoff
- Handle all error cases gracefully
- Maintain connection health checks
- Use failover mechanisms
- Keep audit logs

This comprehensive API integration guide provides all the necessary information to integrate AlgoMirror with OpenAlgo and implement robust trading functionality.