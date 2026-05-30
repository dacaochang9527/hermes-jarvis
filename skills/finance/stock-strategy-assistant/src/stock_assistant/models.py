from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyBar:
    code: str
    name: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    volume: float
    amount: float
    pct_chg: float | None = None
    turnover_rate: float | None = None
    limit_up_price: float | None = None


@dataclass(frozen=True)
class StrategySignal:
    code: str
    name: str
    strategy: str
    signal_type: str
    reason: str
    trigger_price: float | None
    invalid_price: float | None
    risk_note: str
