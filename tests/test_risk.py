from bot.config import ExecutionParams, RiskParams
from bot.risk import RiskManager


class FakeJournal:
    def __init__(self, pnl=0.0, trades=0):
        self.pnl = pnl
        self.trades = trades

    def daily_pnl(self, *_):
        return self.pnl

    def daily_trades(self, *_):
        return self.trades


def make_rm(journal=None, **over):
    rp = RiskParams(**over)
    return RiskManager(rp, ExecutionParams(), journal or FakeJournal())


def test_equity_cap():
    rm = make_rm(equity_cap_usdt=300.0)
    assert rm.working_equity(50000.0) == 300.0
    assert rm.working_equity(150.0) == 150.0


def test_position_qty_from_risk():
    rm = make_rm(equity_cap_usdt=300.0, risk_per_trade_pct=1.0,
                 max_notional_pct=1000.0)
    # риск $3, стоп на $1 от входа -> 3 контракта
    qty = rm.position_qty(account_equity=300.0, entry=100.0, stop=99.0)
    assert abs(qty - 3.0) < 1e-9


def test_position_qty_capped_by_notional():
    rm = make_rm(equity_cap_usdt=300.0, risk_per_trade_pct=10.0,
                 max_notional_pct=30.0)
    qty = rm.position_qty(account_equity=300.0, entry=100.0, stop=99.9)
    assert qty * 100.0 <= 90.0 + 1e-9  # 30% от 300


def test_position_qty_zero_below_min_notional():
    rm = make_rm(equity_cap_usdt=50.0, risk_per_trade_pct=0.1)
    # риск $0.05 при стопе $5 -> номинал около $1 < $5 минимум
    assert rm.position_qty(50.0, entry=100.0, stop=95.0) == 0.0


def test_daily_loss_limit_blocks():
    rm = make_rm(journal=FakeJournal(pnl=-10.0), equity_cap_usdt=300.0,
                 daily_loss_limit_pct=3.0)
    ok, why = rm.can_open(0, 300.0)
    assert not ok and "лимит убытка" in why


def test_loss_within_limit_allows():
    rm = make_rm(journal=FakeJournal(pnl=-5.0), equity_cap_usdt=300.0,
                 daily_loss_limit_pct=3.0)
    ok, _ = rm.can_open(0, 300.0)
    assert ok


def test_max_positions_blocks():
    rm = make_rm(max_positions=2)
    ok, why = rm.can_open(2, 300.0)
    assert not ok and "лимит позиций" in why


def test_max_trades_per_day_blocks():
    rm = make_rm(journal=FakeJournal(trades=15), max_trades_per_day=15)
    ok, why = rm.can_open(0, 300.0)
    assert not ok and "лимит сделок" in why
