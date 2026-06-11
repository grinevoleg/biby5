"""Стратегия возврата к средней (mean reversion) для коротких сделок.

Идея: на ликвидных перпетуалах цена после резкого отклонения от средней
(нижняя/верхняя полоса Боллинджера + экстремальный RSI) статистически чаще
возвращается к SMA20, чем продолжает движение. Тейк — средняя полоса,
стоп — кратное ATR. Вход и тейк лимитными post-only ордерами (комиссия
мейкера 0.02%), стоп — рыночный по триггеру (тейкер, срабатывает редко).

Сделка открывается только если расстояние до тейка покрывает комиссии
с запасом (min_profit_pct) и соотношение тейк/стоп не хуже min_rr.
"""
from dataclasses import dataclass
from typing import List, Optional

from .config import FeeParams, StrategyParams
from .indicators import atr, bollinger, ema, rsi


@dataclass
class Candle:
    ts: int  # время открытия, мс
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    side: str  # "Buy" | "Sell"
    entry: float
    stop: float
    take: float
    reason: str


class MeanReversionStrategy:
    def __init__(self, params: StrategyParams, fees: FeeParams):
        self.p = params
        self.fees = fees

    def min_bars(self) -> int:
        p = self.p
        return max(p.bb_period, p.rsi_period + 1, p.atr_period + 1,
                   p.trend_ema_period if p.trend_filter else 0) + 5

    def evaluate(self, candles: List[Candle]) -> Optional[Signal]:
        """candles — только закрытые свечи, последняя в конце."""
        p = self.p
        if len(candles) < self.min_bars():
            return None

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        bb = bollinger(closes, p.bb_period, p.bb_std)
        r = rsi(closes, p.rsi_period)
        a = atr(highs, lows, closes, p.atr_period)
        if bb is None or r is None or a is None or a <= 0:
            return None
        mid, upper, lower = bb

        trend = ema(closes, p.trend_ema_period) if p.trend_filter else None
        last = candles[-1]

        if last.close <= lower and r <= p.rsi_oversold:
            if p.trend_filter and (trend is None or mid <= trend):
                return None
            return self._build("Buy", last.close, mid, a, r)

        if last.close >= upper and r >= p.rsi_overbought:
            if p.trend_filter and (trend is None or mid >= trend):
                return None
            return self._build("Sell", last.close, mid, a, r)

        return None

    def _build(self, side: str, entry: float, take: float, a: float,
               r: float) -> Optional[Signal]:
        p = self.p
        if side == "Buy":
            stop = entry - p.sl_atr_mult * a
            profit = take - entry
            risk = entry - stop
        else:
            stop = entry + p.sl_atr_mult * a
            profit = entry - take
            risk = stop - entry

        if stop <= 0 or risk <= 0 or profit <= 0:
            return None

        profit_pct = profit / entry * 100.0
        # Тейк должен покрывать комиссии круга с трёхкратным запасом
        # и быть не меньше настроенного минимума.
        fee_floor_pct = self.fees.round_trip_maker * 3 * 100.0
        if profit_pct < max(p.min_profit_pct, fee_floor_pct):
            return None
        if profit / risk < p.min_rr:
            return None

        return Signal(
            side=side, entry=entry, stop=stop, take=take,
            reason=f"RSI={r:.1f} close за полосой BB, тейк к SMA{p.bb_period}",
        )
