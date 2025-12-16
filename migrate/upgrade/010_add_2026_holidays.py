"""
Migration: Add 2026 NSE market holidays

Adds 15 NSE holidays for the year 2026.
"""

from sqlalchemy import text
from datetime import date


def upgrade(db):
    """Add 2026 NSE holidays to market_holiday table"""

    holidays_2026 = [
        (date(2026, 1, 26), 'Republic Day', 'NSE', 'trading'),
        (date(2026, 3, 3), 'Holi', 'NSE', 'trading'),
        (date(2026, 3, 26), 'Shri Ram Navami', 'NSE', 'trading'),
        (date(2026, 3, 31), 'Shri Mahavir Jayanti', 'NSE', 'trading'),
        (date(2026, 4, 3), 'Good Friday', 'NSE', 'trading'),
        (date(2026, 4, 14), 'Dr. Baba Saheb Ambedkar Jayanti', 'NSE', 'trading'),
        (date(2026, 5, 1), 'Maharashtra Day', 'NSE', 'trading'),
        (date(2026, 5, 28), 'Bakri Eid', 'NSE', 'trading'),
        (date(2026, 6, 26), 'Moharram', 'NSE', 'trading'),
        (date(2026, 9, 14), 'Ganesh Chaturthi', 'NSE', 'trading'),
        (date(2026, 10, 2), 'Mahatma Gandhi Jayanti', 'NSE', 'trading'),
        (date(2026, 10, 20), 'Dussehra', 'NSE', 'trading'),
        (date(2026, 11, 10), 'Diwali - Balipratipada', 'NSE', 'trading'),
        (date(2026, 11, 24), 'Prakash Gurpurb Sri Guru Nanak Dev', 'NSE', 'trading'),
        (date(2026, 12, 25), 'Christmas', 'NSE', 'trading'),
    ]

    added_count = 0
    for holiday_date, holiday_name, market, holiday_type in holidays_2026:
        # Check if holiday already exists
        result = db.session.execute(
            text("SELECT id FROM market_holidays WHERE holiday_date = :hdate AND market = :market"),
            {"hdate": holiday_date.isoformat(), "market": market}
        )
        if result.fetchone() is None:
            db.session.execute(
                text("""
                    INSERT INTO market_holidays (holiday_date, holiday_name, market, holiday_type)
                    VALUES (:hdate, :hname, :market, :htype)
                """),
                {"hdate": holiday_date.isoformat(), "hname": holiday_name, "market": market, "htype": holiday_type}
            )
            added_count += 1

    db.session.commit()
    print(f"Added {added_count} holidays for 2026")


def downgrade(db):
    """Remove 2026 holidays"""
    db.session.execute(
        text("DELETE FROM market_holidays WHERE holiday_date >= '2026-01-01' AND holiday_date <= '2026-12-31'")
    )
    db.session.commit()
    print("Removed 2026 holidays")
