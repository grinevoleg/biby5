"""Точка входа: python -m bot.main [--config config.yaml]"""
import argparse
import logging
import os
import sys
import time

from .config import load_config
from .exchange import BybitClient
from .journal import Journal, format_stats
from .risk import RiskManager
from .strategy import MeanReversionStrategy
from .trader import SymbolTrader


def setup_logging(log_file: str):
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO, format=fmt,
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(log_file, encoding="utf-8")],
    )


def main():
    ap = argparse.ArgumentParser(description="Бот mean-reversion для Bybit")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.log_file)
    log = logging.getLogger("main")

    if not cfg.api_key or not cfg.api_secret:
        log.error("Не заданы BYBIT_API_KEY / BYBIT_API_SECRET (.env)")
        sys.exit(1)

    mode = "ДЕМО" if cfg.demo else "РЕАЛЬНЫЙ СЧЁТ"
    log.info("Запуск: %s | %s | таймфрейм %sм", mode,
             ", ".join(cfg.symbols), cfg.interval)
    if not cfg.demo:
        log.warning("Торговля на РЕАЛЬНЫЕ деньги. Ctrl+C в течение 10 с для отмены.")
        time.sleep(10)

    client = BybitClient(cfg)
    journal = Journal(cfg.journal_db)
    strategy = MeanReversionStrategy(cfg.strategy, cfg.fees)
    risk = RiskManager(cfg.risk, cfg.execution, journal)

    equity = client.equity_usdt()
    log.info("Баланс счёта: %.2f USDT, рабочий капитал: %.2f USDT",
             equity, risk.working_equity(equity))

    traders = []
    for sym in cfg.symbols:
        client.set_leverage(sym, cfg.risk.leverage)
        traders.append(SymbolTrader(sym, cfg, client, strategy, risk, journal))

    log.info("Статистика журнала:\n%s", format_stats(journal.stats()))

    log.info("Бот работает. Сигналы возникают редко (обычно несколько в день); "
             "строка состояния — каждые %.0f с.", cfg.execution.heartbeat_sec)

    last_beat = 0.0
    try:
        while True:
            open_total = sum(1 for t in traders if t.in_market)
            for t in traders:
                t.step(open_total)
                open_total = sum(1 for t2 in traders if t2.in_market)
            if time.time() - last_beat >= cfg.execution.heartbeat_sec:
                for t in traders:
                    log.info(t.status_line())
                last_beat = time.time()
            time.sleep(cfg.execution.poll_interval_sec)
    except KeyboardInterrupt:
        log.info("Останов по Ctrl+C")
        for t in traders:
            try:
                t.shutdown()
            except Exception:
                log.exception("ошибка при остановке %s", t.symbol)
        log.info("Итоговая статистика:\n%s", format_stats(journal.stats()))


if __name__ == "__main__":
    main()
