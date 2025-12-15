#!/usr/bin/env python3
"""
Standalone WebSocket Service for AlgoMirror
Runs as a separate systemd service to handle real-time data streaming.

This service uses the OpenAlgo Python SDK for WebSocket connections:
1. Maintains persistent WebSocket connections to OpenAlgo
2. Updates position P&L in the database
3. Triggers stop-loss/take-profit via order_status_poller integration
4. Writes latest prices to a shared file for the main app

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
from datetime import datetime, time as dt_time, timedelta, date
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
from openalgo import api
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(app_dir, '.env'))

# Shared data file path
SHARED_DATA_PATH = os.path.join(app_dir, 'instance', 'websocket_data.json')


class StandaloneWebSocketService:
    """
    Standalone WebSocket service using OpenAlgo SDK.
    Shares data via file-based storage for simplicity.
    """

    def __init__(self):
        self.client = None
        self.host_url = None
        self.ws_url = None
        self.api_key = None
        self.connected = False
        self.subscriptions = set()
        self.latest_prices = {}  # symbol -> {ltp, timestamp, ...}
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
            from app.models import TradingAccount

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
                    self.host_url = primary_account.host_url
                    self.ws_url = primary_account.websocket_url
                    self.api_key = primary_account.get_api_key()
                    logger.info(f"Loaded config from account: {primary_account.account_name}")
                    logger.info(f"Host URL: {self.host_url}")
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

                instruments = []
                for exec in open_executions:
                    if exec.symbol:
                        instruments.append({
                            'symbol': exec.symbol,
                            'exchange': exec.exchange or 'NFO'
                        })

                logger.info(f"Found {len(instruments)} open positions to monitor")
                return instruments

        except Exception as e:
            logger.error(f"Failed to get open positions: {e}")
            return []

    def connect(self):
        """Establish WebSocket connection using OpenAlgo SDK"""
        if not self.host_url or not self.ws_url or not self.api_key:
            logger.error("Host URL, WebSocket URL, or API key not configured")
            return False

        try:
            logger.info(f"Connecting to OpenAlgo WebSocket: {self.ws_url}")

            # Initialize OpenAlgo client with WebSocket support
            self.client = api(
                api_key=self.api_key,
                host=self.host_url,
                ws_url=self.ws_url
            )

            # Connect to WebSocket
            self.client.connect()
            self.connected = True

            # Wait for connection to stabilize
            time.sleep(2)

            logger.info("OpenAlgo WebSocket connected successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}")
            self.connected = False
            return False

    def on_quote_data(self, data):
        """Handle incoming quote data from OpenAlgo SDK"""
        try:
            # OpenAlgo SDK format:
            # {'type': 'market_data', 'symbol': 'INFY', 'exchange': 'NSE', 'mode': 2,
            #  'data': {'open': 1585.0, 'high': 1606.8, 'low': 1585.0, 'close': 1598.2,
            #           'ltp': 1605.8, 'volume': 1930758, 'timestamp': 1765781412568}}

            symbol = data.get('symbol')
            exchange = data.get('exchange')
            market_data = data.get('data', {})
            ltp = market_data.get('ltp')

            if symbol and ltp:
                key = f"{exchange}:{symbol}"
                with self._lock:
                    self.latest_prices[key] = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'ltp': ltp,
                        'open': market_data.get('open'),
                        'high': market_data.get('high'),
                        'low': market_data.get('low'),
                        'close': market_data.get('close'),
                        'volume': market_data.get('volume'),
                        'timestamp': datetime.now(self.ist).isoformat()
                    }

                # Save to shared file
                self._save_prices()

                # Check stop-loss/take-profit triggers
                self._check_risk_triggers(symbol, exchange, ltp)

        except Exception as e:
            logger.error(f"Error processing quote data: {e}")

    def subscribe_to_positions(self):
        """Subscribe to symbols with open positions using OpenAlgo SDK"""
        instruments = self.get_open_positions()

        if not instruments:
            logger.info("No open positions to subscribe")
            return

        # Unsubscribe from previous subscriptions if any
        if self.subscriptions:
            try:
                old_instruments = [
                    {'exchange': s.split(':')[0], 'symbol': s.split(':')[1]}
                    for s in self.subscriptions
                ]
                self.client.unsubscribe_quote(old_instruments)
                self.subscriptions.clear()
            except Exception as e:
                logger.warning(f"Error unsubscribing old instruments: {e}")

        # Subscribe to new instruments using quote mode (for OHLCV data)
        try:
            self.client.subscribe_quote(instruments, on_data_received=self.on_quote_data)

            for inst in instruments:
                key = f"{inst['exchange']}:{inst['symbol']}"
                self.subscriptions.add(key)
                logger.info(f"Subscribed to {key}")

        except Exception as e:
            logger.error(f"Error subscribing to instruments: {e}")

    def _save_prices(self):
        """Save latest prices to shared file"""
        try:
            with self._lock:
                data = {
                    'prices': self.latest_prices,
                    'updated_at': datetime.now(self.ist).isoformat(),
                    'subscriptions': list(self.subscriptions)
                }

            with open(SHARED_DATA_PATH, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save prices: {e}")

    def _check_risk_triggers(self, symbol, exchange, ltp):
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
        logger.info("Starting WebSocket Service (OpenAlgo SDK)...")

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

                        # Subscribe to positions after connection
                        self.subscribe_to_positions()
                        was_trading_hours = True

                    # Refresh subscriptions periodically
                    current_time = time.time()
                    if current_time - last_refresh >= refresh_interval:
                        if self.connected:
                            logger.info("Refreshing subscriptions...")
                            self.subscribe_to_positions()
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
        self.connected = False
        self.subscriptions.clear()
        self.latest_prices.clear()

        if self.client:
            try:
                self.client.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting client: {e}")
            self.client = None

        logger.info("WebSocket disconnected (outside trading hours)")

    def stop(self):
        """Stop the service"""
        self._shutdown = True
        self.stop_websocket()
        logger.info("WebSocket service stopped")


def main():
    """Entry point"""
    service = StandaloneWebSocketService()
    service.run()


if __name__ == '__main__':
    main()
