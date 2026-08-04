#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests


SINA_SPOT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
SINA_COUNT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)
TENCENT_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EASTMONEY_INDUSTRY_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_FUNDAMENTAL_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EASTMONEY_ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
BENCHMARK_SYMBOL = "sh000300"
BENCHMARK_NAME = "沪深300"
MAINBOARD_PREFIXES = ("000", "001", "002", "003", "600", "601", "603", "605")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
}
THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class Spot:
    code: str
    name: str
    price: float
    pct_chg: float
    amount: float
    turnover: float
    pe: float | None
    total_cap: float
    float_cap: float
    high: float
    low: float
    open: float
    prev_close: float
    industry: str = "未分类"


@dataclass(frozen=True)
class Bar:
    trade_date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    pct_chg: float
    turnover: float


@dataclass
class Candidate:
    code: str
    name: str
    trade_date: str
    stage: str
    score: int
    heat: str
    trend: str
    style: str
    high_elasticity: bool
    limit_up: bool
    close: float
    pct_chg: float
    amount_yi: float
    turnover: float
    float_cap_yi: float
    pe: float | None
    max_drawdown_pct: float
    base_range_pct: float
    breakout_ratio: float
    ma5: float
    ma10: float
    ma20: float
    ma5_up: bool
    ma10_up: bool
    ma20_up: bool
    rsi6: float
    distance_ma20_pct: float
    return_5d_pct: float
    volume_ratio: float
    turnover_ratio: float
    close_position_pct: float
    days_since_60d_low: int
    industry: str
    industry_member_count: int
    industry_rank_pct: float | None
    industry_return_20d_pct: float | None
    industry_breadth_pct: float | None
    return_20d_pct: float
    return_60d_pct: float
    benchmark_return_20d_pct: float | None
    benchmark_return_60d_pct: float | None
    rs20_benchmark_pct: float | None
    rs60_benchmark_pct: float | None
    stock_vs_industry_20d_pct: float | None
    ma60: float
    ma120: float
    ma60_slope_10d_pct: float
    ma120_slope_10d_pct: float
    breakout_60d_ratio: float
    long_trend: str
    base_volume_contraction_ratio: float
    volume_structure: str
    fundamental_status: str
    fundamental_hard_risk: bool
    fundamental_report_date: str
    revenue_yoy_pct: float | None
    deduct_profit_yoy_pct: float | None
    operating_cashflow_yi: float | None
    debt_ratio_pct: float | None
    roe_pct: float | None
    fundamental_notes: str
    announcement_risk: bool | None
    announcement_notes: str
    metadata_status: str
    secondary_score: int
    focus_tier: str
    reasons: str
    risks: str


@dataclass(frozen=True)
class IndustryStat:
    member_count: int
    return_20d_pct: float
    return_60d_pct: float
    breadth_pct: float
    rank_pct: float


def _session() -> requests.Session:
    session = getattr(THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.trust_env = False
        session.headers.update(HEADERS)
        THREAD_LOCAL.session = session
    return session


def _request_json(
    url: str,
    params: dict[str, Any],
    timeout: int = 15,
    require_eastmoney_rc: bool = False,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = _session().get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if require_eastmoney_rc and payload.get("rc") != 0:
                raise RuntimeError(f"东方财富返回 rc={payload.get('rc')}")
            return payload
        except Exception as exc:  # 网络层重试
            last_error = exc
            if attempt < 2:
                time.sleep(0.4 * (2 ** attempt))

    # 某些行情站会按 TLS 指纹临时断开 requests；curl 作为同 URL 的只读兜底。
    try:
        full_url = f"{url}?{urlencode(params)}"
        completed = subprocess.run(
            [
                "curl", "--fail", "--silent", "--show-error", "--max-time", str(timeout),
                "--user-agent", HEADERS["User-Agent"],
                "--referer", HEADERS["Referer"],
                full_url,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        if require_eastmoney_rc and payload.get("rc") != 0:
            raise RuntimeError(f"东方财富返回 rc={payload.get('rc')}")
        return payload
    except Exception as curl_error:
        raise RuntimeError(f"requests={last_error}; curl={curl_error}") from curl_error


def _number(value: Any, default: float = 0.0) -> float:
    if value in (None, "", "-"):
        return default
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _fetch_sina_spot_page(page: int, page_size: int) -> list[Spot]:
    payload = _request_json(SINA_SPOT_URL, {
        "page": page,
        "num": page_size,
        "sort": "symbol",
        "asc": 1,
        "node": "hs_a",
        "symbol": "",
        "_s_r_a": "page",
    })
    rows: list[Spot] = []
    for item in payload or []:
        code = str(item.get("code") or "")
        rows.append(Spot(
            code=code,
            name=str(item.get("name") or code),
            price=_number(item.get("trade")),
            pct_chg=_number(item.get("changepercent")),
            amount=_number(item.get("amount")),
            turnover=_number(item.get("turnoverratio")),
            pe=None if item.get("per") in (None, "", "-") else _number(item.get("per")),
            # 新浪 mktcap/nmc 的单位为万元。
            total_cap=_number(item.get("mktcap")) * 1e4,
            float_cap=_number(item.get("nmc")) * 1e4,
            high=_number(item.get("high")),
            low=_number(item.get("low")),
            open=_number(item.get("open")),
            prev_close=_number(item.get("settlement")),
        ))
    return rows


def fetch_spot_universe(page_size: int = 100, workers: int = 8) -> list[Spot]:
    total_payload = _request_json(SINA_COUNT_URL, {"node": "hs_a"})
    total = int(str(total_payload).strip('"'))
    page_count = math.ceil(total / page_size)
    rows: list[Spot] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_fetch_sina_spot_page, page, page_size) for page in range(1, page_count + 1)]
        for future in as_completed(futures):
            rows.extend(future.result())
    # 页面并发返回顺序不稳定，按代码固定顺序并去重。
    return sorted({row.code: row for row in rows}.values(), key=lambda row: row.code)


def _fetch_eastmoney_industry_page(page: int, page_size: int) -> tuple[int, dict[str, str]]:
    payload = _request_json(EASTMONEY_INDUSTRY_URL, {
        "pn": page,
        "pz": page_size,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f12",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f100",
    }, require_eastmoney_rc=True)
    data = payload.get("data") or {}
    mapping = {
        str(row.get("f12") or ""): str(row.get("f100") or "未分类")
        for row in data.get("diff") or []
        if row.get("f12")
    }
    return int(data.get("total") or 0), mapping


def fetch_industry_map(page_size: int = 100, workers: int = 8) -> dict[str, str]:
    total, first = _fetch_eastmoney_industry_page(1, page_size)
    page_count = max(1, math.ceil(total / page_size))
    mapping = dict(first)
    if page_count == 1:
        return mapping
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_fetch_eastmoney_industry_page, page, page_size)
            for page in range(2, page_count + 1)
        ]
        for future in as_completed(futures):
            _, rows = future.result()
            mapping.update(rows)
    return mapping


