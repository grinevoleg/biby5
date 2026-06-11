"""Индикаторы на чистом Python. Все функции принимают списки чисел
(старые значения в начале, последняя закрытая свеча в конце) и
возвращают значение на последней точке либо None, если данных мало."""
import math


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def stdev(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    m = sum(window) / period
    return math.sqrt(sum((v - m) ** 2 for v in window) / period)


def bollinger(closes, period, mult):
    """Возвращает (mid, upper, lower) или None."""
    m = sma(closes, period)
    if m is None:
        return None
    s = stdev(closes, period)
    return m, m + mult * s, m - mult * s


def ema(values, period):
    """EMA с инициализацией через SMA первых period значений."""
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(closes, period):
    """RSI со сглаживанием Уайлдера."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def atr(highs, lows, closes, period):
    """ATR со сглаживанием Уайлдера."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = []
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a
