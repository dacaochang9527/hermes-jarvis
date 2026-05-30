from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from .eastmoney import calc_limit_up
from .models import DailyBar


def akshare_symbol_for_code(code: str) -> str:
    prefix = "sh" if code.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{code}"


def parse_akshare_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def bars_from_akshare_daily(code: str, name: str, df: pd.DataFrame, pre_close: float | None = None) -> list[DailyBar]:
    if df.empty:
        return []
    rows = df.sort_values("date")
    bars: list[DailyBar] = []
    prev_close = pre_close
    for _, row in rows.iterrows():
        close = float(row["close"])
        if prev_close is None:
            prev_close = float(row["open"])
        bars.append(DailyBar(
            code=code,
            name=name,
            trade_date=parse_akshare_date(row["date"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=close,
            prev_close=float(prev_close),
            volume=float(row.get("volume", 0)),
            amount=float(row.get("amount", 0)),
            pct_chg=(close / float(prev_close) - 1) * 100 if prev_close else None,
            turnover_rate=float(row["turnover"]) * 100 if "turnover" in row and pd.notna(row["turnover"]) else None,
            limit_up_price=calc_limit_up(float(prev_close), code, name),
        ))
        prev_close = close
    return bars


class AkshareSinaDailyProvider:
    """Free A-share daily bars via akshare.stock_zh_a_daily (Sina source)."""

    def __init__(self):
        try:
            import akshare as ak
        except Exception as exc:
            raise RuntimeError("akshare 未安装。请运行：.venv/bin/python -m pip install akshare") from exc
        self.ak = ak
        self._names: dict[str, str] = {}

    def stock_codes(self) -> list[str]:
        df = self.ak.stock_info_a_code_name()
        code_col = "code" if "code" in df.columns else "证券代码"
        name_col = "name" if "name" in df.columns else "证券简称"
        self._names.update({str(row[code_col]).zfill(6): str(row[name_col]) for _, row in df.iterrows()})
        return sorted(self._names)

    def name_for_code(self, code: str) -> str:
        return self._names.get(code, code)

    def history(self, code: str, start: date | None = None, end: date | None = None) -> list[DailyBar]:
        start = start or date(2021, 1, 1)
        end = end or date.today()
        # Fetch one extra prior day so prev_close for the first requested date is reliable.
        fetch_start = start - timedelta(days=10)
        symbol = akshare_symbol_for_code(code)
        df = self.ak.stock_zh_a_daily(
            symbol=symbol,
            start_date=fetch_start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="",
        )
        if df.empty:
            return []
        df = df.sort_values("date")
        before = df[df["date"].map(parse_akshare_date) < start]
        pre_close = float(before.iloc[-1]["close"]) if not before.empty else None
        target = df[df["date"].map(parse_akshare_date) >= start]
        return bars_from_akshare_daily(code, self.name_for_code(code), target, pre_close=pre_close)
