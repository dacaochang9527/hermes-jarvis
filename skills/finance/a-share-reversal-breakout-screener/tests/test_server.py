from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "server.py"
SPEC = importlib.util.spec_from_file_location("reversal_dashboard_server", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DashboardServerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_dir = self.root / "reports"
        self.cache_dir = self.root / "cache"
        self.report_dir.mkdir()
        self.cache_dir.mkdir()
        self.web_dir = Path(__file__).resolve().parents[1] / "web"

        fields = [
            "code", "name", "trade_date", "stage", "score", "heat", "trend",
            "style", "high_elasticity", "limit_up", "close", "pct_chg",
            "rsi6", "max_drawdown_pct", "breakout_ratio", "reasons", "risks",
            "secondary_score", "focus_tier", "industry", "industry_rank_pct",
            "rs20_benchmark_pct", "ma60", "ma120", "ma60_slope_10d_pct",
            "breakout_60d_ratio", "long_trend", "fundamental_status",
            "fundamental_hard_risk", "announcement_risk", "metadata_status",
        ]
        rows = []
        stages = ["早期", "确认", "观察", "过热"]
        for index, stage in enumerate(stages, start=1):
            rows.append({
                "code": f"60000{index}",
                "name": f"样本{index}",
                "trade_date": "2026-07-20",
                "stage": stage,
                "score": str(90 - index),
                "heat": "过热" if stage == "过热" else "正常",
                "trend": "完整多头",
                "style": "中盘",
                "high_elasticity": "True" if index == 1 else "False",
                "limit_up": "False",
                "close": str(10 + index),
                "pct_chg": str(index),
                "rsi6": "65",
                "max_drawdown_pct": "35",
                "breakout_ratio": "1.01",
                "reasons": "测试原因",
                "risks": "测试风险",
                "secondary_score": str(80 - index),
                "focus_tier": "核心观察" if index == 1 else "重点复核",
                "industry": "测试行业",
                "industry_rank_pct": "80",
                "rs20_benchmark_pct": "5",
                "ma60": "10",
                "ma120": "9",
                "ma60_slope_10d_pct": "1.2",
                "breakout_60d_ratio": "0.96",
                "long_trend": "长期修复",
                "fundamental_status": "正常",
                "fundamental_hard_risk": "False",
                "announcement_risk": "False",
                "metadata_status": "完整",
            })
        report = self.report_dir / "reversal_breakout_20260720_120000.csv"
        with report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

        bars = []
        for index in range(1, 141):
            bars.append({
                "trade_date": f"2026-06-{index:02d}",
                "open": float(index) - 0.2,
                "close": float(index),
                "high": float(index) + 0.5,
                "low": float(index) - 0.5,
                "volume": float(index * 1000),
                "amount": 0.0,
                "pct_chg": 0.0,
                "turnover": 0.0,
            })
        (self.cache_dir / "2026-07-20_600001.json").write_text(
            json.dumps(bars),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_report_store_preserves_all_four_groups(self):
        snapshot = MODULE.ReportStore(self.report_dir).load()
        self.assertEqual(snapshot.payload["total"], 4)
        self.assertEqual(snapshot.payload["counts"], {
            "早期": 1,
            "确认": 1,
            "观察": 1,
            "过热": 1,
        })
        early = snapshot.payload["groups"]["早期"][0]
        self.assertTrue(early["high_elasticity"])
        self.assertEqual(early["score"], 89)
        self.assertEqual(snapshot.payload["focus_counts"]["核心观察"], 1)
        self.assertEqual(snapshot.payload["industries"], ["测试行业"])
        self.assertFalse(early["announcement_risk"])

    def test_kline_store_adds_hover_fields_and_moving_averages(self):
        payload = MODULE.KlineStore(self.cache_dir).load("600001", 140)
        self.assertEqual(len(payload["bars"]), 140)
        latest = payload["bars"][-1]
        self.assertAlmostEqual(latest["ma5"], 138.0)
        self.assertAlmostEqual(latest["ma10"], 135.5)
        self.assertAlmostEqual(latest["ma20"], 130.5)
        self.assertAlmostEqual(latest["ma60"], 110.5)
        self.assertAlmostEqual(latest["ma120"], 80.5)
        self.assertIn("pct_chg", latest)
        self.assertIn("amplitude", latest)

    def test_http_service_is_read_only_and_serves_interactive_data(self):
        server = MODULE.create_server(
            "127.0.0.1",
            0,
            self.report_dir,
            self.cache_dir,
            self.web_dir,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(base + "/healthz", timeout=3) as response:
                health = json.load(response)
            self.assertTrue(health["ok"])
            self.assertEqual(health["total"], 4)

            with urlopen(base + "/api/groups", timeout=3) as response:
                groups = json.load(response)
            self.assertEqual(groups["counts"]["过热"], 1)

            with urlopen(base + "/api/kline?code=600001&limit=40", timeout=3) as response:
                kline = json.load(response)
            self.assertEqual(kline["bars"][-1]["close"], 140.0)

            with urlopen(base + "/", timeout=3) as response:
                html = response.read().decode("utf-8")
            self.assertIn("A股超跌反转日K看板", html)
            self.assertIn("largeChart", html)
            self.assertIn("heatFilter", html)
            self.assertIn("trendFilter", html)
            self.assertIn("styleFilter", html)
            self.assertIn("minScoreFilter", html)
            self.assertIn("resetFilters", html)
            self.assertIn("presetSelect", html)
            self.assertIn("focusFilter", html)
            self.assertIn("industryFilter", html)
            self.assertIn("fundamentalFilter", html)
            self.assertIn("minRs20Filter", html)

            request = Request(base + "/api/groups", data=b"{}", method="POST")
            with self.assertRaises(HTTPError) as error:
                urlopen(request, timeout=3)
            self.assertEqual(error.exception.code, 405)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
