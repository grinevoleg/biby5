"""Обёртка над pybit для Bybit v5 API (категория linear).

Демо-счёт включается флагом demo=True (api-demo.bybit.com) — тот же API
и реальные рыночные цены, но виртуальные деньги.
"""
import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import List, Optional

from pybit.exceptions import InvalidRequestError
from pybit.unified_trading import HTTP

from .config import Config
from .strategy import Candle

log = logging.getLogger("exchange")

RET_LEVERAGE_NOT_MODIFIED = 110043


@dataclass
class Instrument:
    symbol: str
    tick_size: Decimal
    qty_step: Decimal
    min_qty: Decimal


@dataclass
class Position:
    symbol: str
    side: str       # "Buy" | "Sell" | "" (нет позиции)
    qty: float
    avg_price: float


@dataclass
class OrderState:
    order_id: str
    status: str         # New / PartiallyFilled / Filled / Cancelled / ...
    filled_qty: float
    avg_fill_price: float

    @property
    def is_open(self) -> bool:
        return self.status in ("New", "PartiallyFilled", "Untriggered")


class BybitClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = HTTP(
            demo=cfg.demo,
            api_key=cfg.api_key or None,
            api_secret=cfg.api_secret or None,
            recv_window=cfg.recv_window,
        )
        self._instruments = {}

    # ---------- маркет-данные ----------

    def get_klines(self, symbol: str, interval: str,
                   limit: int = 300) -> List[Candle]:
        """Свечи по возрастанию времени. Последняя — ещё не закрытая."""
        r = self.http.get_kline(category="linear", symbol=symbol,
                                interval=interval, limit=limit)
        rows = r["result"]["list"]  # API отдаёт от новых к старым
        return [
            Candle(ts=int(x[0]), open=float(x[1]), high=float(x[2]),
                   low=float(x[3]), close=float(x[4]), volume=float(x[5]))
            for x in reversed(rows)
        ]

    def instrument(self, symbol: str) -> Instrument:
        if symbol not in self._instruments:
            r = self.http.get_instruments_info(category="linear", symbol=symbol)
            info = r["result"]["list"][0]
            self._instruments[symbol] = Instrument(
                symbol=symbol,
                tick_size=Decimal(info["priceFilter"]["tickSize"]),
                qty_step=Decimal(info["lotSizeFilter"]["qtyStep"]),
                min_qty=Decimal(info["lotSizeFilter"]["minOrderQty"]),
            )
        return self._instruments[symbol]

    def round_price(self, symbol: str, price: float) -> str:
        tick = self.instrument(symbol).tick_size
        q = (Decimal(str(price)) / tick).quantize(0, ROUND_HALF_UP) * tick
        return format(q.normalize(), "f")

    def round_qty(self, symbol: str, qty: float) -> Optional[str]:
        ins = self.instrument(symbol)
        q = (Decimal(str(qty)) / ins.qty_step).quantize(0, ROUND_DOWN) * ins.qty_step
        if q < ins.min_qty:
            return None
        return format(q.normalize(), "f")

    # ---------- аккаунт ----------

    def equity_usdt(self) -> float:
        r = self.http.get_wallet_balance(accountType="UNIFIED")
        return float(r["result"]["list"][0]["totalEquity"])

    def set_leverage(self, symbol: str, leverage: int):
        try:
            self.http.set_leverage(category="linear", symbol=symbol,
                                   buyLeverage=str(leverage),
                                   sellLeverage=str(leverage))
        except InvalidRequestError as e:
            if e.status_code != RET_LEVERAGE_NOT_MODIFIED:
                raise

    # ---------- ордера и позиции ----------

    def place_limit(self, symbol: str, side: str, qty: str, price: str,
                    post_only: bool = True, reduce_only: bool = False) -> str:
        r = self.http.place_order(
            category="linear", symbol=symbol, side=side,
            orderType="Limit", qty=qty, price=price,
            timeInForce="PostOnly" if post_only else "GTC",
            reduceOnly=reduce_only,
            orderLinkId=uuid.uuid4().hex[:32],
        )
        return r["result"]["orderId"]

    def close_market(self, symbol: str, side: str, qty: str) -> str:
        """Закрытие позиции рыночным reduce-only ордером.
        side — сторона ЗАКРЫВАЮЩЕГО ордера (противоположная позиции)."""
        r = self.http.place_order(
            category="linear", symbol=symbol, side=side,
            orderType="Market", qty=qty, reduceOnly=True,
        )
        return r["result"]["orderId"]

    def cancel_order(self, symbol: str, order_id: str):
        try:
            self.http.cancel_order(category="linear", symbol=symbol,
                                   orderId=order_id)
        except InvalidRequestError as e:
            # ордер уже исполнен/отменён — не ошибка
            log.debug("cancel %s: %s", order_id, e)

    def order_state(self, symbol: str, order_id: str) -> Optional[OrderState]:
        r = self.http.get_open_orders(category="linear", symbol=symbol,
                                      orderId=order_id)
        rows = r["result"]["list"]
        if not rows:
            r = self.http.get_order_history(category="linear", symbol=symbol,
                                            orderId=order_id)
            rows = r["result"]["list"]
        if not rows:
            return None
        o = rows[0]
        return OrderState(
            order_id=o["orderId"],
            status=o["orderStatus"],
            filled_qty=float(o.get("cumExecQty") or 0),
            avg_fill_price=float(o.get("avgPrice") or 0),
        )

    def position(self, symbol: str) -> Position:
        r = self.http.get_positions(category="linear", symbol=symbol)
        rows = r["result"]["list"]
        if rows and float(rows[0].get("size") or 0) > 0:
            p = rows[0]
            return Position(symbol=symbol, side=p["side"],
                            qty=float(p["size"]),
                            avg_price=float(p["avgPrice"]))
        return Position(symbol=symbol, side="", qty=0.0, avg_price=0.0)

    def set_stop_loss(self, symbol: str, stop_price: str):
        try:
            self.http.set_trading_stop(
                category="linear", symbol=symbol, positionIdx=0,
                stopLoss=stop_price, slTriggerBy="MarkPrice",
            )
        except InvalidRequestError as e:
            log.warning("set_trading_stop %s: %s", symbol, e)
            raise

    def cancel_all(self, symbol: str):
        self.http.cancel_all_orders(category="linear", symbol=symbol)

    def last_closed_pnl(self, symbol: str) -> Optional[dict]:
        """Последняя запись closed PnL (включает комиссии)."""
        r = self.http.get_closed_pnl(category="linear", symbol=symbol, limit=1)
        rows = r["result"]["list"]
        if not rows:
            return None
        p = rows[0]
        return {
            "qty": float(p["qty"]),
            "entry_price": float(p["avgEntryPrice"]),
            "exit_price": float(p["avgExitPrice"]),
            "pnl": float(p["closedPnl"]),
            "side": p["side"],
            "updated": int(p["updatedTime"]),
        }