def _market_id(code: str) -> int:
    return 1 if code.startswith("6") else 0


def _parse_eastmoney_bars(payload: dict[str, Any]) -> list[Bar]:
    data = payload.get("data") or {}
    result: list[Bar] = []
    for raw in data.get("klines") or []:
        parts = str(raw).split(",")
        if len(parts) < 11:
            continue
        result.append(Bar(
            trade_date=parts[0],
            open=_number(parts[1]),
            close=_number(parts[2]),
            high=_number(parts[3]),
            low=_number(parts[4]),
            volume=_number(parts[5]),
            amount=_number(parts[6]),
            pct_chg=_number(parts[8]),
            turnover=_number(parts[10]),
        ))
    return result


def _parse_tencent_bars(payload: dict[str, Any], symbol: str) -> list[Bar]:
    data = (payload.get("data") or {}).get(symbol) or {}
    raw_rows = data.get("qfqday") or data.get("day") or []
    result: list[Bar] = []
    previous_close = 0.0
    for parts in raw_rows:
        if len(parts) < 6:
            continue
        close = _number(parts[2])
        pct_chg = (close / previous_close - 1) * 100 if previous_close > 0 else 0.0
        result.append(Bar(
            trade_date=str(parts[0]),
            open=_number(parts[1]),
            close=close,
            high=_number(parts[3]),
            low=_number(parts[4]),
            volume=_number(parts[5]),
            amount=0.0,
            pct_chg=pct_chg,
            turnover=0.0,
        ))
        previous_close = close
    return result


def fetch_history(code: str, cache_dir: Path, use_cache: bool = True) -> list[Bar]:
    cache_file = cache_dir / f"{date.today().isoformat()}_{code}.json"
    if use_cache:
        reusable = cache_file if cache_file.exists() else None
        if reusable is None and datetime.now().hour < 9:
            older = list(cache_dir.glob(f"*_{code}.json"))
            reusable = max(older, key=lambda item: item.stat().st_mtime_ns) if older else None
        if reusable is not None:
            payload = json.loads(reusable.read_text(encoding="utf-8"))
            return [Bar(**row) for row in payload]

    symbol = ("sh" if code.startswith("6") else "sz") + code
    try:
        payload = _request_json(TENCENT_KLINE_URL, {
            "param": f"{symbol},day,,,180,qfq",
        })
        bars = _parse_tencent_bars(payload, symbol)
        if not bars:
            raise RuntimeError("腾讯未返回日线")
    except Exception as tencent_error:
        start = (date.today() - timedelta(days=500)).strftime("%Y%m%d")
        try:
            payload = _request_json(EASTMONEY_KLINE_URL, {
                "secid": f"{_market_id(code)}.{code}",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": 101,
                "fqt": 1,
                "beg": start,
                "end": "20500101",
                "lmt": 180,
            }, require_eastmoney_rc=True)
            bars = _parse_eastmoney_bars(payload)
        except Exception as eastmoney_error:
            raise RuntimeError(
                f"腾讯日线失败={tencent_error}; 东方财富兜底失败={eastmoney_error}"
            ) from eastmoney_error
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps([asdict(row) for row in bars], ensure_ascii=False),
        encoding="utf-8",
    )
    return bars


def fetch_benchmark_history(cache_dir: Path, use_cache: bool = True) -> list[Bar]:
    cache_file = cache_dir / f"{date.today().isoformat()}_benchmark_{BENCHMARK_SYMBOL}.json"
    if use_cache:
        reusable = cache_file if cache_file.exists() else None
        if reusable is None and datetime.now().hour < 9:
            older = list(cache_dir.glob(f"*_benchmark_{BENCHMARK_SYMBOL}.json"))
            reusable = max(older, key=lambda item: item.stat().st_mtime_ns) if older else None
        if reusable is not None:
            payload = json.loads(reusable.read_text(encoding="utf-8"))
            return [Bar(**row) for row in payload]

    try:
        payload = _request_json(TENCENT_KLINE_URL, {
            "param": f"{BENCHMARK_SYMBOL},day,,,220,qfq",
        })
        bars = _parse_tencent_bars(payload, BENCHMARK_SYMBOL)
        if not bars:
            raise RuntimeError("腾讯未返回沪深300日线")
    except Exception as tencent_error:
        start = (date.today() - timedelta(days=700)).strftime("%Y%m%d")
        try:
            payload = _request_json(EASTMONEY_KLINE_URL, {
                "secid": "1.000300",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": 101,
                "fqt": 0,
                "beg": start,
                "end": "20500101",
                "lmt": 220,
            }, require_eastmoney_rc=True)
            bars = _parse_eastmoney_bars(payload)
        except Exception as eastmoney_error:
            raise RuntimeError(
                f"沪深300日线失败: 腾讯={tencent_error}; 东方财富={eastmoney_error}"
            ) from eastmoney_error
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps([asdict(row) for row in bars], ensure_ascii=False),
        encoding="utf-8",
    )
    return bars


def _mean(values: Iterable[float]) -> float:
    seq = list(values)
    return statistics.fmean(seq) if seq else 0.0


def sma_at(values: list[float], period: int, offset: int = 0) -> float:
    end = len(values) - offset
    start = end - period
    if start < 0 or end <= 0:
        return 0.0
    return _mean(values[start:end])


