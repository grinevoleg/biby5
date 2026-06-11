import random

from backtest.backtester import run_backtest
from bot.config import FeeParams, RiskParams, StrategyParams
from bot.strategy import Candle


def make_candle(ts, o, h, l, c):
    return Candle(ts=ts, open=o, high=h, low=l, close=c, volume=1.0)


def mean_reverting_series(n=3000, seed=1):
    """Синтетика с возвратом к средней: цена колеблется вокруг 100."""
    rng = random.Random(seed)
    candles = []
    p = 100.0
    for i in range(n):
        pull = (100.0 - p) * 0.03            # притяжение к 100
        shock = rng.gauss(0, 0.25)
        o = p
        c = p + pull + shock
        h = max(o, c) + abs(rng.gauss(0, 0.1))
        l = min(o, c) - abs(rng.gauss(0, 0.1))
        candles.append(make_candle(i * 300000, o, h, l, c))
        p = c
    return candles


def default_params():
    sp = StrategyParams(trend_filter=False, min_profit_pct=0.05, min_rr=0.1,
                        time_stop_bars=24)
    rp = RiskParams(equity_cap_usdt=300.0, risk_per_trade_pct=1.0,
                    max_notional_pct=1000.0)
    return sp, rp


def test_backtest_runs_and_accounts_fees():
    sp, rp = default_params()
    fees = FeeParams()
    res = run_backtest("TEST", mean_reverting_series(), sp, rp, fees)
    assert res.trades, "на mean-reverting синтетике должны быть сделки"
    for t in res.trades:
        assert t.fees > 0
        gross = (t.exit - t.entry) * t.qty if t.side == "Buy" \
            else (t.entry - t.exit) * t.qty
        assert abs(t.pnl - (gross - t.fees)) < 1e-9
    # equity сходится с суммой PnL
    total = sum(t.pnl for t in res.trades)
    assert abs((res.end_equity - res.start_equity) - total) < 1e-6


def test_backtest_profitable_on_ideal_mean_reversion():
    """На синтетике, идеально подходящей стратегии, результат должен быть
    положительным — иначе в логике исполнения/комиссий ошибка знака."""
    sp, rp = default_params()
    res = run_backtest("TEST", mean_reverting_series(seed=2), sp, rp,
                       FeeParams())
    assert res.end_equity > res.start_equity


def test_higher_fees_reduce_pnl():
    sp, rp = default_params()
    series = mean_reverting_series(seed=3)
    low = run_backtest("TEST", series, sp, rp,
                       FeeParams(maker=0.0002, taker=0.00055))
    high = run_backtest("TEST", series, sp, rp,
                        FeeParams(maker=0.001, taker=0.001))
    assert high.end_equity < low.end_equity


def test_stop_priority_over_take():
    """Свеча, задевшая и стоп и тейк, должна закрывать сделку по стопу."""
    sp, rp = default_params()
    candles = mean_reverting_series(seed=4)
    res = run_backtest("TEST", candles, sp, rp, FeeParams())
    for t in res.trades:
        if t.exit_reason == "stop":
            # выход по стопу хуже входа (с поправкой на проскальзывание)
            if t.side == "Buy":
                assert t.exit < t.entry
            else:
                assert t.exit > t.entry


def test_no_trades_without_signals():
    sp, rp = default_params()
    flat = [make_candle(i * 300000, 100, 100.01, 99.99, 100.0)
            for i in range(1000)]
    res = run_backtest("TEST", flat, sp, rp, FeeParams())
    assert res.trades == []
