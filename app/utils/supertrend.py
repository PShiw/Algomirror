"""
Supertrend Indicator Module
Calculates Supertrend matching Pine Script v6 implementation exactly

Pine Script Reference:
    pine_supertrend(factor, atrPeriod) =>
        src = hl2
        atr = ta.atr(atrPeriod)
        upperBand = src + factor * atr
        lowerBand = src - factor * atr
        prevLowerBand = nz(lowerBand[1])
        prevUpperBand = nz(upperBand[1])

        lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
        upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand

        int _direction = na
        float superTrend = na
        prevSuperTrend = superTrend[1]
        if na(atr[1])
            _direction := 1
        else if prevSuperTrend == prevUpperBand
            _direction := close > upperBand ? -1 : 1
        else
            _direction := close < lowerBand ? 1 : -1
        superTrend := _direction == -1 ? lowerBand : upperBand
        [superTrend, _direction]

Direction convention (matching Pine Script):
    - direction = -1: Bullish (Up direction, green) - price above supertrend (lower band)
    - direction = 1: Bearish (Down direction, red) - price below supertrend (upper band)
"""
import numpy as np
from numba import njit
import talib
import logging

logger = logging.getLogger(__name__)


def get_basic_bands(hl2_price, atr, multiplier):
    """
    Calculate basic upper and lower bands

    Args:
        hl2_price: HL2 price array (high + low) / 2
        atr: Average True Range array
        multiplier: ATR multiplier (factor)

    Returns:
        Tuple of (upper_band, lower_band)
    """
    matr = multiplier * atr
    upper = hl2_price + matr
    lower = hl2_price - matr
    return upper, lower


@njit
def get_final_bands_nb(close, upper, lower):
    """
    Calculate final Supertrend bands and direction - MATCHING PINE SCRIPT EXACTLY

    Pine Script logic:
        lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
        upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand

        if na(atr[1])
            _direction := 1
        else if prevSuperTrend == prevUpperBand
            _direction := close > upperBand ? -1 : 1
        else
            _direction := close < lowerBand ? 1 : -1
        superTrend := _direction == -1 ? lowerBand : upperBand

    Direction convention:
        -1 = Bullish (Up direction, green line = lower band)
         1 = Bearish (Down direction, red line = upper band)

    Args:
        close: Close price array
        upper: Upper band array (will be modified in place)
        lower: Lower band array (will be modified in place)

    Returns:
        Tuple of (trend, direction, long, short)
    """
    n = close.shape[0]
    trend = np.full(n, np.nan)
    dir_ = np.full(n, 1, dtype=np.int32)  # Start with bearish (1)
    long = np.full(n, np.nan)   # Bullish line (lower band when direction = -1)
    short = np.full(n, np.nan)  # Bearish line (upper band when direction = 1)

    # Find first valid index (where bands are not NaN)
    first_valid = -1
    for i in range(n):
        if not np.isnan(upper[i]) and not np.isnan(lower[i]):
            first_valid = i
            break

    if first_valid < 0:
        return trend, dir_, long, short

    # Initialize first valid bar - Pine Script: if na(atr[1]) then direction = 1
    # First bar starts as bearish (direction = 1), supertrend = upper band
    dir_[first_valid] = 1
    trend[first_valid] = upper[first_valid]
    short[first_valid] = upper[first_valid]

    # Process remaining bars
    for i in range(first_valid + 1, n):
        # Skip if current bar has NaN bands
        if np.isnan(upper[i]) or np.isnan(lower[i]):
            continue

        # Check if previous bar had valid bands
        prev_upper_valid = not np.isnan(upper[i - 1])
        prev_lower_valid = not np.isnan(lower[i - 1])

        # Step 1: Adjust bands FIRST (before direction check) - matching Pine Script
        # Pine uses nz() which returns 0 for NA, but we handle differently:
        # Only adjust if previous value was valid

        # lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand ? lowerBand : prevLowerBand
        if prev_lower_valid:
            if not (lower[i] > lower[i - 1] or close[i - 1] < lower[i - 1]):
                lower[i] = lower[i - 1]

        # upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand ? upperBand : prevUpperBand
        if prev_upper_valid:
            if not (upper[i] < upper[i - 1] or close[i - 1] > upper[i - 1]):
                upper[i] = upper[i - 1]

        # Step 2: Determine direction based on previous supertrend position
        # In Pine: if prevSuperTrend == prevUpperBand means we were bearish (direction was 1)
        if dir_[i - 1] == 1:  # Previous was bearish (supertrend was upper band)
            # _direction := close > upperBand ? -1 : 1
            if close[i] > upper[i]:
                dir_[i] = -1  # Flip to bullish
            else:
                dir_[i] = 1   # Stay bearish
        else:  # Previous was bullish (direction was -1, supertrend was lower band)
            # _direction := close < lowerBand ? 1 : -1
            if close[i] < lower[i]:
                dir_[i] = 1   # Flip to bearish
            else:
                dir_[i] = -1  # Stay bullish

        # Step 3: Set supertrend value based on direction
        # superTrend := _direction == -1 ? lowerBand : upperBand
        if dir_[i] == -1:  # Bullish
            trend[i] = lower[i]
            long[i] = lower[i]
        else:  # Bearish (direction == 1)
            trend[i] = upper[i]
            short[i] = upper[i]

    return trend, dir_, long, short


def calculate_supertrend(high, low, close, period=7, multiplier=3):
    """
    Calculate Supertrend indicator matching Pine Script v6 exactly

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

        # Calculate HL2 (src = hl2 in Pine Script)
        hl2_price = (high + low) / 2.0

        # Calculate ATR using talib
        atr = talib.ATR(high, low, close, period)

        # Get basic bands
        upper, lower = get_basic_bands(hl2_price, atr, multiplier)

        # Make copies to avoid modifying original arrays
        upper = upper.copy()
        lower = lower.copy()

        # Calculate final bands with direction (matching Pine Script)
        trend, direction, long, short = get_final_bands_nb(close, upper, lower)

        logger.debug(f"Supertrend calculated: period={period}, multiplier={multiplier}")

        return trend, direction, long, short

    except Exception as e:
        logger.error(f"Error calculating Supertrend: {e}", exc_info=True)
        # Return NaN arrays on error
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
        # For now, simple sum of close prices (can be customized based on strategy)
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
        trend, direction, long, short = calculate_supertrend(
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
            'long': long,
            'short': short,
            'signal': get_supertrend_signal(direction)
        }

    except Exception as e:
        logger.error(f"Error calculating spread Supertrend: {e}", exc_info=True)
        return None