def rsi_cn(closes: list[float], period: int = 6) -> float:
    if len(closes) < period + 1:
        return 0.0
    avg_up = 0.0
    avg_abs = 0.0
    initialized = False
    for previous, current in zip(closes, closes[1:]):
        delta = current - previous
        up = max(delta, 0.0)
        absolute = abs(delta)
        if not initialized:
            avg_up = up
            avg_abs = absolute
            initialized = True
        else:
            avg_up = (avg_up * (period - 1) + up) / period
            avg_abs = (avg_abs * (period - 1) + absolute) / period
    return 0.0 if avg_abs == 0 else 100.0 * avg_up / avg_abs


def max_drawdown_pct(bars: list[Bar], window: int = 120) -> float:
    sample = bars[-window:]
    if not sample:
        return 0.0
    peak = sample[0].high
    maximum = 0.0
    for bar in sample:
        peak = max(peak, bar.high)
        if peak > 0:
            maximum = max(maximum, (peak - bar.low) / peak * 100)
    return maximum


def period_return_pct(bars: list[Bar], period: int) -> float:
    if len(bars) <= period or bars[-period - 1].close <= 0:
        return 0.0
    return (bars[-1].close / bars[-period - 1].close - 1) * 100


def build_industry_stats(
    spots: list[Spot],
    histories: dict[str, list[Bar]],
) -> dict[str, IndustryStat]:
    grouped: dict[str, list[tuple[float, float, bool]]] = {}
    for spot in spots:
        bars = histories.get(spot.code) or []
        if spot.industry in {"", "未分类"} or len(bars) < 61:
            continue
        closes = [bar.close for bar in bars]
        ma20 = sma_at(closes, 20)
        grouped.setdefault(spot.industry, []).append((
            period_return_pct(bars, 20),
            period_return_pct(bars, 60),
            bars[-1].close > ma20 > 0,
        ))

    raw: dict[str, tuple[int, float, float, float]] = {}
    for industry, values in grouped.items():
        if len(values) < 3:
            continue
        raw[industry] = (
            len(values),
            statistics.median(item[0] for item in values),
            statistics.median(item[1] for item in values),
            sum(item[2] for item in values) / len(values) * 100,
        )

    ranked = sorted(raw, key=lambda name: raw[name][1])
    denominator = max(len(ranked) - 1, 1)
    return {
        industry: IndustryStat(
            member_count=raw[industry][0],
            return_20d_pct=raw[industry][1],
            return_60d_pct=raw[industry][2],
            breadth_pct=raw[industry][3],
            rank_pct=index / denominator * 100,
        )
        for index, industry in enumerate(ranked)
    }


def classify_long_trend(
    close: float,
    ma60: float,
    ma120: float,
    ma60_slope_10d_pct: float,
    ma120_slope_10d_pct: float,
) -> str:
    if close > ma60 > ma120 > 0 and ma60_slope_10d_pct >= 0 and ma120_slope_10d_pct >= 0:
        return "长短共振"
    if close > ma60 > 0 and ma60_slope_10d_pct >= 0:
        return "MA60转强"
    if ma60 > 0 and close >= ma60 * 0.95 and ma60_slope_10d_pct >= -1:
        return "长期修复"
    return "长压未解"


def classify_volume_structure(
    base_volume_contraction_ratio: float,
    volume_ratio: float,
    close_position_pct: float,
) -> str:
    if (
        base_volume_contraction_ratio <= 0.9
        and 1.2 <= volume_ratio <= 3.0
        and close_position_pct >= 70
    ):
        return "缩量后放量"
    if 1.2 <= volume_ratio <= 3.0 and close_position_pct >= 60:
        return "温和放量"
    if volume_ratio > 4 or close_position_pct < 40:
        return "量价分歧"
    return "量价一般"


def classify_style(spot: Spot) -> tuple[str, bool]:
    cap_yi = spot.float_cap / 1e8
    if cap_yi <= 50:
        style = "小盘"
    elif cap_yi <= 500:
        style = "中盘"
    elif cap_yi <= 1500:
        style = "大盘"
    else:
        style = "超大盘"
    high_elasticity = 2 <= spot.price <= 20 and 20 <= cap_yi <= 150
    return style, high_elasticity


def turnover_threshold(float_cap_yi: float) -> float:
    if float_cap_yi <= 50:
        return 4.0
    if float_cap_yi <= 150:
        return 2.0
    if float_cap_yi <= 500:
        return 1.0
    return 0.4


def _score_drawdown(value: float) -> int:
    if value >= 35:
        return 15
    if value >= 25:
        return 10
    return 5 if value >= 20 else 0


def _score_base(value: float) -> int:
    if value <= 15:
        return 15
    if value <= 20:
        return 12
    if value <= 25:
        return 8
    return 3


def _score_breakout(value: float) -> int:
    if value >= 1.0:
        return 20
    if value >= 0.98:
        return 14
    if value >= 0.95:
        return 8
    return 0


def _score_volume(value: float) -> int:
    if 1.3 <= value <= 3.0:
        return 10
    if 1.0 <= value < 1.3 or 3.0 < value <= 4.0:
        return 6
    if value > 4.0:
        return 3
    return 2


