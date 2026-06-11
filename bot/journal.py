"""Журнал сделок в SQLite и расчёт статистики."""
import os
import sqlite3
from datetime import datetime, timezone


class Journal:
    def __init__(self, path: str = "journal.db"):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                pnl REAL NOT NULL,           -- чистый PnL с учётом комиссий, USDT
                fees REAL NOT NULL DEFAULT 0,
                exit_reason TEXT,
                opened_at TEXT,
                closed_at TEXT NOT NULL      -- ISO UTC
            )
        """)
        self.conn.commit()

    def log_trade(self, symbol, side, qty, entry_price, exit_price, pnl,
                  fees=0.0, exit_reason="", opened_at=None, closed_at=None):
        closed_at = closed_at or datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "INSERT INTO trades (symbol, side, qty, entry_price, exit_price,"
            " pnl, fees, exit_reason, opened_at, closed_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (symbol, side, qty, entry_price, exit_price, pnl, fees,
             exit_reason, opened_at, closed_at),
        )
        self.conn.commit()

    def daily_pnl(self, date_utc=None) -> float:
        d = (date_utc or datetime.now(timezone.utc).date()).isoformat()
        row = self.conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE closed_at LIKE ?",
            (d + "%",),
        ).fetchone()
        return float(row[0])

    def daily_trades(self, date_utc=None) -> int:
        d = (date_utc or datetime.now(timezone.utc).date()).isoformat()
        row = self.conn.execute(
            "SELECT COUNT(*) FROM trades WHERE closed_at LIKE ?", (d + "%",)
        ).fetchone()
        return int(row[0])

    def stats(self) -> dict:
        rows = self.conn.execute(
            "SELECT pnl, fees FROM trades ORDER BY id"
        ).fetchall()
        return compute_stats([r[0] for r in rows], sum(r[1] for r in rows))

    def close(self):
        self.conn.close()


def compute_stats(pnls, total_fees=0.0) -> dict:
    n = len(pnls)
    if n == 0:
        return {"trades": 0}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "trades": n,
        "win_rate": len(wins) / n * 100,
        "net_pnl": sum(pnls),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
        "avg_trade": sum(pnls) / n,
        "avg_win": gross_win / len(wins) if wins else 0.0,
        "avg_loss": -gross_loss / len(losses) if losses else 0.0,
        "max_drawdown": max_dd,
        "fees": total_fees,
    }


def format_stats(s: dict) -> str:
    if s.get("trades", 0) == 0:
        return "Сделок нет."
    return (
        f"Сделок: {s['trades']} | Winrate: {s['win_rate']:.1f}% | "
        f"PF: {s['profit_factor']:.2f}\n"
        f"Чистый PnL: {s['net_pnl']:+.2f} USDT (комиссии: {s['fees']:.2f})\n"
        f"Средняя сделка: {s['avg_trade']:+.3f} | "
        f"ср. прибыль: {s['avg_win']:+.3f} | ср. убыток: {s['avg_loss']:+.3f}\n"
        f"Макс. просадка: {s['max_drawdown']:.2f} USDT"
    )
