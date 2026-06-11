"""Проверка подключения к Bybit: ключи, баланс, инструменты, позиции.

  python scripts/check_connection.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_config
from bot.exchange import BybitClient


def main():
    cfg = load_config()
    mode = "ДЕМО" if cfg.demo else "РЕАЛЬНЫЙ СЧЁТ"
    print(f"Режим: {mode}")

    if not cfg.api_key or not cfg.api_secret:
        print("ОШИБКА: ключи не заданы. Скопируйте .env.example в .env "
              "и впишите BYBIT_API_KEY / BYBIT_API_SECRET.")
        sys.exit(1)

    client = BybitClient(cfg)

    try:
        equity = client.equity_usdt()
    except Exception as e:
        print(f"ОШИБКА доступа к балансу: {e}\n"
              "Частые причины:\n"
              "- ключ от реального счёта при demo: true (или наоборот) — "
              "ключи демо и реала разные;\n"
              "- у ключа нет прав на чтение Unified Trading;\n"
              "- опечатка в ключе/секрете.")
        sys.exit(1)

    print(f"Баланс: {equity:.2f} USDT — ключи работают")

    for sym in cfg.symbols:
        try:
            candles = client.get_klines(sym, cfg.interval, limit=2)
            ins = client.instrument(sym)
            pos = client.position(sym)
            pos_str = (f"позиция {pos.side} {pos.qty}" if pos.qty > 0
                       else "позиции нет")
            print(f"{sym}: цена {candles[-1].close:.6g}, мин. лот "
                  f"{ins.min_qty}, {pos_str}")
        except Exception as e:
            print(f"{sym}: ОШИБКА — {e}")

    print("Всё в порядке: можно запускать бота (python -m bot.main)")


if __name__ == "__main__":
    main()