def analyze(
    spot: Spot,
    bars: list[Bar],
    min_score: int = 65,
    benchmark_bars: list[Bar] | None = None,
    industry_stats: dict[str, IndustryStat] | None = None,
) -> Candidate | None:
    if len(bars) < 120:
        return None
    closes = [row.close for row in bars]
    latest = bars[-1]
    ma5, ma10, ma20 = (sma_at(closes, period) for period in (5, 10, 20))
    ma5_old, ma10_old, ma20_old = (sma_at(closes, period, 1) for period in (5, 10, 20))
    ma5_up, ma10_up, ma20_up = ma5 > ma5_old, ma10 > ma10_old, ma20 > ma20_old
    ma60, ma120 = sma_at(closes, 60), sma_at(closes, 120)
    ma60_old_10, ma120_old_10 = sma_at(closes, 60, 10), sma_at(closes, 120, 10)
    ma60_slope_10d = (ma60 / ma60_old_10 - 1) * 100 if ma60_old_10 > 0 else 0.0
    ma120_slope_10d = (ma120 / ma120_old_10 - 1) * 100 if ma120_old_10 > 0 else 0.0
    long_trend = classify_long_trend(
        latest.close, ma60, ma120, ma60_slope_10d, ma120_slope_10d
    )

    full_trend = latest.close > ma5 > ma10 > ma20 and ma5_up and ma10_up and ma20_up
    early_trend = (
        latest.close > ma5
        and ma5 > ma10
        and ma5 > ma20
        and ma20_up
    )
    if full_trend:
        trend = "完整多头"
        trend_score = 25
    elif early_trend:
        trend = "早期过渡"
        trend_score = 20
    else:
        trend = "未完成"
        trend_score = 10 if latest.close > max(ma5, ma10, ma20) else 0

    drawdown = max_drawdown_pct(bars)
    previous_20 = bars[-21:-1]
    previous_high = max(row.high for row in previous_20)
    previous_low = min(row.low for row in previous_20)
    base_range = (previous_high / previous_low - 1) * 100 if previous_low > 0 else 999.0
    breakout_ratio = latest.close / previous_high if previous_high > 0 else 0.0
    previous_60 = bars[-61:-1]
    previous_60_high = max(row.high for row in previous_60)
    breakout_60d_ratio = latest.close / previous_60_high if previous_60_high > 0 else 0.0
    volume_ratio = latest.volume / _mean(row.volume for row in previous_20)
    volume_median = statistics.median(row.volume for row in previous_20)
    turnover_ratio = latest.volume / volume_median if volume_median > 0 else 0.0
    return_5d = (latest.close / bars[-6].close - 1) * 100
    distance_ma20 = (latest.close / ma20 - 1) * 100 if ma20 > 0 else 999.0
    rsi6 = rsi_cn(closes, 6)
    day_range = latest.high - latest.low
    close_position = 100.0 if day_range <= 0 else (latest.close - latest.low) / day_range * 100
    recent_base_volume = _mean(row.volume for row in bars[-11:-1])
    prior_base_volume = _mean(row.volume for row in bars[-21:-11])
    base_volume_contraction_ratio = (
        recent_base_volume / prior_base_volume if prior_base_volume > 0 else 1.0
    )
    volume_structure = classify_volume_structure(
        base_volume_contraction_ratio, volume_ratio, close_position
    )
    lows_60 = [row.low for row in bars[-60:]]
    low_index = min(range(len(lows_60)), key=lows_60.__getitem__)
    days_since_low = len(lows_60) - 1 - low_index

    if (
        drawdown < 20
        or latest.close <= ma5
        or ma5 <= ma10
        or ma5 <= ma20
        or not ma20_up
        or breakout_ratio < 0.95
    ):
        return None

    float_cap_yi = spot.float_cap / 1e8
    turnover_ok = spot.turnover >= turnover_threshold(float_cap_yi)
    relative_turnover_ok = 1.2 <= turnover_ratio <= 3.0
    turnover_score = 5 if turnover_ok and relative_turnover_ok else 3 if turnover_ok or relative_turnover_ok else 0
    amount_score = 5 if spot.amount >= 5e8 else 3 if spot.amount >= 2e8 else 0
    close_score = 5 if close_position >= 80 else 3 if close_position >= 60 else 0

    score = (
        _score_drawdown(drawdown)
        + _score_base(base_range)
        + trend_score
        + _score_breakout(breakout_ratio)
        + _score_volume(volume_ratio)
        + turnover_score
        + amount_score
        + close_score
    )
    if score < min_score:
        return None

    if rsi6 >= 80 or distance_ma20 >= 15 or return_5d >= 20:
        heat = "过热"
    elif rsi6 >= 75 or distance_ma20 >= 12 or return_5d >= 15:
        heat = "偏热"
    else:
        heat = "正常"

    if heat == "过热":
        stage = "过热"
    elif score >= 75 and full_trend and breakout_ratio >= 1.0:
        stage = "确认"
    elif score >= 75 and heat == "正常" and (early_trend or breakout_ratio >= 0.98):
        stage = "早期"
    else:
        stage = "观察"

    style, high_elasticity = classify_style(spot)
    limit_up = spot.prev_close > 0 and spot.price >= round(spot.prev_close * 1.10, 2) - 0.01
    return_20d = period_return_pct(bars, 20)
    return_60d = period_return_pct(bars, 60)
    benchmark_return_20d = (
        period_return_pct(benchmark_bars, 20)
        if benchmark_bars and len(benchmark_bars) >= 61
        else None
    )
    benchmark_return_60d = (
        period_return_pct(benchmark_bars, 60)
        if benchmark_bars and len(benchmark_bars) >= 61
        else None
    )
    industry_stat = (industry_stats or {}).get(spot.industry)
    industry_return_20d = industry_stat.return_20d_pct if industry_stat else None
    industry_breadth = industry_stat.breadth_pct if industry_stat else None
    industry_rank = industry_stat.rank_pct if industry_stat else None
    industry_member_count = industry_stat.member_count if industry_stat else 0
    rs20_benchmark = (
        return_20d - benchmark_return_20d
        if benchmark_return_20d is not None else None
    )
    rs60_benchmark = (
        return_60d - benchmark_return_60d
        if benchmark_return_60d is not None else None
    )
    stock_vs_industry = (
        return_20d - industry_return_20d
        if industry_return_20d is not None else None
    )
    reasons = [
        f"120日最大回撤{drawdown:.1f}%",
        trend,
        f"突破比{breakout_ratio:.3f}",
        f"量能{volume_ratio:.2f}倍",
        f"长周期{long_trend}",
    ]
    if industry_rank is not None:
        reasons.append(f"{spot.industry}强度分位{industry_rank:.0f}%")
    risks: list[str] = []
    if heat != "正常":
        risks.append(f"{heat}: RSI6={rsi6:.1f}, MA20乖离={distance_ma20:.1f}%, 5日涨幅={return_5d:.1f}%")
    if close_position < 60:
        risks.append(f"收盘位置仅{close_position:.0f}%")
    if volume_ratio > 4:
        risks.append("量能超过20日均量4倍")
    if turnover_ratio > 4:
        risks.append("换手超过20日中位数4倍")
    if spot.pe is not None and spot.pe < 0:
        risks.append("动态市盈率为负")
    if long_trend == "长压未解":
        risks.append("MA60/MA120长周期压力尚未解除")
    if volume_structure == "量价分歧":
        risks.append("当日量价结构存在分歧")
    if limit_up:
        risks.append("当日涨停，仅记录状态且需关注次日接力波动")

    return Candidate(
        code=spot.code,
        name=spot.name,
        trade_date=latest.trade_date,
        stage=stage,
        score=score,
        heat=heat,
        trend=trend,
        style=style,
        high_elasticity=high_elasticity,
        limit_up=limit_up,
        close=latest.close,
        pct_chg=spot.pct_chg,
        amount_yi=spot.amount / 1e8,
        turnover=spot.turnover,
        float_cap_yi=float_cap_yi,
        pe=spot.pe,
        max_drawdown_pct=drawdown,
        base_range_pct=base_range,
        breakout_ratio=breakout_ratio,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma5_up=ma5_up,
        ma10_up=ma10_up,
        ma20_up=ma20_up,
        rsi6=rsi6,
        distance_ma20_pct=distance_ma20,
        return_5d_pct=return_5d,
        volume_ratio=volume_ratio,
        turnover_ratio=turnover_ratio,
        close_position_pct=close_position,
        days_since_60d_low=days_since_low,
        industry=spot.industry,
        industry_member_count=industry_member_count,
        industry_rank_pct=industry_rank,
        industry_return_20d_pct=industry_return_20d,
        industry_breadth_pct=industry_breadth,
        return_20d_pct=return_20d,
        return_60d_pct=return_60d,
        benchmark_return_20d_pct=benchmark_return_20d,
        benchmark_return_60d_pct=benchmark_return_60d,
        rs20_benchmark_pct=rs20_benchmark,
        rs60_benchmark_pct=rs60_benchmark,
        stock_vs_industry_20d_pct=stock_vs_industry,
        ma60=ma60,
        ma120=ma120,
        ma60_slope_10d_pct=ma60_slope_10d,
        ma120_slope_10d_pct=ma120_slope_10d,
        breakout_60d_ratio=breakout_60d_ratio,
        long_trend=long_trend,
        base_volume_contraction_ratio=base_volume_contraction_ratio,
        volume_structure=volume_structure,
        fundamental_status="数据缺失",
        fundamental_hard_risk=False,
        fundamental_report_date="",
        revenue_yoy_pct=None,
        deduct_profit_yoy_pct=None,
        operating_cashflow_yi=None,
        debt_ratio_pct=None,
        roe_pct=None,
        fundamental_notes="基本面数据尚未补充",
        announcement_risk=None,
        announcement_notes="公告风险数据尚未补充",
        metadata_status="缺失",
        secondary_score=0,
        focus_tier="一般观察",
        reasons="；".join(reasons),
        risks="；".join(risks) if risks else "未触发脚本内主要风险阈值",
    )


