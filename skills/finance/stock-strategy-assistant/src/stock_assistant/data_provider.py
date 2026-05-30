from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from .models import DailyBar


class DailyDataProvider(Protocol):
    def history(self, code: str, start: date | None = None, end: date | None = None) -> list[DailyBar]: ...
    def stock_codes(self) -> list[str]: ...


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unsupported date format: {value}")


def parse_optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


class CsvDailyDataProvider:
    """Simple local CSV provider for tests/backtests.

    Expected columns: code,name,date,open,high,low,close,prev_close,volume,amount,limit_up_price.
    """

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    def stock_codes(self) -> list[str]:
        return sorted(path.stem for path in self.data_dir.glob("*.csv"))

    def history(self, code: str, start: date | None = None, end: date | None = None) -> list[DailyBar]:
        path = self.data_dir / f"{code}.csv"
        if not path.exists():
            return []
        rows: list[DailyBar] = []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade_date = parse_date(row["date"])
                if start and trade_date < start:
                    continue
                if end and trade_date > end:
                    continue
                rows.append(DailyBar(
                    code=row["code"], name=row.get("name", code), trade_date=trade_date,
                    open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
                    close=float(row["close"]), prev_close=float(row["prev_close"]),
                    volume=float(row["volume"]), amount=float(row["amount"]),
                    pct_chg=parse_optional_float(row.get("pct_chg")),
                    turnover_rate=parse_optional_float(row.get("turnover_rate")),
                    limit_up_price=parse_optional_float(row.get("limit_up_price")),
                ))
        return sorted(rows, key=lambda b: b.trade_date)


class AkshareDailyDataProvider:
    """Lazy akshare adapter. Import happens at runtime so the project works without the optional dependency."""

    def __init__(self):
        try:
            import akshare as ak  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("akshare 未安装。请运行：python -m pip install '.[data]'") from exc
        self.ak = ak

    def stock_codes(self) -> list[str]:  # pragma: no cover - network/API dependent
        df = self.ak.stock_info_a_code_name()
        return [str(code).zfill(6) for code in df["code"].tolist()]

    def history(self, code: str, start: date | None = None, end: date | None = None) -> list[DailyBar]:  # pragma: no cover
        start_s = (start or date(2021, 1, 1)).strftime("%Y%m%d")
        end_s = (end or date.today()).strftime("%Y%m%d")
        df = self.ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start_s, end_date=end_s, adjust="")
        if df.empty:
            return []
        rows: list[DailyBar] = []
        prev_close = None
        for _, r in df.iterrows():
            close = float(r["收盘"])
            prev = float(prev_close if prev_close is not None else r.get("昨收", r["开盘"]))
            name = str(r.get("股票名称", code))
            # 简化涨停价：普通A股10%，ST 5%，创业板/科创板/北交所后续可扩展。
            limit_up = round(prev * 1.10, 2)
            rows.append(DailyBar(
                code=code, name=name, trade_date=parse_date(str(r["日期"])),
                open=float(r["开盘"]), high=float(r["最高"]), low=float(r["最低"]), close=close,
                prev_close=prev, volume=float(r["成交量"]), amount=float(r["成交额"]),
                pct_chg=float(r["涨跌幅"]) if "涨跌幅" in r else None,
                turnover_rate=float(r["换手率"]) if "换手率" in r else None,
                limit_up_price=limit_up,
            ))
            prev_close = close
        return rows
