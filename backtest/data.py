"""Загрузка исторических свечей Bybit с кэшированием в CSV."""
import csv
import os
import time
from typing import List

from pybit.unified_trading import HTTP

from bot.strategy import Candle

CACHE_DIR = "data"


def fetch_klines(symbol: str, interval: str, days: int,
                 cache: bool = True) -> List[Candle]:
    path = os.path.join(CACHE_DIR, f"{symbol}_{interval}m_{days}d.csv")
    if cache and os.path.exists(path):
        return _load_csv(path)

    http = HTTP()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 3600 * 1000
    out: List[Candle] = []
    cursor = start_ms
    while cursor < end_ms:
        r = http.get_kline(category="linear", symbol=symbol,
                           interval=interval, start=cursor, limit=1000)
        rows = sorted(r["result"]["list"], key=lambda x: int(x[0]))
        if not rows:
            break
        for x in rows:
            ts = int(x[0])
            if ts >= cursor:
                out.append(Candle(ts=ts, open=float(x[1]), high=float(x[2]),
                                  low=float(x[3]), close=float(x[4]),
                                  volume=float(x[5])))
        last_ts = int(rows[-1][0])
        if last_ts <= cursor:
            break
        cursor = last_ts + 1
        time.sleep(0.1)  # бережём rate limit

    # последняя свеча может быть незакрытой — отбрасываем
    if out:
        out = out[:-1]
    if cache and out:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _save_csv(path, out)
    return out


def _save_csv(path: str, candles: List[Candle]):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts, c.open, c.high, c.low, c.close, c.volume])


def _load_csv(path: str) -> List[Candle]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Candle(ts=int(row["ts"]), open=float(row["open"]),
                              high=float(row["high"]), low=float(row["low"]),
                              close=float(row["close"]),
                              volume=float(row["volume"])))
    return out