ANNOUNCEMENT_RISK_KEYWORDS = (
    "立案调查", "立案告知", "行政处罚", "退市风险", "终止上市",
    "风险警示", "重大诉讼", "重大仲裁", "债务逾期", "债务违约",
    "股份冻结", "司法冻结", "减持计划", "股份减持", "限售股份上市流通",
    "解除限售", "业绩预亏", "预计亏损", "控制权变更",
)


def _optional_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def classify_fundamentals(record: dict[str, Any] | None, pe: float | None) -> dict[str, Any]:
    if not record:
        return {
            "status": "数据缺失",
            "hard_risk": False,
            "report_date": "",
            "revenue_yoy_pct": None,
            "deduct_profit_yoy_pct": None,
            "operating_cashflow_yi": None,
            "debt_ratio_pct": None,
            "roe_pct": None,
            "notes": "未取得最近一期财务指标",
        }

    parent_profit = _optional_number(record.get("PARENTNETPROFIT"))
    deduct_profit = _optional_number(record.get("KCFJCXSYJLR"))
    revenue_yoy = _optional_number(record.get("TOTALOPERATEREVETZ"))
    deduct_profit_yoy = _optional_number(record.get("KCFJCXSYJLRTZ"))
    operating_cashflow = _optional_number(record.get("NETCASH_OPERATE_PK"))
    debt_ratio = _optional_number(record.get("ZCFZL"))
    roe = _optional_number(record.get("ROEJQ"))
    org_type = str(record.get("ORG_TYPE") or "通用")
    report_date = str(record.get("REPORT_DATE_NAME") or record.get("REPORT_DATE") or "")

    hard_flags: list[str] = []
    concerns: list[str] = []
    if parent_profit is not None and parent_profit <= 0:
        hard_flags.append("归母净利润非正")
    if deduct_profit is not None and deduct_profit <= 0:
        hard_flags.append("扣非净利润非正")
    if roe is not None and roe < 0:
        hard_flags.append("ROE为负")
    if pe is not None and pe < 0:
        hard_flags.append("动态市盈率为负")
    if org_type == "通用" and debt_ratio is not None and debt_ratio >= 90:
        hard_flags.append(f"资产负债率{debt_ratio:.1f}%")

    if org_type == "通用" and operating_cashflow is not None and operating_cashflow < 0:
        concerns.append("经营现金流为负")
    if revenue_yoy is not None and revenue_yoy <= -20:
        concerns.append(f"营收同比{revenue_yoy:.1f}%")
    if deduct_profit_yoy is not None and deduct_profit_yoy <= -30:
        concerns.append(f"扣非利润同比{deduct_profit_yoy:.1f}%")
    if org_type == "通用" and debt_ratio is not None and 75 <= debt_ratio < 90:
        concerns.append(f"资产负债率{debt_ratio:.1f}%")

    status = "风险" if hard_flags else "关注" if concerns else "正常"
    notes = [report_date] if report_date else []
    notes.extend(hard_flags or concerns or ["未触发财务硬伤或关注阈值"])
    return {
        "status": status,
        "hard_risk": bool(hard_flags),
        "report_date": report_date,
        "revenue_yoy_pct": revenue_yoy,
        "deduct_profit_yoy_pct": deduct_profit_yoy,
        "operating_cashflow_yi": (
            operating_cashflow / 1e8 if operating_cashflow is not None else None
        ),
        "debt_ratio_pct": debt_ratio,
        "roe_pct": roe,
        "notes": "；".join(notes),
    }


