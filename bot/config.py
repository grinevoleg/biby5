"""Загрузка конфигурации из config.yaml и ключей из .env."""
import os
from dataclasses import dataclass, field

import yaml
from dotenv import load_dotenv


@dataclass
class StrategyParams:
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    atr_period: int = 14
    sl_atr_mult: float = 1.5
    trend_ema_period: int = 200
    trend_filter: bool = True
    min_profit_pct: float = 0.25
    min_rr: float = 0.5
    time_stop_bars: int = 24


@dataclass
class RiskParams:
    equity_cap_usdt: float = 300.0
    risk_per_trade_pct: float = 1.0
    max_notional_pct: float = 30.0
    max_positions: int = 2
    daily_loss_limit_pct: float = 3.0
    max_trades_per_day: int = 15
    leverage: int = 2


@dataclass
class ExecutionParams:
    poll_interval_sec: float = 5.0
    entry_timeout_sec: float = 120.0
    order_qty_min_notional: float = 5.0


@dataclass
class FeeParams:
    maker: float = 0.0002
    taker: float = 0.00055

    @property
    def round_trip_maker(self) -> float:
        return self.maker * 2


@dataclass
class Config:
    api_key: str = ""
    api_secret: str = ""
    demo: bool = True
    recv_window: int = 5000
    symbols: list = field(default_factory=lambda: ["SOLUSDT"])
    interval: str = "5"
    strategy: StrategyParams = field(default_factory=StrategyParams)
    risk: RiskParams = field(default_factory=RiskParams)
    execution: ExecutionParams = field(default_factory=ExecutionParams)
    fees: FeeParams = field(default_factory=FeeParams)
    journal_db: str = "journal.db"
    log_file: str = "logs/bot.log"


def _take(cls, raw: dict):
    known = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in (raw or {}).items() if k in known})


def load_config(path: str = "config.yaml") -> Config:
    load_dotenv()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    ex = raw.get("exchange", {}) or {}
    cfg = Config(
        api_key=os.getenv("BYBIT_API_KEY", ""),
        api_secret=os.getenv("BYBIT_API_SECRET", ""),
        demo=bool(ex.get("demo", True)),
        recv_window=int(ex.get("recv_window", 5000)),
        symbols=list(raw.get("symbols", ["SOLUSDT"])),
        interval=str(raw.get("interval", "5")),
        strategy=_take(StrategyParams, raw.get("strategy")),
        risk=_take(RiskParams, raw.get("risk")),
        execution=_take(ExecutionParams, raw.get("execution")),
        fees=_take(FeeParams, raw.get("fees")),
        journal_db=raw.get("journal_db", "journal.db"),
        log_file=raw.get("log_file", "logs/bot.log"),
    )
    return cfg
