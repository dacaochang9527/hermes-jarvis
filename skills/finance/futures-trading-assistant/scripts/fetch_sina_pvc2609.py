#!/usr/bin/env python3
"""Fetch PVC2609 market data from Sina futures API with proper Referer header.

Usage:
  python scripts/fetch_sina_pvc2609.py [--kline 3|15|30|60|120|daily] [--quote]

Outputs parsed JSON to stdout by default.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import date

QUOTE_URL = "https://hq.sinajs.cn/list=nf_V2609"
KLINE_URLS = {
    3: "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_3=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=3",
    15: "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_15=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=15",
    30: "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_30=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=30",
    60: "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_60=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=60",
    120: "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_120=/InnerFuturesNewService.getFewMinLine?symbol=V2609&type=120",
    "daily": "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_V2609_D=/InnerFuturesNewService.getDailyKLine?symbol=V2609",
}
HEADERS = {"Referer": "https://finance.sina.com.cn"}


def fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_jsonp(raw: str) -> list[dict]:
    """Extract and parse JSON array from Sina JSONP response.

    Handles:
    - Optional redirect script prefix: /*<script>location.href=...</script>*/
    - Literal control characters (\\n, \\r) inside JSON strings
    """
    clean = re.sub(r"^/\*<script>.*?</script>\*/", "", raw)
    m = re.search(r"=\s*\((\[.*\])\s*\);", clean, re.DOTALL)
    if not m:
        raise ValueError("Could not find JSON array in response")
    js = m.group(1)
    js_clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", js)
    return json.loads(js_clean)


def parse_quote(raw: str) -> dict:
    """Parse Sina quote CSV string into dict."""
    m = re.search(r'"(.+)"', raw)
    if not m:
        raise ValueError("Could not find quote data")
    fields = m.group(1).split(",")
    return {
        "name": fields[0],
        "timestamp": fields[1],  # e.g. 150418 = 15:04:18
        "open": fields[2],
        "prev_settlement": fields[3],
        "current": fields[4],
        "high": fields[5],
        "low": fields[6],
        "bid1": fields[7],
        "bid1_qty": fields[8],
        "ask1": fields[9],
        "ask1_qty": fields[10],
        "volume": fields[11],
        "amount": fields[12],
        "open_interest": fields[13],
        "settlement": fields[14],
        "prev_close": fields[15],
        "date": fields[16],
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch PVC2609 market data from Sina")
    parser.add_argument("--quote", action="store_true", help="Fetch quote snapshot")
    parser.add_argument("--kline", type=str, default=None,
                        help="Fetch K-line: 3, 15, 30, 60, 120, or 'daily'")
    parser.add_argument("--filter-today", action="store_true",
                        help="Only show today's bars (for intraday K-lines)")
    parser.add_argument("--last", type=int, default=None,
                        help="Show only last N bars")
    args = parser.parse_args()

    if args.quote:
        raw = fetch(QUOTE_URL)
        data = parse_quote(raw)
        print(json.dumps(data, indent=2, ensure_ascii=False))

    if args.kline:
        period = args.kline
        if period.isdigit():
            period = int(period)
        url = KLINE_URLS.get(period)
        if not url:
            print(f"Unknown period: {args.kline}. Choose from: 3, 15, 30, 60, 120, daily", file=sys.stderr)
            sys.exit(1)
        raw = fetch(url)
        bars = parse_jsonp(raw)

        today_str = str(date.today())
        if args.filter_today:
            bars = [b for b in bars if b.get("d", "").startswith(today_str)]
        if args.last:
            bars = bars[-args.last:]

        # Print as aligned table
        for b in bars:
            t = b.get("d", "?")[11:19] if args.filter_today else b.get("d", "?")
            print(f"{t} O:{b['o']} H:{b['h']} L:{b['l']} C:{b['c']} V:{b.get('v','?')} OI:{b.get('p','?')}")


if __name__ == "__main__":
    main()
