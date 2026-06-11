"""Статистика по журналу живых/демо сделок: python scripts/show_stats.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_config
from bot.journal import Journal, format_stats


def main():
    cfg = load_config()
    j = Journal(cfg.journal_db)
    print(format_stats(j.stats()))
    print(f"Сегодня (UTC): PnL {j.daily_pnl():+.2f} USDT, сделок {j.daily_trades()}")


if __name__ == "__main__":
    main()
