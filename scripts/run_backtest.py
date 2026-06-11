"""Бэктест стратегии на исторических данных Bybit.

  python scripts/run_backtest.py --days 30
  python scripts/run_backtest.py --symbols SOLUSDT --days 60 --equity 300
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtester import run_backtest
from backtest.data import fetch_klines
from bot.config import load_config
from bot.journal import compute_stats, format_stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--equity", type=float, default=None,
                    help="стартовый капитал (по умолчанию equity_cap из конфига)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    symbols = args.symbols or cfg.symbols
    equity = args.equity or cfg.risk.equity_cap_usdt

    all_pnls, all_fees = [], 0.0
    for sym in symbols:
        print(f"\n=== {sym} | {args.days}д | {cfg.interval}м ===")
        candles = fetch_klines(sym, cfg.interval, args.days,
                               cache=not args.no_cache)
        if len(candles) < 300:
            print(f"мало данных: {len(candles)} свечей")
            continue
        res = run_backtest(sym, candles, cfg.strategy, cfg.risk, cfg.fees,
                           start_equity=equity)
        s = res.stats()
        print(format_stats(s))
        if s.get("trades"):
            print(f"Капитал: {s['start_equity']:.0f} -> {s['end_equity']:.2f} "
                  f"USDT ({s.get('return_pct', 0):+.2f}%)")
            by_reason = {}
            for t in res.trades:
                by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1
            print("Выходы:", ", ".join(f"{k}={v}" for k, v in by_reason.items()))
        all_pnls += [t.pnl for t in res.trades]
        all_fees += sum(t.fees for t in res.trades)

    if len(symbols) > 1 and all_pnls:
        print(f"\n=== ИТОГО по {len(symbols)} инструментам ===")
        print(format_stats(compute_stats(all_pnls, all_fees)))


if __name__ == "__main__":
    main()
