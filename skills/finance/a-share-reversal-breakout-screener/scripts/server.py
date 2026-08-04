#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import threading
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


STAGES = ("早期", "确认", "观察", "过热")
CODE_PATTERN = re.compile(r"^\d{6}$")
BOOL_FIELDS = {
    "high_elasticity", "limit_up", "ma5_up", "ma10_up", "ma20_up",
    "fundamental_hard_risk",
}
OPTIONAL_BOOL_FIELDS = {"announcement_risk"}
INT_FIELDS = {"score", "days_since_60d_low", "industry_member_count", "secondary_score"}
FLOAT_FIELDS = {
    "close", "pct_chg", "amount_yi", "turnover", "float_cap_yi", "pe",
    "max_drawdown_pct", "base_range_pct", "breakout_ratio", "ma5", "ma10",
    "ma20", "rsi6", "distance_ma20_pct", "return_5d_pct", "volume_ratio",
    "turnover_ratio", "close_position_pct", "industry_rank_pct",
    "industry_return_20d_pct", "industry_breadth_pct", "return_20d_pct",
    "return_60d_pct", "benchmark_return_20d_pct", "benchmark_return_60d_pct",
    "rs20_benchmark_pct", "rs60_benchmark_pct", "stock_vs_industry_20d_pct",
    "ma60", "ma120", "ma60_slope_10d_pct", "ma120_slope_10d_pct",
    "breakout_60d_ratio", "base_volume_contraction_ratio", "revenue_yoy_pct",
    "deduct_profit_yoy_pct", "operating_cashflow_yi", "debt_ratio_pct", "roe_pct",
}


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _optional_bool(value: Any) -> bool | None:
    if value in (None, "", "None", "null", "-"):
        return None
    return _bool(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_candidate(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for field in BOOL_FIELDS:
        result[field] = _bool(row.get(field))
    for field in OPTIONAL_BOOL_FIELDS:
        result[field] = _optional_bool(row.get(field))
    for field in INT_FIELDS:
        try:
            result[field] = int(float(row.get(field) or 0))
        except (TypeError, ValueError):
            result[field] = 0
    for field in FLOAT_FIELDS:
        result[field] = _float_or_none(row.get(field))
    return result


@dataclass
class ReportSnapshot:
    path: Path
    mtime_ns: int
    payload: dict[str, Any]
    codes: set[str]


class ReportStore:
    def __init__(self, report_dir: Path, report_path: Path | None = None):
        self.report_dir = report_dir
        self.report_path = report_path
        self._snapshot: ReportSnapshot | None = None
        self._lock = threading.RLock()

    def _latest_path(self) -> Path:
        if self.report_path:
            if not self.report_path.exists():
                raise FileNotFoundError(f"指定报告不存在: {self.report_path}")
            return self.report_path
        paths = list(self.report_dir.glob("reversal_breakout_*.csv"))
        if not paths:
            raise FileNotFoundError(f"报告目录没有筛选 CSV: {self.report_dir}")
        return max(paths, key=lambda item: item.stat().st_mtime_ns)

    def load(self) -> ReportSnapshot:
        with self._lock:
            path = self._latest_path()
            mtime_ns = path.stat().st_mtime_ns
            if (
                self._snapshot
                and self._snapshot.path == path
                and self._snapshot.mtime_ns == mtime_ns
            ):
                return self._snapshot

            groups = {stage: [] for stage in STAGES}
            codes: set[str] = set()
            data_dates: list[str] = []
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for raw in csv.DictReader(handle):
                    candidate = normalize_candidate(raw)
                    stage = str(candidate.get("stage") or "")
                    if stage not in groups:
                        continue
                    groups[stage].append(candidate)
                    code = str(candidate.get("code") or "")
                    if CODE_PATTERN.fullmatch(code):
                        codes.add(code)
                    trade_date = str(candidate.get("trade_date") or "")
                    if trade_date:
                        data_dates.append(trade_date)

            for stage in STAGES:
                groups[stage].sort(
                    key=lambda item: (
                        -int(item.get("secondary_score") or 0),
                        -int(item.get("score") or 0),
                        str(item.get("code") or ""),
                    )
                )
            all_rows = [row for stage in STAGES for row in groups[stage]]
            payload = {
                "report": path.name,
                "report_path": str(path),
                "report_updated_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(
                    timespec="seconds"
                ),
                "data_date": max(data_dates) if data_dates else None,
                "counts": {stage: len(groups[stage]) for stage in STAGES},
                "total": sum(len(groups[stage]) for stage in STAGES),
                "focus_counts": {
                    tier: sum(row.get("focus_tier") == tier for row in all_rows)
                    for tier in ("核心观察", "重点复核", "一般观察")
                },
                "metadata_counts": {
                    status: sum(row.get("metadata_status") == status for row in all_rows)
                    for status in ("完整", "部分", "缺失")
                },
                "industries": sorted({
                    str(row.get("industry")) for row in all_rows
                    if row.get("industry") and row.get("industry") != "未分类"
                }),
                "groups": groups,
            }
            self._snapshot = ReportSnapshot(path, mtime_ns, payload, codes)
            return self._snapshot


class KlineStore:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self._cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def _latest_path(self, code: str) -> Path:
        if not CODE_PATTERN.fullmatch(code):
            raise ValueError("股票代码必须是6位数字")
        paths = list(self.cache_dir.glob(f"*_{code}.json"))
        if not paths:
            raise FileNotFoundError(f"没有 {code} 的本地日线缓存")
        return max(paths, key=lambda item: item.stat().st_mtime_ns)

    @staticmethod
    def _moving_average(closes: list[float], index: int, period: int) -> float | None:
        if index + 1 < period:
            return None
        values = closes[index + 1 - period:index + 1]
        return sum(values) / period

    def load(self, code: str, limit: int = 140) -> dict[str, Any]:
        path = self._latest_path(code)
        key = (str(path), path.stat().st_mtime_ns)
        with self._lock:
            rows = self._cache.get(key)
            if rows is None:
                raw_rows = json.loads(path.read_text(encoding="utf-8"))
                closes = [float(row["close"]) for row in raw_rows]
                rows = []
                previous_close: float | None = None
                for index, raw in enumerate(raw_rows):
                    close = float(raw["close"])
                    high = float(raw["high"])
                    low = float(raw["low"])
                    pct_chg = (
                        (close / previous_close - 1) * 100
                        if previous_close and previous_close > 0
                        else float(raw.get("pct_chg") or 0)
                    )
                    amplitude = (
                        (high - low) / previous_close * 100
                        if previous_close and previous_close > 0
                        else 0.0
                    )
                    rows.append({
                        "trade_date": str(raw["trade_date"]),
                        "open": float(raw["open"]),
                        "close": close,
                        "high": high,
                        "low": low,
                        "volume": float(raw.get("volume") or 0),
                        "pct_chg": pct_chg,
                        "amplitude": amplitude,
                        "ma5": self._moving_average(closes, index, 5),
                        "ma10": self._moving_average(closes, index, 10),
                        "ma20": self._moving_average(closes, index, 20),
                        "ma60": self._moving_average(closes, index, 60),
                        "ma120": self._moving_average(closes, index, 120),
                    })
                    previous_close = close
                self._cache = {key: rows}
            safe_limit = max(30, min(int(limit), 181))
            return {
                "code": code,
                "cache_file": path.name,
                "bars": rows[-safe_limit:],
            }


@dataclass
class DashboardContext:
    report_store: ReportStore
    kline_store: KlineStore
    web_dir: Path
    verbose: bool = False


def build_handler(context: DashboardContext) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "ReversalBreakoutDashboard/1.0"

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'",
            )

        def _send_bytes(
            self,
            body: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
            cache_control: str = "no-store",
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            self._security_headers()
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status)

        def _send_error_json(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message, "status": int(status)}, status)

        def _serve_static(self, filename: str) -> None:
            allowed = {"index.html", "app.js", "styles.css"}
            if filename not in allowed:
                self._send_error_json(HTTPStatus.NOT_FOUND, "资源不存在")
                return
            path = context.web_dir / filename
            if not path.exists():
                self._send_error_json(HTTPStatus.NOT_FOUND, f"缺少前端资源: {filename}")
                return
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/javascript"}:
                content_type += "; charset=utf-8"
            self._send_bytes(path.read_bytes(), content_type, cache_control="no-cache")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/healthz":
                    snapshot = context.report_store.load()
                    self._send_json({
                        "ok": True,
                        "report": snapshot.path.name,
                        "total": snapshot.payload["total"],
                    })
                    return
                if parsed.path == "/api/groups":
                    self._send_json(context.report_store.load().payload)
                    return
                if parsed.path == "/api/kline":
                    query = parse_qs(parsed.query)
                    code = (query.get("code") or [""])[0]
                    limit_raw = (query.get("limit") or ["140"])[0]
                    try:
                        limit = int(limit_raw)
                    except ValueError:
                        raise ValueError("limit 必须是整数")
                    self._send_json(context.kline_store.load(code, limit))
                    return
                if parsed.path in {"/", "/index.html"}:
                    self._serve_static("index.html")
                    return
                if parsed.path == "/app.js":
                    self._serve_static("app.js")
                    return
                if parsed.path == "/styles.css":
                    self._serve_static("styles.css")
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "路径不存在")
            except FileNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except ValueError as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

        def do_POST(self) -> None:
            self._send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "本服务只读，不接受写请求")

        def log_message(self, fmt: str, *args: Any) -> None:
            if context.verbose:
                super().log_message(fmt, *args)

    return DashboardHandler


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    host: str,
    port: int,
    report_dir: Path,
    cache_dir: Path,
    web_dir: Path,
    report_path: Path | None = None,
    verbose: bool = False,
) -> DashboardServer:
    context = DashboardContext(
        report_store=ReportStore(report_dir, report_path),
        kline_store=KlineStore(cache_dir),
        web_dir=web_dir,
        verbose=verbose,
    )
    context.report_store.load()
    return DashboardServer((host, port), build_handler(context))


def parse_args() -> argparse.Namespace:
    skill_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="A股超跌反转四组交互式日K看板")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只允许本机访问")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认8765")
    parser.add_argument("--report", type=Path, help="固定使用某个CSV；默认自动读取最新报告")
    parser.add_argument("--report-dir", type=Path, default=skill_dir / "reports")
    parser.add_argument("--cache-dir", type=Path, default=skill_dir / "cache")
    parser.add_argument("--web-dir", type=Path, default=skill_dir / "web")
    parser.add_argument("--open", action="store_true", help="启动后打开默认浏览器")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = create_server(
        args.host,
        args.port,
        args.report_dir,
        args.cache_dir,
        args.web_dir,
        args.report,
        args.verbose,
    )
    actual_host, actual_port = server.server_address[:2]
    url_host = "127.0.0.1" if actual_host in {"0.0.0.0", "::"} else actual_host
    url = f"http://{url_host}:{actual_port}/"
    print(f"本地日K看板已启动：{url}", flush=True)
    print("只读服务；按 Ctrl+C 停止。", flush=True)
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n正在停止服务……", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