def detect_announcement_risk(
    announcements: list[dict[str, Any]] | None,
    as_of: date | None = None,
    lookback_days: int = 60,
) -> tuple[bool | None, str]:
    if announcements is None:
        return None, "公告数据缺失"
    cutoff = (as_of or date.today()) - timedelta(days=lookback_days)
    hits: list[str] = []
    for item in announcements:
        notice_raw = str(item.get("notice_date") or "")[:10]
        try:
            notice_date = datetime.strptime(notice_raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        if notice_date < cutoff:
            continue
        title = str(item.get("title") or item.get("title_ch") or "")
        if "解除质押" in title or "解除冻结" in title:
            continue
        if any(keyword in title for keyword in ANNOUNCEMENT_RISK_KEYWORDS):
            hits.append(f"{notice_raw} {title}")
    if hits:
        return True, "；".join(hits[:3])
    return False, f"近{lookback_days}日公告未命中脚本风险关键词"


def fetch_candidate_metadata(
    candidate: Candidate,
    metadata_dir: Path,
    use_cache: bool = True,
) -> dict[str, Any]:
    cache_file = metadata_dir / f"{date.today().isoformat()}_{candidate.code}.json"
    if use_cache:
        reusable = cache_file if cache_file.exists() else None
        if reusable is None and datetime.now().hour < 9:
            older = list(metadata_dir.glob(f"*_{candidate.code}.json"))
            reusable = max(older, key=lambda item: item.stat().st_mtime_ns) if older else None
        if reusable is not None:
            return json.loads(reusable.read_text(encoding="utf-8"))

    result: dict[str, Any] = {
        "code": candidate.code,
        "industry": candidate.industry,
        "fundamental": None,
        "announcements": None,
        "errors": [],
    }
    try:
        payload = _request_json(EASTMONEY_FUNDAMENTAL_URL, {
            "reportName": "RPT_F10_FINANCE_MAINFINADATA",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{candidate.code}")',
            "pageNumber": 1,
            "pageSize": 1,
            "source": "WEB",
            "client": "WEB",
        })
        data = (payload.get("result") or {}).get("data") or []
        if not payload.get("success") or not data:
            raise RuntimeError(payload.get("message") or "未返回财务指标")
        result["fundamental"] = data[0]
    except Exception as exc:
        result["errors"].append(f"fundamental={exc}")

    try:
        payload = _request_json(EASTMONEY_ANNOUNCEMENT_URL, {
            "sr": -1,
            "page_size": 50,
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": candidate.code,
            "f_node": 0,
            "s_node": 0,
        })
        result["announcements"] = (payload.get("data") or {}).get("list") or []
    except Exception as exc:
        result["errors"].append(f"announcement={exc}")

    metadata_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def secondary_score(candidate: Candidate) -> int:
    value = 15 if candidate.score >= 90 else 12 if candidate.score >= 85 else 8 if candidate.score >= 75 else 4
    value += 6 if candidate.heat == "正常" else 0
    value += 4 if candidate.rsi6 <= 75 else 0
    value += 4 if candidate.distance_ma20_pct <= 10 else 0
    value += 4 if candidate.breakout_ratio >= 0.98 else 0
    value += 4 if 1.2 <= candidate.volume_ratio <= 3.0 else 0
    value += 3 if candidate.close_position_pct >= 70 else 0

    if candidate.industry_rank_pct is not None:
        value += 10 if candidate.industry_rank_pct >= 70 else 5 if candidate.industry_rank_pct >= 50 else 0
    if candidate.rs20_benchmark_pct is not None:
        value += 8 if candidate.rs20_benchmark_pct >= 0 else 4 if candidate.rs20_benchmark_pct >= -3 else 0
    if candidate.stock_vs_industry_20d_pct is not None:
        value += 7 if candidate.stock_vs_industry_20d_pct >= 0 else 3 if candidate.stock_vs_industry_20d_pct >= -2 else 0

    value += {"长短共振": 10, "MA60转强": 8, "长期修复": 4}.get(candidate.long_trend, 0)
    value += 6 if candidate.breakout_60d_ratio >= 1 else 4 if candidate.breakout_60d_ratio >= 0.95 else 2 if candidate.breakout_60d_ratio >= 0.90 else 0
    value += 4 if candidate.ma120_slope_10d_pct >= 0 else 2 if candidate.ma120_slope_10d_pct >= -1 else 0

    value += {"正常": 7, "关注": 4, "数据缺失": 1}.get(candidate.fundamental_status, 0)
    value += 5 if candidate.announcement_risk is False else 1 if candidate.announcement_risk is None else 0
    value += {"缩量后放量": 3, "温和放量": 2}.get(candidate.volume_structure, 0)
    return max(0, min(100, value))


def classify_focus_tier(candidate: Candidate) -> str:
    core = (
        candidate.secondary_score >= 70
        and candidate.stage in {"早期", "确认"}
        and candidate.heat == "正常"
        and candidate.industry_rank_pct is not None
        and candidate.industry_rank_pct >= 60
        and candidate.rs20_benchmark_pct is not None
        and candidate.rs20_benchmark_pct >= 0
        and candidate.long_trend != "长压未解"
        and not candidate.fundamental_hard_risk
        and candidate.announcement_risk is False
    )
    if core:
        return "核心观察"
    if (
        candidate.secondary_score >= 55
        and not candidate.fundamental_hard_risk
        and candidate.announcement_risk is not True
    ):
        return "重点复核"
    return "一般观察"


def enrich_candidates(
    candidates: list[Candidate],
    metadata_dir: Path,
    workers: int = 12,
    use_cache: bool = True,
) -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(fetch_candidate_metadata, row, metadata_dir, use_cache): row
            for row in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                metadata = future.result()
                fundamental = classify_fundamentals(metadata.get("fundamental"), candidate.pe)
                candidate.fundamental_status = fundamental["status"]
                candidate.fundamental_hard_risk = fundamental["hard_risk"]
                candidate.fundamental_report_date = fundamental["report_date"]
                candidate.revenue_yoy_pct = fundamental["revenue_yoy_pct"]
                candidate.deduct_profit_yoy_pct = fundamental["deduct_profit_yoy_pct"]
                candidate.operating_cashflow_yi = fundamental["operating_cashflow_yi"]
                candidate.debt_ratio_pct = fundamental["debt_ratio_pct"]
                candidate.roe_pct = fundamental["roe_pct"]
                candidate.fundamental_notes = fundamental["notes"]
                candidate.announcement_risk, candidate.announcement_notes = detect_announcement_risk(
                    metadata.get("announcements")
                )
                errors = metadata.get("errors") or []
                candidate.metadata_status = "完整" if not errors else "部分"
                if candidate.fundamental_hard_risk:
                    candidate.risks += f"；基本面硬伤: {candidate.fundamental_notes}"
                if candidate.announcement_risk:
                    candidate.risks += f"；公告风险: {candidate.announcement_notes}"
                if errors:
                    failures.append((candidate.code, "；".join(errors)))
            except Exception as exc:
                candidate.metadata_status = "缺失"
                failures.append((candidate.code, str(exc)))
            candidate.secondary_score = secondary_score(candidate)
            candidate.focus_tier = classify_focus_tier(candidate)
    return failures


def is_eligible_spot(spot: Spot, min_amount: float) -> bool:
    upper_name = spot.name.upper()
    return (
        spot.code.startswith(MAINBOARD_PREFIXES)
        and "ST" not in upper_name
        and "退" not in spot.name
        and spot.price > 0
        and spot.amount >= min_amount
    )


def scan(
    spots: list[Spot],
    cache_dir: Path,
    min_score: int,
    workers: int,
    use_cache: bool,
    benchmark_bars: list[Bar] | None = None,
) -> tuple[list[Candidate], list[tuple[str, str]]]:
    candidates: list[Candidate] = []
    failures: list[tuple[str, str]] = []
    histories: dict[str, list[Bar]] = {}
    total = len(spots)
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_history, spot.code, cache_dir, use_cache): spot
            for spot in spots
        }
        for future in as_completed(futures):
            spot = futures[future]
            completed += 1
            try:
                histories[spot.code] = future.result()
            except Exception as exc:
                failures.append((spot.code, str(exc)))
            if completed % 50 == 0 or completed == total:
                print(
                    f"日线进度 {completed}/{total}，成功 {len(histories)}，失败 {len(failures)}",
                    flush=True,
                )

    industry_stats = build_industry_stats(spots, histories)
    for spot in spots:
        bars = histories.get(spot.code)
        if not bars:
            continue
        try:
            candidate = analyze(
                spot,
                bars,
                min_score=min_score,
                benchmark_bars=benchmark_bars,
                industry_stats=industry_stats,
            )
            if candidate:
                candidates.append(candidate)
        except Exception as exc:
            failures.append((spot.code, f"指标计算={exc}"))
    order = {"早期": 0, "确认": 1, "观察": 2, "过热": 3}
    candidates.sort(key=lambda row: (order[row.stage], -row.score, row.code))
    return candidates, failures


