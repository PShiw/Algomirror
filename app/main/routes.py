from flask import render_template, redirect, url_for, current_app
from flask_login import login_required, current_user
from app.main import main_bp
from app.models import TradingAccount, ActivityLog, User
from openalgo import api
from datetime import datetime
from sqlalchemy import desc

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # Check if registration is available (single-user app - only if no users exist)
    registration_available = (User.query.count() == 0)

    return render_template('main/index.html', registration_available=registration_available)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Strategy dashboard showing active strategies and account status (migrated from /strategy)"""
    from app.models import Strategy, StrategyExecution
    from datetime import datetime, timedelta

    # Get user's strategies
    strategies = Strategy.query.filter_by(user_id=current_user.id).order_by(Strategy.created_at.desc()).all()

    # Get user's active accounts
    accounts = TradingAccount.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).all()

    # If no accounts, redirect to add account page
    if not accounts:
        return redirect(url_for('accounts.add'))

    # Calculate today's P&L across all strategies
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_executions = StrategyExecution.query.join(Strategy).filter(
        Strategy.user_id == current_user.id,
        StrategyExecution.created_at >= today_start
    ).all()

    # Calculate P&L only from successful executions (exclude rejected/failed)
    today_pnl = sum(
        e.realized_pnl or 0
        for e in today_executions
        if e.realized_pnl and e.status != 'failed'
        and not (hasattr(e, 'broker_order_status') and e.broker_order_status in ['rejected', 'cancelled'])
    )

    # Get active strategy count
    active_strategies = [s for s in strategies if s.is_active]

    # Convert strategies to dictionaries for JSON serialization
    strategies_data = []
    for strategy in strategies:
        strategies_data.append({
            'id': strategy.id,
            'name': strategy.name,
            'description': strategy.description,
            'market_condition': strategy.market_condition,
            'risk_profile': strategy.risk_profile,
            'is_active': strategy.is_active,
            'created_at': strategy.created_at.isoformat() if strategy.created_at else None,
            'updated_at': strategy.updated_at.isoformat() if strategy.updated_at else None,
            'selected_accounts': strategy.selected_accounts or [],
            'allocation_type': strategy.allocation_type,
            'max_loss': strategy.max_loss,
            'max_profit': strategy.max_profit,
            'trailing_sl': strategy.trailing_sl,
            # Per-strategy P&L calculation using new properties
            'total_pnl': strategy.total_pnl,
            'realized_pnl': strategy.realized_pnl,
            'unrealized_pnl': strategy.unrealized_pnl
        })

    # Convert accounts to dictionaries for JSON serialization
    accounts_data = []
    for account in accounts:
        accounts_data.append({
            'id': account.id,
            'account_name': account.account_name,
            'broker_name': account.broker_name,
            'is_primary': account.is_primary,
            'connection_status': account.connection_status
        })

    current_app.logger.info(
        f'Dashboard accessed by user {current_user.username}',
        extra={
            'event': 'dashboard_access',
            'user_id': current_user.id,
            'accounts_count': len(accounts),
            'strategies_count': len(strategies)
        }
    )

    return render_template('main/dashboard.html',
                         strategies=strategies,
                         strategies_json=strategies_data,
                         accounts=accounts,
                         accounts_json=accounts_data,
                         today_pnl=today_pnl,
                         active_strategies=len(active_strategies))