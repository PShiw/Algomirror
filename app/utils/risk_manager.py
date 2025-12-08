"""
Risk Manager Service
Monitors and enforces risk thresholds for strategies.

Key Features:
- Max Loss monitoring with auto-exit
- Max Profit monitoring with auto-exit
- Trailing Stop Loss implementation
- Real-time P&L calculations using WebSocket data
- Audit logging of all risk events

Uses standard threading for background tasks
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from decimal import Decimal

from app import db
from app.models import (
    Strategy, StrategyExecution, StrategyLeg, RiskEvent,
    TradingAccount
)
from app.utils.openalgo_client import ExtendedOpenAlgoAPI

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Singleton service to monitor and enforce risk thresholds.

    Risk Types:
    - Max Loss: Closes all positions when total loss exceeds threshold
    - Max Profit: Closes all positions when total profit exceeds threshold
    - Trailing SL: Dynamically adjusts stop loss as price moves favorably

    Calculates P&L using real-time LTP from PositionMonitor.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern - only one instance"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the risk manager"""
        if self._initialized:
            return

        self._initialized = True
        self.is_running = False
        self.monitored_strategies: Dict[int, Strategy] = {}

        logger.info("RiskManager initialized")

    def calculate_execution_pnl(self, execution: StrategyExecution) -> Tuple[float, float]:
        """
        Calculate P&L for a single strategy execution.

        Args:
            execution: Strategy execution to calculate P&L for

        Returns:
            Tuple of (realized_pnl, unrealized_pnl)
        """
        realized_pnl = 0.0
        unrealized_pnl = 0.0

        try:
            # Get entry and exit prices
            entry_price = float(execution.entry_price or 0)
            exit_price = float(execution.exit_price or 0)
            quantity = int(execution.quantity or 0)

            if quantity == 0:
                return (0.0, 0.0)

            # Determine if long or short from leg action
            is_long = execution.leg and execution.leg.action.upper() == 'BUY'

            # Calculate realized P&L (if position is closed)
            if execution.status == 'exited' and exit_price > 0:
                if is_long:
                    realized_pnl = (exit_price - entry_price) * quantity
                else:
                    realized_pnl = (entry_price - exit_price) * quantity

                return (realized_pnl, 0.0)

            # Calculate unrealized P&L (if position is open)
            if execution.status == 'entered':
                # Use real-time LTP from WebSocket if available
                current_price = float(execution.last_price or entry_price)

                if current_price > 0:
                    if is_long:
                        unrealized_pnl = (current_price - entry_price) * quantity
                    else:
                        unrealized_pnl = (entry_price - current_price) * quantity

                return (0.0, unrealized_pnl)

        except Exception as e:
            logger.error(f"Error calculating P&L for execution {execution.id}: {e}")

        return (realized_pnl, unrealized_pnl)

    def calculate_strategy_pnl(self, strategy: Strategy) -> Dict:
        """
        Calculate total P&L for a strategy across all executions.

        Args:
            strategy: Strategy to calculate P&L for

        Returns:
            Dict with realized_pnl, unrealized_pnl, total_pnl
        """
        total_realized = 0.0
        total_unrealized = 0.0

        try:
            # Get all executions for this strategy
            executions = StrategyExecution.query.filter_by(
                strategy_id=strategy.id
            ).all()

            for execution in executions:
                realized, unrealized = self.calculate_execution_pnl(execution)
                total_realized += realized
                total_unrealized += unrealized

            total_pnl = total_realized + total_unrealized

            return {
                'realized_pnl': round(total_realized, 2),
                'unrealized_pnl': round(total_unrealized, 2),
                'total_pnl': round(total_pnl, 2)
            }

        except Exception as e:
            logger.error(f"Error calculating strategy P&L for {strategy.name}: {e}")
            return {
                'realized_pnl': 0.0,
                'unrealized_pnl': 0.0,
                'total_pnl': 0.0
            }

    def check_max_loss(self, strategy: Strategy) -> Optional[RiskEvent]:
        """
        Check if strategy has breached max loss threshold.

        Args:
            strategy: Strategy to check

        Returns:
            RiskEvent if threshold breached, None otherwise
        """
        # Check if max loss monitoring is enabled
        if not strategy.max_loss or strategy.max_loss <= 0:
            return None

        if not strategy.auto_exit_on_max_loss:
            return None

        # Calculate current P&L
        pnl_data = self.calculate_strategy_pnl(strategy)
        current_pnl = pnl_data['total_pnl']

        # Check if loss exceeds threshold (loss is negative)
        max_loss_threshold = -abs(float(strategy.max_loss))

        if current_pnl <= max_loss_threshold:
            logger.warning(
                f"Max Loss breached for {strategy.name}: "
                f"P&L={current_pnl} <= Threshold={max_loss_threshold}"
            )

            # Create risk event
            risk_event = RiskEvent(
                strategy_id=strategy.id,
                event_type='max_loss',
                threshold_value=max_loss_threshold,
                current_value=current_pnl,
                action_taken='close_all' if strategy.auto_exit_on_max_loss else 'alert_only',
                notes=f"Max Loss breached: P&L {current_pnl} exceeded threshold {max_loss_threshold}"
            )

            return risk_event

        return None

    def check_max_profit(self, strategy: Strategy) -> Optional[RiskEvent]:
        """
        Check if strategy has breached max profit threshold.

        Args:
            strategy: Strategy to check

        Returns:
            RiskEvent if threshold breached, None otherwise
        """
        # Check if max profit monitoring is enabled
        if not strategy.max_profit or strategy.max_profit <= 0:
            return None

        if not strategy.auto_exit_on_max_profit:
            return None

        # Calculate current P&L
        pnl_data = self.calculate_strategy_pnl(strategy)
        current_pnl = pnl_data['total_pnl']

        # Check if profit exceeds threshold (profit is positive)
        max_profit_threshold = abs(float(strategy.max_profit))

        if current_pnl >= max_profit_threshold:
            logger.info(
                f"Max Profit reached for {strategy.name}: "
                f"P&L={current_pnl} >= Threshold={max_profit_threshold}"
            )

            # Create risk event
            risk_event = RiskEvent(
                strategy_id=strategy.id,
                event_type='max_profit',
                threshold_value=max_profit_threshold,
                current_value=current_pnl,
                action_taken='close_all' if strategy.auto_exit_on_max_profit else 'alert_only',
                notes=f"Max Profit reached: P&L {current_pnl} exceeded threshold {max_profit_threshold}"
            )

            return risk_event

        return None

    def check_trailing_sl(self, strategy: Strategy) -> Optional[RiskEvent]:
        """
        Check if trailing stop loss should be triggered.

        Trailing SL Types:
        - percentage: Trail by X% of favorable movement
        - points: Trail by X points of favorable movement
        - amount: Trail by X rupees of favorable movement

        Args:
            strategy: Strategy to check

        Returns:
            RiskEvent if trailing SL triggered, None otherwise
        """
        # Check if trailing SL is enabled
        if not strategy.trailing_sl or strategy.trailing_sl <= 0:
            return None

        # Calculate current P&L
        pnl_data = self.calculate_strategy_pnl(strategy)
        current_pnl = pnl_data['total_pnl']

        # Get trailing SL type
        trailing_type = strategy.trailing_sl_type or 'percentage'
        trailing_value = float(strategy.trailing_sl)

        try:
            # Get all open executions
            open_executions = StrategyExecution.query.filter_by(
                strategy_id=strategy.id,
                status='entered'
            ).all()

            if not open_executions:
                return None

            # Check each execution for trailing SL trigger
            for execution in open_executions:
                # Skip if no real-time price available
                if not execution.last_price or execution.last_price <= 0:
                    continue

                entry_price = float(execution.entry_price or 0)
                current_price = float(execution.last_price)
                # Get action from leg (transaction_type doesn't exist on StrategyExecution)
                is_long = execution.leg and execution.leg.action.upper() == 'BUY'

                # Calculate trigger price based on type
                trigger_price = None

                if trailing_type == 'percentage':
                    # Trail by percentage
                    if is_long:
                        # For long: trigger = entry + (current - entry) * (1 - trailing_pct/100)
                        if current_price > entry_price:
                            trigger_price = entry_price + (current_price - entry_price) * (1 - trailing_value / 100)
                    else:
                        # For short: trigger = entry - (entry - current) * (1 - trailing_pct/100)
                        if current_price < entry_price:
                            trigger_price = entry_price - (entry_price - current_price) * (1 - trailing_value / 100)

                elif trailing_type == 'points':
                    # Trail by points
                    if is_long:
                        if current_price > entry_price:
                            trigger_price = current_price - trailing_value
                    else:
                        if current_price < entry_price:
                            trigger_price = current_price + trailing_value

                elif trailing_type == 'amount':
                    # Trail by amount (rupees)
                    quantity = int(execution.quantity or 1)
                    points = trailing_value / quantity  # Convert amount to points

                    if is_long:
                        if current_price > entry_price:
                            trigger_price = current_price - points
                    else:
                        if current_price < entry_price:
                            trigger_price = current_price + points

                # Check if current price has hit trailing SL
                if trigger_price:
                    # Update highest trigger price seen
                    if not execution.trailing_sl_triggered or current_price > execution.trailing_sl_triggered:
                        execution.trailing_sl_triggered = trigger_price
                        db.session.commit()

                    # Check if price has reversed and hit the trailing SL
                    should_trigger = False
                    if is_long and current_price <= trigger_price:
                        should_trigger = True
                    elif not is_long and current_price >= trigger_price:
                        should_trigger = True

                    if should_trigger:
                        logger.warning(
                            f"Trailing SL triggered for {strategy.name} - {execution.symbol}: "
                            f"Price={current_price}, Trigger={trigger_price}"
                        )

                        # Create risk event
                        risk_event = RiskEvent(
                            strategy_id=strategy.id,
                            execution_id=execution.id,
                            event_type='trailing_sl',
                            threshold_value=trigger_price,
                            current_value=current_price,
                            action_taken='close_all',
                            notes=f"Trailing SL triggered: Price {current_price} hit trigger {trigger_price}"
                        )

                        return risk_event

        except Exception as e:
            logger.error(f"Error checking trailing SL for {strategy.name}: {e}")

        return None

    def close_strategy_positions(self, strategy: Strategy, risk_event: RiskEvent) -> bool:
        """
        Close all open positions for a strategy.

        Args:
            strategy: Strategy to close
            risk_event: Risk event that triggered the closure

        Returns:
            bool: True if all positions closed successfully
        """
        try:
            # Get all open executions
            open_executions = StrategyExecution.query.filter_by(
                strategy_id=strategy.id,
                status='entered'
            ).all()

            if not open_executions:
                logger.info(f"No open positions to close for {strategy.name}")
                return True

            exit_order_ids = []

            # Get primary account for order placement
            primary_account = TradingAccount.query.filter_by(
                user_id=strategy.user_id,
                is_primary=True,
                is_active=True
            ).first()

            if not primary_account:
                logger.error(f"No primary account found for user {strategy.user_id}")
                return False

            # Initialize OpenAlgo client
            client = ExtendedOpenAlgoAPI(
                api_key=primary_account.get_api_key(),
                host=primary_account.host_url
            )

            # Close each position with freeze-aware placement and retry logic
            from app.utils.freeze_quantity_handler import place_order_with_freeze_check

            for execution in open_executions:
                try:
                    # Reverse transaction type for exit (get action from leg)
                    leg_action = execution.leg.action.upper() if execution.leg else 'BUY'
                    exit_transaction = 'SELL' if leg_action == 'BUY' else 'BUY'

                    # Place exit order with freeze-aware placement and retry logic
                    max_retries = 3
                    retry_delay = 1
                    response = None

                    for attempt in range(max_retries):
                        try:
                            response = place_order_with_freeze_check(
                                client=client,
                                user_id=strategy.user_id,
                                strategy=strategy.name,
                                symbol=execution.symbol,
                                exchange=execution.exchange,
                                action=exit_transaction,
                                quantity=execution.quantity,
                                price_type='MARKET',
                                product=execution.product or 'MIS'
                            )
                            if response and isinstance(response, dict):
                                break
                        except Exception as api_error:
                            logger.warning(f"[RETRY] Risk exit attempt {attempt + 1}/{max_retries} failed: {api_error}")
                            if attempt < max_retries - 1:
                                import time
                                time.sleep(retry_delay)
                                retry_delay *= 2
                            else:
                                response = {'status': 'error', 'message': f'API error after {max_retries} retries'}

                    if response and response.get('status') == 'success':
                        order_id = response.get('orderid')
                        exit_order_ids.append(order_id)

                        logger.info(
                            f"Exit order placed for {execution.symbol}: "
                            f"Order ID {order_id}"
                        )

                        # Update execution status
                        execution.status = 'exit_pending'
                        execution.exit_order_id = order_id

                    else:
                        logger.error(
                            f"Failed to place exit order for {execution.symbol}: "
                            f"{response.get('message') if response else 'No response'}"
                        )

                except Exception as e:
                    logger.error(f"Error placing exit order for {execution.symbol}: {e}")

            # Update risk event with order IDs
            risk_event.exit_order_ids = exit_order_ids
            db.session.add(risk_event)
            db.session.commit()

            logger.info(
                f"Risk exit completed for {strategy.name}: "
                f"{len(exit_order_ids)} orders placed"
            )

            return len(exit_order_ids) > 0

        except Exception as e:
            logger.error(f"Error closing strategy positions: {e}")
            db.session.rollback()
            return False

    def check_strategy(self, strategy: Strategy):
        """
        Check all risk thresholds for a strategy.

        Args:
            strategy: Strategy to check
        """
        try:
            # Check if risk monitoring is enabled
            if not strategy.risk_monitoring_enabled:
                return

            # Check max loss
            risk_event = self.check_max_loss(strategy)
            if risk_event:
                db.session.add(risk_event)
                db.session.commit()

                # Close positions if auto-exit enabled
                if strategy.auto_exit_on_max_loss:
                    self.close_strategy_positions(strategy, risk_event)

            # Check max profit
            risk_event = self.check_max_profit(strategy)
            if risk_event:
                db.session.add(risk_event)
                db.session.commit()

                # Close positions if auto-exit enabled
                if strategy.auto_exit_on_max_profit:
                    self.close_strategy_positions(strategy, risk_event)

            # Check trailing SL
            risk_event = self.check_trailing_sl(strategy)
            if risk_event:
                db.session.add(risk_event)
                db.session.commit()

                # Trailing SL always triggers exit
                self.close_strategy_positions(strategy, risk_event)

        except Exception as e:
            logger.error(f"Error checking strategy {strategy.name}: {e}")

    def run_risk_checks(self):
        """
        Run risk checks for all monitored strategies.
        Called by background scheduler.
        """
        if not self.is_running:
            return

        try:
            # Get all active strategies with risk monitoring enabled
            strategies = Strategy.query.filter_by(
                is_active=True,
                risk_monitoring_enabled=True
            ).all()

            for strategy in strategies:
                # Only check strategies with open positions
                has_open = StrategyExecution.query.filter_by(
                    strategy_id=strategy.id,
                    status='entered'
                ).first()

                if has_open:
                    self.check_strategy(strategy)

        except Exception as e:
            logger.error(f"Error running risk checks: {e}")

    def start(self):
        """Start risk monitoring"""
        if self.is_running:
            logger.warning("Risk manager already running")
            return

        self.is_running = True
        logger.info("Risk monitoring started")

    def stop(self):
        """Stop risk monitoring"""
        if not self.is_running:
            return

        self.is_running = False
        self.monitored_strategies.clear()
        logger.info("Risk monitoring stopped")

    def get_monitoring_status(self) -> Dict:
        """
        Get current monitoring status for admin dashboard.

        Returns:
            Dict with monitoring statistics
        """
        try:
            # Count strategies with risk monitoring enabled
            total_strategies = Strategy.query.filter_by(
                is_active=True,
                risk_monitoring_enabled=True
            ).count()

            # Count strategies with open positions
            strategies_with_positions = db.session.query(Strategy.id).join(
                StrategyExecution
            ).filter(
                Strategy.is_active == True,
                Strategy.risk_monitoring_enabled == True,
                StrategyExecution.status == 'entered'
            ).distinct().count()

            # Get recent risk events (last 24 hours)
            from datetime import timedelta
            yesterday = datetime.utcnow() - timedelta(days=1)
            recent_events = RiskEvent.query.filter(
                RiskEvent.triggered_at >= yesterday
            ).count()

            return {
                'is_running': self.is_running,
                'total_strategies': total_strategies,
                'active_strategies': strategies_with_positions,
                'recent_events_24h': recent_events
            }

        except Exception as e:
            logger.error(f"Error getting monitoring status: {e}")
            return {
                'is_running': self.is_running,
                'total_strategies': 0,
                'active_strategies': 0,
                'recent_events_24h': 0
            }


# Global instance
risk_manager = RiskManager()