def write_reports(
    candidates: list[Candidate],
    failures: list[tuple[str, str]],
    metadata_failures: list[tuple[str, str]],
    output_dir: Path,
    scanned_count: int,
    source_count: int,
    top: int,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"reversal_breakout_{stamp}.csv"
    md_path = output_dir / f"reversal_breakout_{stamp}.md"

    rows = [asdict(row) for row in candidates]
    if rows:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("code,name,stage,score\n", encoding="utf-8-sig")

    grouped = {stage: [row for row in candidates if row.stage == stage] for stage in ("早期", "确认", "观察", "过热")}
    focus_rows = [row for row in candidates if row.focus_tier == "核心观察"]
    lines = [
        "# A股超跌反转突破筛选",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 日线数据日期：{max((row.trade_date for row in candidates), default='无候选')}",
        "- 数据源：新浪A股快照、腾讯前复权日线与沪深300；东方财富提供日线兜底、行业、财务及公告。",
        f"- 行情源股票数：{source_count}",
        f"- 通过快照预筛并读取日线：{scanned_count}",
        f"- 日线读取失败：{len(failures)}",
        f"- 财务/公告补充不完整：{len(metadata_failures)}",
        f"- 最终候选：{len(candidates)}",
        f"- 二次精选核心观察：{len(focus_rows)}",
        "- 涨停不参与评分；市值和股价只用于风格标签。",
        "",
    ]
    lines.extend([f"## 二次精选·核心观察（{len(focus_rows)}）", ""])
    if not focus_rows:
        lines.extend(["无。", ""])
    else:
        lines.extend([
            "| 代码 | 名称 | 二次分 | 阶段 | 行业/强度 | RS20 | 超行业 | 长周期 | 60日突破 | 基本面 | 公告 |",
            "|---|---|---:|---|---|---:|---:|---|---:|---|---|",
        ])
        for row in sorted(focus_rows, key=lambda item: (-item.secondary_score, -item.score, item.code)):
            lines.append(
                f"| {row.code} | {row.name} | {row.secondary_score} | {row.stage} | "
                f"{row.industry}/{row.industry_rank_pct:.0f}% | {row.rs20_benchmark_pct:.1f}% | "
                f"{row.stock_vs_industry_20d_pct:.1f}% | {row.long_trend} | "
                f"{row.breakout_60d_ratio:.3f} | {row.fundamental_status} | "
                f"{'风险' if row.announcement_risk else '正常'} |"
            )
        lines.append("")
    for stage in ("早期", "确认", "观察", "过热"):
        stage_rows = grouped[stage][:top]
        lines.extend([f"## {stage}（{len(grouped[stage])}）", ""])
        if not stage_rows:
            lines.extend(["无。", ""])
            continue
        lines.extend([
            "| 代码 | 名称 | 分数/二次 | 趋势 | 行业 | RS20 | 长周期 | 60日突破 | 基本面 | 风险 |",
            "|---|---|---:|---|---|---:|---|---:|---|---|",
        ])
        for row in stage_rows:
            lines.append(
                f"| {row.code} | {row.name} | {row.score}/{row.secondary_score} | {row.trend} | "
                f"{row.industry} | {row.rs20_benchmark_pct if row.rs20_benchmark_pct is not None else 0:.1f}% | "
                f"{row.long_trend} | {row.breakout_60d_ratio:.3f} | {row.fundamental_status} | {row.risks} |"
            )
        lines.append("")
    if failures:
        lines.extend(["## 数据失败样本", ""])
        for code, error in failures[:20]:
            lines.append(f"- `{code}`：{error}")
        lines.append("")
    if metadata_failures:
        lines.extend(["## 财务/公告数据失败样本", ""])
        for code, error in metadata_failures[:20]:
            lines.append(f"- `{code}`：{error}")
        lines.append("")
    lines.extend([
        "## 使用说明",
        "",
        "筛选结果是观察信号，不是买卖建议。优先复核早期与确认层；过热层单独观察，不能为凑数补入早期名单。",
        "",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="筛选A股超跌反转突破形态")
    parser.add_argument("--symbols", help="逗号分隔的股票代码；省略时扫描沪深主板")
    parser.add_argument("--min-amount", type=float, default=2e8, help="当日成交额下限，默认2亿元")
    parser.add_argument("--min-score", type=int, default=65, help="最低输出分数，默认65")
    parser.add_argument("--workers", type=int, default=16, help="并发线程数，默认16")
    parser.add_argument("--scan-limit", type=int, help="只扫描预筛后的前N只")
    parser.add_argument("--top", type=int, default=20, help="Markdown每层最多展示数量")
    parser.add_argument("--no-cache", action="store_true", help="不复用当日历史数据缓存")
    parser.add_argument("--skip-enrichment", action="store_true", help="跳过财务与公告补充，仅用于快速冒烟")
    parser.add_argument("--metadata-workers", type=int, default=12, help="财务与公告补充并发数，默认12")
    parser.add_argument("--cache-dir", type=Path, default=skill_dir / "cache")
    parser.add_argument("--metadata-dir", type=Path, default=skill_dir / "metadata")
    parser.add_argument("--output-dir", type=Path, default=skill_dir / "reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("读取新浪A股快照……", flush=True)
    all_spots = fetch_spot_universe()
    try:
        print("读取东方财富行业分类……", flush=True)
        industry_map = fetch_industry_map()
        all_spots = [
            replace(row, industry=industry_map.get(row.code, "未分类"))
            for row in all_spots
        ]
        print(f"行业分类覆盖 {sum(row.industry != '未分类' for row in all_spots)} 只。", flush=True)
    except Exception as exc:
        print(f"行业分类读取失败，将明确标记未分类：{exc}", file=sys.stderr)
    by_code = {row.code: row for row in all_spots}
    if args.symbols:
        requested = [item.strip() for item in args.symbols.split(",") if item.strip()]
        missing = [code for code in requested if code not in by_code]
        if missing:
            print(f"快照中未找到：{','.join(missing)}", file=sys.stderr)
        spots = [by_code[code] for code in requested if code in by_code]
    else:
        spots = [row for row in all_spots if is_eligible_spot(row, args.min_amount)]
    if args.scan_limit:
        spots = spots[:args.scan_limit]
    if not spots:
        print("没有股票进入日线扫描。", file=sys.stderr)
        return 2

    print(f"快照共 {len(all_spots)} 只，进入日线扫描 {len(spots)} 只。", flush=True)
    benchmark_bars: list[Bar] | None = None
    try:
        benchmark_bars = fetch_benchmark_history(args.cache_dir, use_cache=not args.no_cache)
        print(f"{BENCHMARK_NAME}日线 {len(benchmark_bars)} 条，最新 {benchmark_bars[-1].trade_date}。", flush=True)
    except Exception as exc:
        print(f"{BENCHMARK_NAME}读取失败，相对强度将标记缺失：{exc}", file=sys.stderr)
    candidates, failures = scan(
        spots,
        cache_dir=args.cache_dir,
        min_score=args.min_score,
        workers=max(1, args.workers),
        use_cache=not args.no_cache,
        benchmark_bars=benchmark_bars,
    )
    if args.skip_enrichment:
        metadata_failures: list[tuple[str, str]] = []
        for row in candidates:
            row.secondary_score = secondary_score(row)
            row.focus_tier = classify_focus_tier(row)
    else:
        print(f"补充 {len(candidates)} 只候选的财务与近60日公告……", flush=True)
        metadata_failures = enrich_candidates(
            candidates,
            args.metadata_dir,
            workers=max(1, args.metadata_workers),
            use_cache=not args.no_cache,
        )
    order = {"早期": 0, "确认": 1, "观察": 2, "过热": 3}
    focus_order = {"核心观察": 0, "重点复核": 1, "一般观察": 2}
    candidates.sort(key=lambda row: (
        focus_order.get(row.focus_tier, 9), order[row.stage], -row.secondary_score, -row.score, row.code
    ))
    csv_path, md_path = write_reports(
        candidates,
        failures,
        metadata_failures,
        output_dir=args.output_dir,
        scanned_count=len(spots),
        source_count=len(all_spots),
        top=args.top,
    )
    counts = {stage: sum(row.stage == stage for row in candidates) for stage in ("早期", "确认", "观察", "过热")}
    focus_count = sum(row.focus_tier == "核心观察" for row in candidates)
    print(
        f"完成：早期 {counts['早期']}，确认 {counts['确认']}，"
        f"观察 {counts['观察']}，过热 {counts['过热']}，核心观察 {focus_count}，"
        f"日线失败 {len(failures)}，补充不完整 {len(metadata_failures)}",
        flush=True,
    )
    print(f"CSV: {csv_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
