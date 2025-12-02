"""
Supertrend Indicator Module
Uses TA-Lib ATR with Pine Script logic for TradingView compatibility

Direction convention (matching Pine Script/TradingView):
    - direction = -1: Bullish (Up direction, green) - price above supertrend (lower band)
    - direction = 1: Bearish (Down direction, red) - price below supertrend (upper band)
"""
import numpy as np
import pandas as pd
import talib
import logging

logger = logging.getLogger(__name__)


def calculate_supertrend(high, low, close, period=7, multiplier=3):
    """
    Calculate Supertrend indicator matching TradingView Pine Script

    Args:
        high: High price array (numpy array or pandas Series)
        low: Low price array (numpy array or pandas Series)
        close: Close price array (numpy array or pandas Series)
        period: ATR period (default: 7)
        multiplier: ATR multiplier/factor (default: 3)

    Returns:
        Tuple of (trend, direction, long, short)
        - trend: Supertrend line values
        - direction: -1 for bullish (green/up), 1 for bearish (red/down)
        - long: Long (support) line - visible when bullish
        - short: Short (resistance) line - visible when bearish
    """
    try:
        # Convert to numpy arrays if needed
        if hasattr(high, 'values'):
            high = high.values.astype(np.float64)
        else:
            high = np.asarray(high, dtype=np.float64)

        if hasattr(low, 'values'):
            low = low.values.astype(np.float64)
        else:
            low = np.asarray(low, dtype=np.float64)

        if hasattr(close, 'values'):
            close = close.values.astype(np.float64)
        else:
            close = np.asarray(close, dtype=np.float64)

        n = len(close)

        # Calculate ATR using TA-Lib (Wilder's smoothing)
        atr = talib.ATR(high, low, close, period)

        # Calculate basic bands (src = hl2 in Pine Script)
        hl_avg = (high + low) / 2.0
        upper_band = hl_avg + multiplier * atr
        lower_band = hl_avg - multiplier * atr

        # Initialize arrays
        final_upper = np.full(n, np.nan)
        final_lower = np.full(n, np.nan)
        supertrend = np.full(n, np.nan)
        direction = np.full(n, np.nan)
        long_line = np.full(n, np.nan)
        short_line = np.full(n, np.nan)

        # Find first valid ATR index
        first_valid = -1
        for i in range(n):
            if not np.isnan(atr[i]):
                first_valid = i
                break

        if first_valid < 0 or first_valid >= n:
            return supertrend, direction, long_line, short_line

        # Initialize first valid values
        # Pine Script: if na(atr[1]) _direction := 1 (first bar is downtrend)
        final_upper[first_valid] = upper_band[first_valid]
        final_lower[first_valid] = lower_band[first_valid]
        direction[first_valid] = 1.0  # downtrend (red in Pine Script)
        supertrend[first_valid] = final_upper[first_valid]
        short_line[first_valid] = final_upper[first_valid]

        # Pine Script logic for subsequent bars
        for i in range(first_valid + 1, n):
            # Final lower band: lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
            if lower_band[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
                final_lower[i] = lower_band[i]
            else:
                final_lower[i] = final_lower[i-1]

            # Final upper band: upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
            if upper_band[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
                final_upper[i] = upper_band[i]
            else:
                final_upper[i] = final_upper[i-1]

            # Direction logic (Pine Script)
            # if prevSuperTrend == prevUpperBand
            #     _direction := close > upperBand ? -1 : 1
            # else
            #     _direction := close < lowerBand ? 1 : -1
            if supertrend[i-1] == final_upper[i-1]:
                # Previous was upper band (downtrend)
                if close[i] > final_upper[i]:
                    direction[i] = -1.0  # Change to uptrend (green)
                else:
                    direction[i] = 1.0   # Continue downtrend (red)
            else:
                # Previous was lower band (uptrend)
                if close[i] < final_lower[i]:
                    direction[i] = 1.0   # Change to downtrend (red)
                else:
                    direction[i] = -1.0  # Continue uptrend (green)

            # Supertrend assignment: _direction == -1 ? lowerBand : upperBand
            if direction[i] == -1.0:  # uptrend (green)
                supertrend[i] = final_lower[i]
                long_line[i] = final_lower[i]
            else:  # downtrend (red)
                supertrend[i] = final_upper[i]
                short_line[i] = final_upper[i]

        logger.debug(f"Supertrend calculated: period={period}, multiplier={multiplier}")

        return supertrend, direction, long_line, short_line

    except Exception as e:
        logger.error(f"Error calculating Supertrend: {e}", exc_info=True)
        nan_array = np.full(len(close), np.nan)
        return nan_array, nan_array, nan_array, nan_array


def get_supertrend_signal(direction):
    """
    Get current Supertrend signal

    Direction convention (matching Pine Script):
        -1 = Bullish (Up direction, green) -> BUY signal
         1 = Bearish (Down direction, red) -> SELL signal

    Args:
        direction: Direction array from calculate_supertrend

    Returns:
        String: 'BUY', 'SELL', or 'NEUTRAL'
    """
    if len(direction) == 0:
        return 'NEUTRAL'

    current_dir = direction[-1]

    if np.isnan(current_dir):
        return 'NEUTRAL'
    elif current_dir == -1:  # Bullish (Pine: direction < 0)
        return 'BUY'
    else:  # Bearish (Pine: direction > 0, i.e., direction == 1)
        return 'SELL'


def calculate_spread_supertrend(leg_prices_dict, high_col='high', low_col='low', close_col='close',
                                period=7, multiplier=3):
    """
    Calculate Supertrend for a combined spread of multiple legs

    Args:
        leg_prices_dict: Dict of {leg_name: DataFrame} with OHLC data
        high_col: Column name for high price
        low_col: Column name for low price
        close_col: Column name for close price
        period: ATR period
        multiplier: ATR multiplier

    Returns:
        Dict with spread OHLC and Supertrend data
    """
    try:
        if not leg_prices_dict:
            logger.error("No leg prices provided")
            return None

        # Calculate combined spread
        combined_high = None
        combined_low = None
        combined_close = None

        for leg_name, df in leg_prices_dict.items():
            if combined_close is None:
                combined_high = df[high_col].copy()
                combined_low = df[low_col].copy()
                combined_close = df[close_col].copy()
            else:
                combined_high += df[high_col]
                combined_low += df[low_col]
                combined_close += df[close_col]

        # Calculate Supertrend on combined spread
        trend, direction, long_line, short_line = calculate_supertrend(
            combined_high.values,
            combined_low.values,
            combined_close.values,
            period=period,
            multiplier=multiplier
        )

        return {
            'high': combined_high,
            'low': combined_low,
            'close': combined_close,
            'supertrend': trend,
            'direction': direction,
            'long': long_line,
            'short': short_line,
            'signal': get_supertrend_signal(direction)
        }

    except Exception as e:
        logger.error(f"Error calculating spread Supertrend: {e}", exc_info=True)
        return None
