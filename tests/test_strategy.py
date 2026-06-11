import math
import random

from bot.config import FeeParams, StrategyParams
from bot.strategy import Candle, MeanReversionStrategy


def make_candles(closes, spread=0.001):
    out = []
    for i, c in enumerate(closes):
        out.append(Candle(ts=i * 60000, open=c, high=c * (1 + spread),
                          low=c * (1 - spread), close=c, volume=1.0))
    return out


def base_params(**over):
    d = dict(trend_filter=False, min_profit_pct=0.05, min_rr=0.1)
    d.update(over)
    return StrategyParams(**d)


def uptrend_with_dip(n=300, base=100.0):
    """Плавный рост со скользящим шумом и резким провалом в конце."""
    rng = random.Random(42)
    closes = []
    p = base
    for _ in range(n - 3):
        p *= 1 + rng.uniform(-0.0008, 0.0012)
        closes.append(p)
    closes += [p * 0.985, p * 0.975, p * 0.965]  # резкий провал ~3.5%
    return closes


def test_long_signal_on_dip():
    strat = MeanReversionStrategy(base_params(), FeeParams())
    candles = make_candles(uptrend_with_dip())
    sig = strat.evaluate(candles)
    assert sig is not None
    assert sig.side == "Buy"
    assert sig.stop < sig.entry < sig.take


def test_short_signal_on_spike():
    strat = MeanReversionStrategy(base_params(), FeeParams())
    closes = uptrend_with_dip()
    mirrored = [200.0 * 100.0 / c for c in closes]  # зеркалим вниз->вверх
    sig = strat.evaluate(make_candles(mirrored))
    assert sig is not None
    assert sig.side == "Sell"
    assert sig.take < sig.entry < sig.stop


def test_no_signal_in_flat_market():
    strat = MeanReversionStrategy(base_params(), FeeParams())
    rng = random.Random(7)
    closes = [100.0 * (1 + rng.uniform(-0.0003, 0.0003)) for _ in range(300)]
    assert strat.evaluate(make_candles(closes)) is None


def test_fee_floor_blocks_tiny_take():
    """Если расстояние до тейка не покрывает комиссии — сделки нет."""
    strat = MeanReversionStrategy(
        base_params(min_profit_pct=50.0), FeeParams())
    candles = make_candles(uptrend_with_dip())
    assert strat.evaluate(candles) is None


def test_trend_filter_blocks_counter_trend_long():
    """Провал в долгом нисходящем тренде: лонг должен блокироваться фильтром."""
    rng = random.Random(3)
    closes = []
    p = 100.0
    for _ in range(400):
        p *= 1 - rng.uniform(0.0, 0.001)
        closes.append(p)
    closes += [p * 0.98, p * 0.97, p * 0.96]
    candles = make_candles(closes)

    with_filter = MeanReversionStrategy(
        base_params(trend_filter=True), FeeParams())
    no_filter = MeanReversionStrategy(base_params(), FeeParams())
    assert no_filter.evaluate(candles) is not None
    assert with_filter.evaluate(candles) is None


def test_insufficient_data_returns_none():
    strat = MeanReversionStrategy(StrategyParams(), FeeParams())
    assert strat.evaluate(make_candles([100.0] * 10)) is None


def test_entry_offset_moves_entry_deeper():
    candles = make_candles(uptrend_with_dip())
    at_close = MeanReversionStrategy(base_params(), FeeParams())
    offset = MeanReversionStrategy(
        base_params(entry_offset_atr=0.5), FeeParams())
    s0 = at_close.evaluate(candles)
    s1 = offset.evaluate(candles)
    assert s0 and s1
    assert s1.entry < s0.entry          # лонг: вход глубже провала
    assert s1.take == s0.take           # тейк тот же (средняя полоса)
    assert s1.take - s1.entry > s0.take - s0.entry  # потенциал больше


def test_min_rr_filter():
    """Сделка с тейком ближе, чем min_rr * стоп, отбрасывается."""
    params_loose = base_params(min_rr=0.01)
    params_strict = base_params(min_rr=10.0)
    candles = make_candles(uptrend_with_dip())
    assert MeanReversionStrategy(params_loose, FeeParams()).evaluate(candles)
    assert MeanReversionStrategy(params_strict, FeeParams()).evaluate(candles) is None
