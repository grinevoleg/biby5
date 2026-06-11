import math

from bot.indicators import atr, bollinger, ema, rsi, sma, stdev


def test_sma():
    assert sma([1, 2, 3, 4, 5], 5) == 3.0
    assert sma([1, 2, 3, 4, 5], 3) == 4.0
    assert sma([1, 2], 3) is None


def test_stdev():
    assert math.isclose(stdev([2, 4, 4, 4, 5, 5, 7, 9], 8), 2.0)


def test_bollinger():
    closes = [2, 4, 4, 4, 5, 5, 7, 9]
    mid, up, lo = bollinger(closes, 8, 2.0)
    assert mid == 5.0
    assert up == 9.0
    assert lo == 1.0


def test_ema_constant_series():
    assert math.isclose(ema([5.0] * 50, 10), 5.0)


def test_ema_converges_upward():
    vals = [1.0] * 20 + [10.0] * 100
    e = ema(vals, 10)
    assert 9.9 < e <= 10.0


def test_rsi_bounds():
    up = list(range(1, 40))
    assert rsi([float(x) for x in up], 14) == 100.0
    down = [float(x) for x in range(40, 1, -1)]
    assert rsi(down, 14) < 1.0
    flat_then_mixed = [10.0, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                       10, 11, 10, 11, 10, 11, 10, 11, 10, 11]
    r = rsi(flat_then_mixed, 14)
    assert 30 < r < 70


def test_atr_simple():
    # свечи с постоянным диапазоном high-low = 2, без гэпов
    highs = [11.0] * 20
    lows = [9.0] * 20
    closes = [10.0] * 20
    assert math.isclose(atr(highs, lows, closes, 14), 2.0)


def test_insufficient_data():
    assert rsi([1.0, 2.0], 14) is None
    assert atr([1.0], [1.0], [1.0], 14) is None
    assert bollinger([1.0] * 5, 20, 2.0) is None
    assert ema([1.0] * 5, 20) is None
