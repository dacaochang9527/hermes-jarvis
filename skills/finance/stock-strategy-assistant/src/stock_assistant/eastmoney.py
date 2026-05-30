from __future__ import annotations

import json
from datetime import date
from typing import Any

import requests

from .models import DailyBar

EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


def market_id_for_code(code: str) -> int:
    """Eastmoney secid market prefix: 1=沪市, 0=深市/北交所等。"""
    return 1 if code.startswith(("5", "6", "9")) else 0


def limit_up_rate_for_code(code: str, name: str = "") -> float:
    upper_name = name.upper()
    if "ST" in upper_name:
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("8", "4")):
        return 0.30
    return 0.10


def calc_limit_up(prev_close: float, code: str, name: str = "") -> float:
    return round(prev_close * (1 + limit_up_rate_for_code(code, name)), 2)


def bars_from_eastmoney_json(payload: dict[str, Any]) -> list[DailyBar]:
    if payload.get("rc") != 0:
        raise RuntimeError(f"eastmoney rc != 0: {payload.get('rc')}")
    data = payload.get("data") or {}
    code = str(data.get("code", ""))
    name = str(data.get("name", code))
    klines = data.get("klines") or []
    prev_close = float(data.get("preKPrice") or 0)
    bars: list[DailyBar] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        trade_date = date.fromisoformat(parts[0])
        open_price = float(parts[1])
        close = float(parts[2])
        high = float(parts[3])
        low = float(parts[4])
        volume = float(parts[5])
        amount = float(parts[6])
        pct_chg = float(parts[8])
        turnover_rate = float(parts[10])
        if prev_close <= 0:
            prev_close = round(close / (1 + pct_chg / 100), 2) if pct_chg != -100 else open_price
        bars.append(DailyBar(
            code=code,
            name=name,
            trade_date=trade_date,
            open=open_price,
            high=high,
            low=low,
            close=close,
            prev_close=prev_close,
            volume=volume,
            amount=amount,
            pct_chg=pct_chg,
            turnover_rate=turnover_rate,
            limit_up_price=calc_limit_up(prev_close, code, name),
        ))
        prev_close = close
    return bars


def eastmoney_kline_params(code: str, start: date | None = None, end: date | None = None) -> dict[str, str]:
    start_s = (start or date(2021, 1, 1)).strftime("%Y%m%d")
    end_s = (end or date.today()).strftime("%Y%m%d")
    return {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101",
        "fqt": "0",
        "secid": f"{market_id_for_code(code)}.{code}",
        "beg": start_s,
        "end": end_s,
    }


def eastmoney_headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }


class EastmoneyDirectProvider:
    def __init__(self, timeout: int = 15, client: str = "curl_cffi", impersonate: str = "chrome120"):
        self.timeout = timeout
        self.client = client
        self.impersonate = impersonate

    def stock_codes(self) -> list[str]:
        # 直连接口暂不扫全市场；全市场列表继续用 akshare 或 CSV。
        return []

    def _get_payload_with_curl_cffi(self, params: dict[str, str]) -> dict[str, Any]:
        try:
            from curl_cffi import requests as curl_requests
        except Exception as exc:  # pragma: no cover - optional dependency import guard
            raise RuntimeError("curl_cffi 未安装，无法使用浏览器 TLS 指纹请求东方财富") from exc
        resp = curl_requests.get(
            EASTMONEY_KLINE_URL,
            params=params,
            headers=eastmoney_headers(),
            timeout=self.timeout,
            impersonate=self.impersonate,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_payload_with_requests(self, params: dict[str, str]) -> dict[str, Any]:
        session = requests.Session()
        session.trust_env = False
        resp = session.get(EASTMONEY_KLINE_URL, params=params, headers=eastmoney_headers(), timeout=self.timeout)
        resp.raise_for_status()
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"eastmoney returned non-json: {resp.text[:200]}") from exc

    def _get_payload(self, params: dict[str, str]) -> dict[str, Any]:
        if self.client == "curl_cffi":
            try:
                return self._get_payload_with_curl_cffi(params)
            except Exception:
                # fallback 便于定位 curl_cffi/TLS 指纹失效时 requests 的原始错误
                return self._get_payload_with_requests(params)
        if self.client == "requests":
            return self._get_payload_with_requests(params)
        raise ValueError(f"unsupported eastmoney client: {self.client}")

    def history(self, code: str, start: date | None = None, end: date | None = None) -> list[DailyBar]:
        payload = self._get_payload(eastmoney_kline_params(code, start, end))
        return bars_from_eastmoney_json(payload)
