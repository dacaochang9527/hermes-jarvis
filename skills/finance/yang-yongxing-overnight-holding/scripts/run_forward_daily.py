#!/usr/bin/env python3
"""前瞻性1分钟样本的每日可恢复编排。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys
from zoneinfo import ZoneInfo

import baostock as bs


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_ROOT = pathlib.Path(
    "/Users/fenomenoronaldo/.hermes/data/yang-yongxing-overnight-holding/forward-1m"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=dt.datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--workers", type=int, default=20)
    return parser.parse_args()


def is_trade_date(date: str) -> bool:
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {login.error_msg}")
    try:
        rs = bs.query_trade_dates(start_date=date, end_date=date)
        while rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            return row[1] == "1"
        return False
    finally:
        bs.logout()


def run(command: list[str]) -> None:
    print("RUN " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def complete_json(path: pathlib.Path) -> bool:
    if not path.exists():
        return False
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    args = parse_args()
    root = pathlib.Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    day_dir = root / args.date
    day_dir.mkdir(exist_ok=True)

    if not is_trade_date(args.date):
        result = {"date": args.date, "status": "NOOP_NON_TRADING_DAY"}
        path = day_dir / "non-trading-day.json"
        if not path.exists():
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)
        return

    raw_dir = day_dir / "raw"
    if raw_dir.exists() and not complete_json(raw_dir / "coverage.json"):
        suffix = dt.datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H%M%S")
        raw_dir = day_dir / f"raw-retry-{suffix}"
    if not complete_json(raw_dir / "coverage.json"):
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "collect_free_prestudy.py"),
                "--start",
                args.date,
                "--end",
                args.date,
                "--exit-end",
                args.date,
                "--one-minute-start",
                args.date,
                "--workers",
                str(args.workers),
                "--output",
                str(raw_dir),
            ]
        )

    raw_name = raw_dir.name
    analysis_dir = day_dir / f"analysis-{raw_name}"
    if not complete_json(analysis_dir / "result.json"):
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "analyze_free_prestudy.py"),
                "--input",
                str(raw_dir),
                "--output",
                str(analysis_dir),
                "--start",
                args.date,
                "--end",
                args.date,
                "--one-minute-start",
                args.date,
            ]
        )

    ablation_dir = day_dir / f"ablation-{raw_name}"
    if not complete_json(ablation_dir / "result.json"):
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "run_ablation_v1.py"),
                "--input",
                str(raw_dir),
                "--features",
                str(analysis_dir),
                "--output",
                str(ablation_dir),
            ]
        )

    exit_path = day_dir / f"exit-update-{raw_name}.json"
    if not complete_json(exit_path):
        run(
            [
                sys.executable,
                str(SCRIPT_DIR / "update_forward_exits.py"),
                "--root",
                str(root),
                "--current-date",
                args.date,
                "--current-bars",
                str(raw_dir / "bars_1m.parquet"),
                "--output",
                str(exit_path),
            ]
        )

    ablation = json.loads((ablation_dir / "result.json").read_text(encoding="utf-8"))
    exit_update = json.loads(exit_path.read_text(encoding="utf-8"))
    summary = {
        "date": args.date,
        "status": "COMPLETE",
        "raw_dir": str(raw_dir),
        "coverage": json.loads((raw_dir / "coverage.json").read_text(encoding="utf-8"))["counts"],
        "m0_1m": ablation["models"]["1m"]["M0"],
        "m4_1m": ablation["models"]["1m"]["M4_PRE1430_BREAKOUT"],
        "exit_update": exit_update,
    }
    manifest = day_dir / f"run-manifest-{dt.datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%H%M%S')}.json"
    manifest.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RESULT=" + json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
