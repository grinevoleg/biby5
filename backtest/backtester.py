"""Бэктестер с консервативной моделью исполнения.

Допущения (намеренно пессимистичные):
- сигнал считается по закрытию свечи i, лимитный вход живёт entry_timeout_bars
  свечей и исполняется, только если цена прошла ЧЕРЕЗ уровень (low < entry для
  лонга), а не просто коснулась;
- на свече исполнения входа тейк не проверяется, стоп — проверяется;
- если в одной свече задеты и стоп, и тейк — считаем, что сработал стоп;
- вход и тейк платят комиссию мейкера, стоп и тайм-стоп — тейкера;
- стоп исполняется с проскальзыванием slippage_pct.
"""
from dataclasses import dataclass, field
from typing import List

from bot.config import FeeParams, RiskParams, StrategyParams
from bot.journal import compute_stats
from bot.risk import RiskManager
from bot.strategy import Candle, MeanReversionStrategy


@dataclass
class BtTrade:
    symbol: str
    side: str
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    qty: float
    pnl: float       # чистый, после комиссий
    fees: float
    exit_reason: str


@dataclass
class BtResult:
    symbol: str
    trades: List[BtTrade] = field(default_factory=list)
    start_equity: float = 0.0
    end_equity: float = 0.0

    def stats(self) -> dict:
        s = compute_stats([t.pnl for t in self.trades],
                          sum(t.fees for t in self.trades))
        s["start_equity"] = self.start_equity
        s["end_equity"] = self.end_equity
        if self.start_equity > 0:
            s["return_pct"] = (self.end_equity / self.start_equity - 1) * 100
        return s


class _FixedJournal:
    """Журнал-заглушка для RiskManager в бэктесте: дневные лимиты
    моделируются отдельно, здесь они отключены."""
    def daily_pnl(self, *_):
        return 0.0

    def daily_trades(self, *_):
        return 0


def run_backtest(symbol: str, candles: List[Candle],
                 sp: StrategyParams, rp: RiskParams, fees: FeeParams,
                 start_equity: float = 300.0,
                 entry_timeout_bars: int = 2,
                 slippage_pct: float = 0.05,
                 min_notional: float = 5.0) -> BtResult:
    from bot.config import ExecutionParams
    strategy = MeanReversionStrategy(sp, fees)
    risk = RiskManager(rp, ExecutionParams(order_qty_min_notional=min_notional),
                       _FixedJournal())

    res = BtResult(symbol=symbol, start_equity=start_equity)
    equity = start_equity
    warmup = strategy.min_bars()
    # окно как у живого бота (он запрашивает min_bars+50 свечей) —
    # и индикаторы совпадают с боевыми, и бэктест на порядок быстрее
    window = warmup + 50
    i = warmup
    n = len(candles)

    while i < n - 1:
        sig = strategy.evaluate(candles[max(0, i + 1 - window):i + 1])
        if sig is None:
            i += 1
            continue

        qty = risk.position_qty(equity, sig.entry, sig.stop)
        if qty <= 0:
            i += 1
            continue

        # --- ожидание исполнения лимитного входа ---
        fill_bar = None
        for j in range(i + 1, min(i + 1 + entry_timeout_bars, n)):
            c = candles[j]
            crossed = c.low < sig.entry if sig.side == "Buy" else c.high > sig.entry
            if crossed:
                fill_bar = j
                break
        if fill_bar is None:
            i += 1
            continue

        # --- позиция открыта, ищем выход ---
        exit_price, exit_reason, exit_bar = None, None, None
        last_bar = min(fill_bar + sp.time_stop_bars, n - 1)
        for j in range(fill_bar, last_bar + 1):
            c = candles[j]
            if sig.side == "Buy":
                if c.low <= sig.stop:
                    exit_price = sig.stop * (1 - slippage_pct / 100)
                    exit_reason = "stop"
                elif j > fill_bar and c.high >= sig.take:
                    exit_price = sig.take
                    exit_reason = "take"
            else:
                if c.high >= sig.stop:
                    exit_price = sig.stop * (1 + slippage_pct / 100)
                    exit_reason = "stop"
                elif j > fill_bar and c.low <= sig.take:
                    exit_price = sig.take
                    exit_reason = "take"
            if exit_price is not None:
                exit_bar = j
                break
        if exit_price is None:
            exit_bar = last_bar
            exit_price = candles[exit_bar].close
            exit_reason = "time"

        # --- PnL и комиссии ---
        entry_fee = qty * sig.entry * fees.maker
        exit_fee = qty * exit_price * (fees.maker if exit_reason == "take"
                                       else fees.taker)
        gross = (exit_price - sig.entry) * qty if sig.side == "Buy" \
            else (sig.entry - exit_price) * qty
        pnl = gross - entry_fee - exit_fee
        equity += pnl

        res.trades.append(BtTrade(
            symbol=symbol, side=sig.side,
            entry_ts=candles[fill_bar].ts, exit_ts=candles[exit_bar].ts,
            entry=sig.entry, exit=exit_price, qty=qty, pnl=pnl,
            fees=entry_fee + exit_fee, exit_reason=exit_reason,
        ))
        i = exit_bar + 1

    res.end_equity = equity
    return res
