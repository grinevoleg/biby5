"""Перебор параметров стратегии с walk-forward проверкой.

История каждого инструмента делится на обучающий (первые 70%) и проверочный
(последние 30%) периоды. Комбинации ранжируются по обучающему периоду,
но решение принимается по проверочному: параметры, прибыльные только
на обучении — это подгонка под историю, в торговлю их брать нельзя.

  python scripts/optimize.py --days 60
  python scripts/optimize.py --days 90 --interval 15 --top 20
"""
import argparse
import itertools
import os
import sys
from dataclasses import replace
from multiprocessing import Pool, cpu_count

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.backtester import run_backtest
from backtest.data import fetch_klines
from bot.config import load_config
from bot.journal import compute_stats

GRID = {
    "bb_std": [2.0, 2.5, 3.0],
    "rsi_oversold": [20.0, 25.0, 30.0],   # rsi_overbought = 100 - oversold
    "sl_atr_mult": [1.5, 2.5, 3.5],
    "time_stop_bars": [12, 24, 48],
    "trend_filter": [True, False],
}

_DATA = {}   # symbol -> candles, заполняется в воркерах через initializer


def _init_worker(data):
    global _DATA
    _DATA = data


def _eval_combo(args):
    combo, base_sp, rp, fees, split_frac, equity = args
    sp = replace(base_sp, **combo,
                 rsi_overbought=100.0 - combo["rsi_oversold"])
    train_pnls, test_pnls = [], []
    for sym, candles in _DATA.items():
        split = int(len(candles) * split_frac)
        split_ts = candles[split].ts
        warm = 400  # запас на прогрев индикаторов перед проверочным периодом
        train = run_backtest(sym, candles[:split], sp, rp, fees, equity)
        test = run_backtest(sym, candles[max(0, split - warm):], sp, rp,
                            fees, equity)
        train_pnls += [t.pnl for t in train.trades]
        test_pnls += [t.pnl for t in test.trades if t.entry_ts >= split_ts]
    return {
        "combo": combo,
        "train": compute_stats(train_pnls),
        "test": compute_stats(test_pnls),
    }


def fmt(stats):
    if stats.get("trades", 0) == 0:
        return "  нет сделок              "
    pf = stats["profit_factor"]
    pf_s = f"{pf:5.2f}" if pf != float("inf") else "  inf"
    return (f"n={stats['trades']:3d} wr={stats['win_rate']:4.1f}% "
            f"pf={pf_s} pnl={stats['net_pnl']:+7.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--symbols", nargs="*", default=None)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--interval", default=None,
                    help="таймфрейм (по умолчанию из конфига)")
    ap.add_argument("--split", type=float, default=0.7)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    symbols = args.symbols or cfg.symbols
    interval = args.interval or cfg.interval

    print(f"Загрузка истории: {', '.join(symbols)}, {args.days}д, {interval}м")
    data = {}
    for sym in symbols:
        candles = fetch_klines(sym, interval, args.days,
                               cache=not args.no_cache)
        if len(candles) < 1000:
            print(f"{sym}: мало данных ({len(candles)}), пропускаю")
            continue
        data[sym] = candles
    if not data:
        sys.exit("нет данных")

    combos = [dict(zip(GRID, vals))
              for vals in itertools.product(*GRID.values())]
    print(f"Комбинаций: {len(combos)}, процессов: {args.workers}")

    tasks = [(c, cfg.strategy, cfg.risk, cfg.fees, args.split,
              cfg.risk.equity_cap_usdt) for c in combos]
    with Pool(args.workers, initializer=_init_worker,
              initargs=(data,)) as pool:
        results = []
        for k, r in enumerate(pool.imap_unordered(_eval_combo, tasks), 1):
            results.append(r)
            print(f"\r{k}/{len(combos)}", end="", flush=True)
    print()

    # минимум сделок на обучении, чтобы статистика что-то значила
    results = [r for r in results if r["train"].get("trades", 0) >= 30]
    results.sort(key=lambda r: r["train"].get("net_pnl", -1e9), reverse=True)

    print(f"\nТоп-{args.top} по обучающему периоду "
          f"(решает ПРОВЕРОЧНЫЙ — правая колонка):")
    header = (f"{'bb':>4} {'rsi':>4} {'sl':>4} {'tstop':>5} {'trend':>5} | "
              f"{'обучение':^34} | {'проверка':^34}")
    print(header)
    print("-" * len(header))
    for r in results[:args.top]:
        c = r["combo"]
        print(f"{c['bb_std']:4.1f} {c['rsi_oversold']:4.0f} "
              f"{c['sl_atr_mult']:4.1f} {c['time_stop_bars']:5d} "
              f"{str(c['trend_filter'])[:5]:>5} | {fmt(r['train'])} | "
              f"{fmt(r['test'])}")

    good = [r for r in results[:args.top]
            if r["test"].get("trades", 0) >= 10
            and r["test"].get("net_pnl", 0) > 0]
    if good:
        c = good[0]["combo"]
        print("\nЛучшая комбинация, подтверждённая проверочным периодом, "
              "для config.yaml:")
        print(f"  bb_std: {c['bb_std']}\n"
              f"  rsi_oversold: {c['rsi_oversold']}\n"
              f"  rsi_overbought: {100 - c['rsi_oversold']}\n"
              f"  sl_atr_mult: {c['sl_atr_mult']}\n"
              f"  time_stop_bars: {c['time_stop_bars']}\n"
              f"  trend_filter: {str(c['trend_filter']).lower()}")
        if args.interval:
            print(f"  # и interval: \"{interval}\" на верхнем уровне конфига")
    else:
        print("\nНи одна из топ-комбинаций не прибыльна на проверочном "
              "периоде. Это честный ответ: на этом таймфрейме/периоде "
              "стратегию в торговлю не брать. Попробуйте --interval 15 "
              "или --days 90.")


if __name__ == "__main__":
    main()
