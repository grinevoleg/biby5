"""Управление сделками по одному инструменту: конечный автомат
IDLE -> ENTRY_PENDING -> IN_POSITION -> IDLE.

Вход: post-only лимитник по цене сигнала; не исполнился за entry_timeout —
отмена, за ценой не гонимся. После входа: стоп-лосс вешается на позицию
(рыночный по триггеру mark price), тейк — reduce-only лимитник (мейкер).
Тайм-стоп: позиция старше time_stop_bars баров закрывается по рынку.
"""
import logging
import time

from .config import Config
from .exchange import BybitClient
from .journal import Journal
from .risk import RiskManager
from .strategy import MeanReversionStrategy

log = logging.getLogger("trader")

IDLE = "IDLE"
ENTRY_PENDING = "ENTRY_PENDING"
IN_POSITION = "IN_POSITION"

OPPOSITE = {"Buy": "Sell", "Sell": "Buy"}


class SymbolTrader:
    def __init__(self, symbol: str, cfg: Config, client: BybitClient,
                 strategy: MeanReversionStrategy, risk: RiskManager,
                 journal: Journal):
        self.symbol = symbol
        self.cfg = cfg
        self.client = client
        self.strategy = strategy
        self.risk = risk
        self.journal = journal

        self.state = IDLE
        self.last_snapshot = None      # индикаторы для статусных логов
        self.last_eval_ts = 0          # ts последней оценённой закрытой свечи
        self.entry_order_id = None
        self.entry_deadline = 0.0
        self.signal = None
        self.tp_order_id = None
        self.position_deadline = 0.0   # тайм-стоп
        self.opened_at = None

        self._adopt_existing_position()

    def _adopt_existing_position(self):
        """При старте подхватываем уже открытую позицию (после рестарта)."""
        pos = self.client.position(self.symbol)
        if pos.qty > 0:
            log.warning("%s: найдена открытая позиция %s %s @ %s — подхватываю",
                        self.symbol, pos.side, pos.qty, pos.avg_price)
            self.state = IN_POSITION
            bar_sec = int(self.cfg.interval) * 60
            self.position_deadline = time.time() + \
                self.cfg.strategy.time_stop_bars * bar_sec

    @property
    def in_market(self) -> bool:
        return self.state != IDLE

    def step(self, open_positions_total: int):
        try:
            if self.state == IDLE:
                self._step_idle(open_positions_total)
            elif self.state == ENTRY_PENDING:
                self._step_entry_pending()
            elif self.state == IN_POSITION:
                self._step_in_position()
        except Exception:
            log.exception("%s: ошибка шага, состояние %s", self.symbol, self.state)

    # ---------- IDLE ----------

    def _step_idle(self, open_positions_total: int):
        candles = self.client.get_klines(
            self.symbol, self.cfg.interval,
            limit=min(self.strategy.min_bars() + 50, 1000))
        if len(candles) < 2:
            return
        closed = candles[:-1]  # последняя свеча ещё формируется
        if closed[-1].ts <= self.last_eval_ts:
            return
        self.last_eval_ts = closed[-1].ts
        self.last_snapshot = self.strategy.snapshot(closed)

        signal = self.strategy.evaluate(closed)
        if signal is None:
            return

        equity = self.client.equity_usdt()
        ok, why = self.risk.can_open(open_positions_total, equity)
        if not ok:
            log.info("%s: сигнал %s пропущен: %s", self.symbol, signal.side, why)
            return

        qty = self.risk.position_qty(equity, signal.entry, signal.stop)
        qty_str = self.client.round_qty(self.symbol, qty) if qty > 0 else None
        if qty_str is None:
            log.info("%s: сигнал %s пропущен: размер меньше минимального лота",
                     self.symbol, signal.side)
            return

        price_str = self.client.round_price(self.symbol, signal.entry)
        try:
            order_id = self.client.place_limit(
                self.symbol, signal.side, qty_str, price_str, post_only=True)
        except Exception as e:
            # post-only отклоняется, если цена пересекла бы стакан — пропускаем
            log.info("%s: вход не размещён (%s)", self.symbol, e)
            return

        self.signal = signal
        self.entry_order_id = order_id
        self.entry_deadline = time.time() + self.cfg.execution.entry_timeout_sec
        self.state = ENTRY_PENDING
        log.info("%s: вход %s qty=%s @ %s (стоп %.6g, тейк %.6g) — %s",
                 self.symbol, signal.side, qty_str, price_str,
                 signal.stop, signal.take, signal.reason)

    # ---------- ENTRY_PENDING ----------

    def _step_entry_pending(self):
        st = self.client.order_state(self.symbol, self.entry_order_id)
        if st is None:
            return

        if st.status == "Filled":
            self._on_entry_filled()
            return

        if not st.is_open:  # отклонён/отменён биржей
            log.info("%s: входной ордер завершился со статусом %s",
                     self.symbol, st.status)
            if st.filled_qty > 0:
                self._on_entry_filled()
            else:
                self._reset()
            return

        if time.time() >= self.entry_deadline:
            log.info("%s: вход не исполнился за %.0f с — отменяю",
                     self.symbol, self.cfg.execution.entry_timeout_sec)
            self.client.cancel_order(self.symbol, self.entry_order_id)
            st = self.client.order_state(self.symbol, self.entry_order_id)
            if st and st.filled_qty > 0:
                self._on_entry_filled()
            else:
                self._reset()

    def _on_entry_filled(self):
        pos = self.client.position(self.symbol)
        if pos.qty <= 0:
            self._reset()
            return
        sig = self.signal
        self.client.set_stop_loss(
            self.symbol, self.client.round_price(self.symbol, sig.stop))
        tp_qty = self.client.round_qty(self.symbol, pos.qty)
        tp_price = self.client.round_price(self.symbol, sig.take)
        try:
            self.tp_order_id = self.client.place_limit(
                self.symbol, OPPOSITE[sig.side], tp_qty, tp_price,
                post_only=False, reduce_only=True)
        except Exception:
            log.exception("%s: не удалось выставить тейк, закрываю по рынку",
                          self.symbol)
            self.client.close_market(self.symbol, OPPOSITE[sig.side], tp_qty)

        bar_sec = int(self.cfg.interval) * 60
        self.position_deadline = time.time() + \
            self.cfg.strategy.time_stop_bars * bar_sec
        self.opened_at = time.time()
        self.state = IN_POSITION
        log.info("%s: позиция открыта %s %.6g @ %.6g, SL %s, TP %s",
                 self.symbol, sig.side, pos.qty, pos.avg_price,
                 self.client.round_price(self.symbol, sig.stop), tp_price)

    # ---------- IN_POSITION ----------

    def _step_in_position(self):
        pos = self.client.position(self.symbol)
        if pos.qty <= 0:
            self._on_position_closed()
            return
        if time.time() >= self.position_deadline:
            log.info("%s: тайм-стоп — закрываю позицию по рынку", self.symbol)
            self.client.cancel_all(self.symbol)
            qty = self.client.round_qty(self.symbol, pos.qty)
            self.client.close_market(self.symbol, OPPOSITE[pos.side], qty)
            # фиксацию результата сделает следующий шаг, когда позиция = 0

    def _on_position_closed(self):
        # reduce-only ордера Bybit снимает сам, но подчищаем на всякий случай
        try:
            self.client.cancel_all(self.symbol)
        except Exception:
            pass
        try:
            pnl = self.client.last_closed_pnl(self.symbol)
        except Exception:
            log.exception("%s: не удалось получить closed PnL", self.symbol)
            pnl = None
        if pnl:
            self.journal.log_trade(
                symbol=self.symbol, side=pnl["side"], qty=pnl["qty"],
                entry_price=pnl["entry_price"], exit_price=pnl["exit_price"],
                pnl=pnl["pnl"], exit_reason="closed",
            )
            log.info("%s: позиция закрыта, PnL %+.4f USDT (сегодня: %+.2f)",
                     self.symbol, pnl["pnl"], self.journal.daily_pnl())
        self._reset()

    def _reset(self):
        self.state = IDLE
        self.entry_order_id = None
        self.signal = None
        self.tp_order_id = None
        self.opened_at = None

    def status_line(self) -> str:
        if self.state == ENTRY_PENDING and self.signal:
            return (f"{self.symbol}: жду исполнения входа {self.signal.side} "
                    f"@ {self.signal.entry:.6g}")
        if self.state == IN_POSITION:
            left = max(0, int(self.position_deadline - time.time()))
            return (f"{self.symbol}: в позиции, до тайм-стопа "
                    f"{left // 60} мин")
        s = self.last_snapshot
        if not s:
            return f"{self.symbol}: жду сигнала (данные ещё накапливаются)"
        return (f"{self.symbol}: жду сигнала | цена {s['close']:.6g} | "
                f"RSI {s['rsi']:.1f} | BB [{s['lower']:.6g} … {s['upper']:.6g}]")

    def shutdown(self):
        """Остановка бота: снимаем невыполненный вход. Открытую позицию
        НЕ закрываем — у неё стоит стоп на бирже, при рестарте подхватим."""
        if self.state == ENTRY_PENDING and self.entry_order_id:
            log.info("%s: останов — отменяю входной ордер", self.symbol)
            self.client.cancel_order(self.symbol, self.entry_order_id)
