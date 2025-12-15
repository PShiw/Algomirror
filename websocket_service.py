#!/usr/bin/env python3
"""
Standalone WebSocket Service for AlgoMirror
Runs as a separate systemd service to handle real-time data streaming.

This service:
1. Maintains persistent WebSocket connections to OpenAlgo
2. Updates position P&L in the database
3. Triggers stop-loss/take-profit via order_status_poller integration
4. Writes latest prices to a shared file/redis for the main app

Usage:
    python websocket_service.py

Or run via systemd:
    sudo systemctl start algomirror-websocket
"""

import os
import sys
import json
import time
import signal
import logging
import threading
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
import pytz

# Add the app directory to path
app_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(app_dir))

# Set up logging before importing app modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(app_dir, 'logs', 'websocket_service.log'))
    ]
)
logger = logging.getLogger('WebSocketService')

# Import after path setup
import websocket
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(app_dir, '.env'))

# Shared data file path
SHARED_DATA_PATH = os.path.join(app_dir, 'instance', 'websocket_data.json')


class StandaloneWebSocketService:
    """
    Standalone WebSocket service that runs independently of Flask app.
    Shares data via file-based storage for simplicity.
    """

    def __init__(self):
        self.ws = None
        self.ws_url = None
        self.api_key = None
        self.authenticated = False
        self.active = False
        self.subscriptions = set()
        self.latest_prices = {}  # symbol -> {ltp, timestamp}
        self._lock = threading.Lock()
        self._shutdown = False

        # Ensure instance directory exists
        os.makedirs(os.path.dirname(SHARED_DATA_PATH), exist_ok=True)

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Trading hours from database (will be loaded dynamically)
        self.ist = pytz.timezone('Asia/Kolkata')
        self.cached_sessions = []
        self.cached_holidays = {}
        self.cached_special_sessions = {}
        self.cache_refresh_time = None

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self._shutdown = True
        self.stop()

    def refresh_trading_hours_cache(self):
        """Load trading hours from database into cache"""
        try:
            from app import create_app, db
            from app.models import TradingSession, MarketHoliday, SpecialTradingSession
            from sqlalchemy import and_
            from datetime import date

            app = create_app()
            with app.app_context():
                now = datetime.now(self.ist)
                year_start = date(now.year, 1, 1)
                year_end = date(now.year, 12, 31)

                # Cache regular trading sessions
                sessions = TradingSession.query.filter_by(is_active=True).all()
                self.cached_sessions = []
                for session in sessions:
                    self.cached_sessions.append({
                        'day_of_week': session.day_of_week,
                        'start_time': session.start_time,
                        'end_time': session.end_time,
                        'is_active': session.is_active
                    })

                # Cache holidays
                holidays = MarketHoliday.query.filter(
                    and_(
                        MarketHoliday.holiday_date >= year_start,
                        MarketHoliday.holiday_date <= year_end
                    )
                ).all()

                self.cached_holidays = {}
                for holiday in holidays:
                    self.cached_holidays[holiday.holiday_date] = {
                        'holiday_name': holiday.holiday_name,
                        'is_special_session': holiday.is_special_session
                    }

                # Cache special sessions
                special_sessions = SpecialTradingSession.query.filter(
                    and_(
                        SpecialTradingSession.session_date >= year_start,
                        SpecialTradingSession.session_date <= year_end,
                        SpecialTradingSession.is_active == True
                    )
                ).all()

                self.cached_special_sessions = {}
                for session in special_sessions:
                    if session.session_date not in self.cached_special_sessions:
                        self.cached_special_sessions[session.session_date] = []
                    self.cached_special_sessions[session.session_date].append({
                        'session_name': session.session_name,
                        'start_time': session.start_time,
                        'end_time': session.end_time
                    })

                self.cache_refresh_time = datetime.now(self.ist)
                logger.info(f"Trading hours cache refreshed: {len(self.cached_sessions)} sessions, "
                          f"{len(self.cached_holidays)} holidays, "
                          f"{len(self.cached_special_sessions)} special sessions")

        except Exception as e:
            logger.error(f"Failed to refresh trading hours cache: {e}")
            # Use default NSE hours as fallback
            self._set_default_cache()

    def _set_default_cache(self):
        """Set default NSE trading hours if database not available"""
        logger.warning("Using default NSE trading hours (database unavailable)")
        self.cached_sessions = [
            {'day_of_week': i, 'start_time': dt_time(9, 15), 'end_time': dt_time(15, 30), 'is_active': True}
            for i in range(5)  # Monday to Friday
        ]
        self.cached_holidays = {}
        self.cached_special_sessions = {}

    def is_trading_hours(self) -> bool:
        """
        Check if current time is within trading hours based on database settings.
        Includes 15-minute pre-market buffer for WebSocket startup.
        """
        try:
            now = datetime.now(self.ist)
            current_day = now.weekday()  # 0=Monday, 6=Sunday
            current_time = now.time()
            current_date = now.date()

            # Refresh cache if needed (once per day at 5 AM)
            if (self.cache_refresh_time is None or
                (now.hour == 5 and now.minute < 5 and
                 (self.cache_refresh_time.date() != current_date))):
                self.refresh_trading_hours_cache()

            # If no cached sessions, use defaults
            if not self.cached_sessions:
                self._set_default_cache()

            # Check for special trading session first (e.g., Muhurat trading)
            if current_date in self.cached_special_sessions:
                for session in self.cached_special_sessions[current_date]:
                    # Include 15-minute pre-market buffer
                    pre_market = (datetime.combine(current_date, session['start_time']) - timedelta(minutes=15)).time()
                    if pre_market <= current_time <= session['end_time']:
                        logger.debug(f"Special session active: {session['session_name']}")
                        return True

            # Check if it's a holiday (without special session)
            if current_date in self.cached_holidays:
                holiday_info = self.cached_holidays[current_date]
                if not holiday_info.get('is_special_session', False):
                    logger.debug(f"Market holiday: {holiday_info.get('holiday_name', 'Unknown')}")
                    return False

            # Check regular trading sessions for current day
            for session in self.cached_sessions:
                if session['day_of_week'] == current_day and session['is_active']:
                    # Include 15-minute pre-market buffer
                    pre_market = (datetime.combine(current_date, session['start_time']) - timedelta(minutes=15)).time()
                    if pre_market <= current_time <= session['end_time']:
                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking trading hours: {e}")
            return False

    def get_time_until_market_open(self) -> int:
        """
        Calculate seconds until next market open based on database settings.
        Returns seconds to wait before next trading session.
        """
        try:
            now = datetime.now(self.ist)
            current_day = now.weekday()
            current_time = now.time()
            current_date = now.date()

            # Ensure cache is loaded
            if not self.cached_sessions:
                self.refresh_trading_hours_cache()
                if not self.cached_sessions:
                    self._set_default_cache()

            # Get trading days from cached sessions
            trading_days = set(s['day_of_week'] for s in self.cached_sessions if s['is_active'])

            # Find session for current day
            current_session = None
            for session in self.cached_sessions:
                if session['day_of_week'] == current_day and session['is_active']:
                    current_session = session
                    break

            # If it's a trading day and before market open (with 15-min buffer)
            if current_session:
                pre_market = (datetime.combine(current_date, current_session['start_time']) - timedelta(minutes=15)).time()
                if current_time < pre_market:
                    # Check if today is a holiday
                    if current_date not in self.cached_holidays or \
                       self.cached_holidays[current_date].get('is_special_session', False):
                        # Market opens today
                        market_open_today = now.replace(
                            hour=pre_market.hour,
                            minute=pre_market.minute,
                            second=0,
                            microsecond=0
                        )
                        return int((market_open_today - now).total_seconds())

            # Find next trading day
            for i in range(1, 8):
                next_day = (current_day + i) % 7
                next_date = current_date + timedelta(days=i)

                # Skip holidays
                if next_date in self.cached_holidays and \
                   not self.cached_holidays[next_date].get('is_special_session', False):
                    continue

                # Find session for next day
                for session in self.cached_sessions:
                    if session['day_of_week'] == next_day and session['is_active']:
                        pre_market = (datetime.combine(next_date, session['start_time']) - timedelta(minutes=15)).time()
                        next_market_open = datetime.combine(next_date, pre_market)
                        next_market_open = self.ist.localize(next_market_open)
                        return int((next_market_open - now).total_seconds())

            # Fallback: wait 1 hour and check again
            return 3600

        except Exception as e:
            logger.error(f"Error calculating time until market open: {e}")
            return 3600  # Default to 1 hour

    def load_config_from_db(self):
        """Load WebSocket configuration from database"""
        try:
            from app import create_app, db
            from app.models import TradingAccount, StrategyExecution

            app = create_app()
            with app.app_context():
                # Get primary account with WebSocket URL
                primary_account = TradingAccount.query.filter(
                    TradingAccount.is_primary == True
                ).first()

                if not primary_account:
                    # Fallback to first account with WebSocket URL
                    primary_account = TradingAccount.query.filter(
                        TradingAccount.websocket_url.isnot(None),
                        TradingAccount.websocket_url != ''
                    ).first()

                if primary_account:
                    self.ws_url = primary_account.websocket_url
                    self.api_key = primary_account.get_api_key()
                    logger.info(f"Loaded config from account: {primary_account.account_name}")
                    logger.info(f"WebSocket URL: {self.ws_url}")
                    return True
                else:
                    logger.error("No account with WebSocket URL found")
                    return False

        except Exception as e:
            logger.error(f"Failed to load config from DB: {e}")
            return False

    def get_open_positions(self):
        """Get symbols with open positions from database"""
        try:
            from app import create_app, db
            from app.models import StrategyExecution

            app = create_app()
            with app.app_context():
                # Get all entered (open) positions
                open_executions = StrategyExecution.query.filter(
                    StrategyExecution.status == 'entered'
                ).all()

                symbols = []
                for exec in open_executions:
                    if exec.symbol:
                        symbols.append({
                            'symbol': exec.symbol,
                            'exchange': exec.exchange or 'NFO'
                        })

                logger.info(f"Found {len(symbols)} open positions to monitor")
                return symbols

        except Exception as e:
            logger.error(f"Failed to get open positions: {e}")
            return []

    def connect(self):
        """Establish WebSocket connection"""
        if not self.ws_url or not self.api_key:
            logger.error("WebSocket URL or API key not configured")
            return False

        try:
            logger.info(f"Connecting to WebSocket: {self.ws_url}")

            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )

            # Run in background thread
            self.ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            self.ws_thread.start()

            # Wait for connection
            time.sleep(3)

            if self.authenticated:
                self.active = True
                logger.info("WebSocket connected and authenticated")
                return True
            else:
                logger.warning("WebSocket connected but not authenticated")
                return False

        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}")
            return False

    def _on_open(self, ws):
        """WebSocket opened callback"""
        logger.info("WebSocket connection opened")

        # Authenticate
        auth_msg = {
            "action": "authenticate",
            "api_key": self.api_key
        }
        ws.send(json.dumps(auth_msg))

    def _on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(message)

            # Handle authentication response
            if data.get("type") == "auth":
                if data.get("status") == "success":
                    self.authenticated = True
                    logger.info("Authentication successful")

                    # Subscribe to open positions
                    self._subscribe_to_positions()
                else:
                    logger.error(f"Authentication failed: {data}")
                return

            # Handle subscription response
            if data.get("type") == "subscribe":
                logger.debug(f"Subscription response: {data}")
                return

            # Handle market data
            if data.get("type") == "market_data":
                market_data = data.get('data', data)
                symbol = market_data.get('symbol') or data.get('symbol')
                ltp = market_data.get('ltp')

                if symbol and ltp:
                    with self._lock:
                        self.latest_prices[symbol] = {
                            'ltp': ltp,
                            'timestamp': datetime.now().isoformat(),
                            'open': market_data.get('open'),
                            'high': market_data.get('high'),
                            'low': market_data.get('low'),
                            'volume': market_data.get('volume')
                        }

                    # Update shared data file
                    self._save_prices()

                    # Check stop-loss/take-profit triggers
                    self._check_risk_triggers(symbol, ltp)

            elif data.get("ltp") is not None:
                # Direct format
                symbol = data.get('symbol')
                ltp = data.get('ltp')

                if symbol and ltp:
                    with self._lock:
                        self.latest_prices[symbol] = {
                            'ltp': ltp,
                            'timestamp': datetime.now().isoformat()
                        }

                    self._save_prices()
                    self._check_risk_triggers(symbol, ltp)

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {message[:100]}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _on_error(self, ws, error):
        """WebSocket error callback"""
        logger.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code=None, close_msg=None):
        """WebSocket closed callback"""
        logger.warning(f"WebSocket closed - Code: {close_status_code}, Message: {close_msg}")
        self.authenticated = False

        if self.active and not self._shutdown:
            # Attempt reconnection
            logger.info("Scheduling reconnection...")
            threading.Thread(target=self._reconnect, daemon=True).start()

    def _reconnect(self):
        """Reconnect with exponential backoff"""
        delays = [2, 4, 8, 16, 30, 60]

        for i, delay in enumerate(delays):
            if self._shutdown:
                return

            logger.info(f"Reconnection attempt {i+1}/{len(delays)} in {delay} seconds")
            time.sleep(delay)

            if self.connect():
                logger.info("Reconnection successful")
                return

        logger.error("All reconnection attempts failed")

    def _subscribe_to_positions(self):
        """Subscribe to symbols with open positions"""
        symbols = self.get_open_positions()

        if not symbols:
            logger.info("No open positions to subscribe")
            return

        for inst in symbols:
            symbol = inst['symbol']
            exchange = inst['exchange']

            message = {
                'action': 'subscribe',
                'symbol': symbol,
                'exchange': exchange,
                'mode': 2,  # Quote mode for position monitoring
                'depth': 5
            }

            self.ws.send(json.dumps(message))
            self.subscriptions.add(f"{exchange}:{symbol}")
            logger.info(f"Subscribed to {exchange}:{symbol}")

            time.sleep(0.05)  # Small delay between subscriptions

    def _save_prices(self):
        """Save latest prices to shared file"""
        try:
            with self._lock:
                data = {
                    'prices': self.latest_prices,
                    'updated_at': datetime.now().isoformat(),
                    'subscriptions': list(self.subscriptions)
                }

            with open(SHARED_DATA_PATH, 'w') as f:
                json.dump(data, f)

        except Exception as e:
            logger.error(f"Failed to save prices: {e}")

    def _check_risk_triggers(self, symbol, ltp):
        """Check if stop-loss or take-profit should be triggered"""
        try:
            from app import create_app, db
            from app.models import StrategyExecution, Strategy

            app = create_app()
            with app.app_context():
                # Find open positions for this symbol
                open_positions = StrategyExecution.query.filter(
                    StrategyExecution.status == 'entered',
                    StrategyExecution.symbol == symbol
                ).all()

                for position in open_positions:
                    strategy = position.strategy
                    if not strategy:
                        continue

                    entry_price = position.entry_price or 0
                    qty = position.quantity or 0
                    side = position.side  # BUY or SELL

                    # Calculate current P&L
                    if side == 'BUY':
                        pnl = (ltp - entry_price) * qty
                    else:
                        pnl = (entry_price - ltp) * qty

                    # Update position P&L in database
                    position.current_price = ltp
                    position.unrealized_pnl = pnl
                    db.session.commit()

                    # Check stop-loss
                    stop_loss = strategy.stop_loss
                    if stop_loss and pnl <= -abs(stop_loss):
                        logger.warning(f"[STOP-LOSS] Triggered for {symbol}: P&L={pnl}, Stop={stop_loss}")
                        self._trigger_exit(position, 'stop_loss')

                    # Check take-profit
                    take_profit = strategy.take_profit
                    if take_profit and pnl >= abs(take_profit):
                        logger.info(f"[TAKE-PROFIT] Triggered for {symbol}: P&L={pnl}, Target={take_profit}")
                        self._trigger_exit(position, 'take_profit')

        except Exception as e:
            logger.error(f"Error checking risk triggers: {e}")

    def _trigger_exit(self, position, reason):
        """Trigger exit order for position"""
        try:
            from app import create_app, db
            from app.models import RiskEvent
            from app.utils.strategy_executor import StrategyExecutor

            app = create_app()
            with app.app_context():
                # Log risk event
                risk_event = RiskEvent(
                    strategy_id=position.strategy_id,
                    execution_id=position.id,
                    event_type=reason,
                    trigger_value=position.unrealized_pnl,
                    action_taken='exit_triggered',
                    created_at=datetime.utcnow()
                )
                db.session.add(risk_event)
                db.session.commit()

                # Execute exit (this will be handled by the strategy executor)
                logger.info(f"Exit triggered for position {position.id}: {reason}")

                # Mark position for exit (the main app will pick this up)
                position.exit_reason = reason
                position.exit_triggered_at = datetime.utcnow()
                db.session.commit()

        except Exception as e:
            logger.error(f"Error triggering exit: {e}")

    def run(self):
        """Main service loop with trading hours awareness"""
        logger.info("Starting WebSocket Service...")

        # Load trading hours cache first
        self.refresh_trading_hours_cache()

        # Load config from database
        if not self.load_config_from_db():
            logger.error("Failed to load configuration, exiting")
            return

        # Main loop - refresh subscriptions periodically
        refresh_interval = 60  # seconds
        last_refresh = time.time()
        was_trading_hours = False

        while not self._shutdown:
            try:
                # Check if within trading hours
                is_trading = self.is_trading_hours()

                if is_trading:
                    # Within trading hours - connect if not connected
                    if not was_trading_hours:
                        logger.info("Trading hours started - connecting WebSocket...")
                        if not self.connect():
                            logger.error("Failed to connect, will retry in 30 seconds...")
                            time.sleep(30)
                            continue
                        was_trading_hours = True

                    # Refresh subscriptions periodically
                    current_time = time.time()
                    if current_time - last_refresh >= refresh_interval:
                        if self.authenticated:
                            logger.info("Refreshing subscriptions...")
                            self._subscribe_to_positions()
                        last_refresh = current_time

                    time.sleep(1)

                else:
                    # Outside trading hours - disconnect and sleep
                    if was_trading_hours:
                        logger.info("Trading hours ended - disconnecting WebSocket...")
                        self.stop_websocket()
                        was_trading_hours = False

                    # Calculate time until next market open
                    wait_seconds = self.get_time_until_market_open()

                    # Cap at 1 hour to periodically recheck
                    wait_seconds = min(wait_seconds, 3600)

                    now = datetime.now(self.ist)
                    next_check = now + timedelta(seconds=wait_seconds)
                    logger.info(f"Outside trading hours. Sleeping until {next_check.strftime('%Y-%m-%d %H:%M:%S')} IST ({wait_seconds} seconds)")

                    # Sleep in chunks to allow for graceful shutdown
                    sleep_chunk = 60  # Check for shutdown every 60 seconds
                    remaining = wait_seconds
                    while remaining > 0 and not self._shutdown:
                        sleep_time = min(sleep_chunk, remaining)
                        time.sleep(sleep_time)
                        remaining -= sleep_time

            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)

        logger.info("WebSocket Service stopped")

    def stop_websocket(self):
        """Stop WebSocket connection without shutting down service"""
        self.active = False
        self.authenticated = False
        self.subscriptions.clear()
        self.latest_prices.clear()

        if self.ws:
            try:
                self.ws.close()
            except:
                pass
            self.ws = None

        logger.info("WebSocket disconnected (outside trading hours)")

    def stop(self):
        """Stop the service"""
        self.active = False
        self._shutdown = True

        if self.ws:
            try:
                self.ws.close()
            except:
                pass

        logger.info("WebSocket service stopped")


def main():
    """Entry point"""
    service = StandaloneWebSocketService()
    service.run()


if __name__ == '__main__':
    main()
