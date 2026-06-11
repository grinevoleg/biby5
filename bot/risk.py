"""Риск-менеджмент: размер позиции, дневные лимиты."""
from .config import ExecutionParams, RiskParams
from .journal import Journal


class RiskManager:
    def __init__(self, params: RiskParams, execution: ExecutionParams,
                 journal: Journal):
        self.p = params
        self.exec = execution
        self.journal = journal

    def working_equity(self, account_equity: float) -> float:
        """Капитал, от которого считается риск: реальный баланс,
        ограниченный equity_cap_usdt (актуально для демо)."""
        return min(account_equity, self.p.equity_cap_usdt)

    def can_open(self, open_positions: int, account_equity: float):
        """-> (разрешено, причина отказа)."""
        if open_positions >= self.p.max_positions:
            return False, f"достигнут лимит позиций ({self.p.max_positions})"
        if self.journal.daily_trades() >= self.p.max_trades_per_day:
            return False, "достигнут дневной лимит сделок"
        eq = self.working_equity(account_equity)
        loss_limit = eq * self.p.daily_loss_limit_pct / 100.0
        if self.journal.daily_pnl() <= -loss_limit:
            return False, (f"дневной лимит убытка {self.p.daily_loss_limit_pct}% "
                           "достигнут, торговля до конца дня (UTC) остановлена")
        return True, ""

    def position_qty(self, account_equity: float, entry: float,
                     stop: float) -> float:
        """Количество контрактов от риска на сделку. 0 — сделка не проходит."""
        eq = self.working_equity(account_equity)
        risk_per_unit = abs(entry - stop)
        if risk_per_unit <= 0 or entry <= 0 or eq <= 0:
            return 0.0
        qty = (eq * self.p.risk_per_trade_pct / 100.0) / risk_per_unit
        max_notional = eq * self.p.max_notional_pct / 100.0
        qty = min(qty, max_notional / entry)
        if qty * entry < self.exec.order_qty_min_notional:
            return 0.0
        return qty
