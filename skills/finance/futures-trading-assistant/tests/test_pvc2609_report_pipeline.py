from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import pvc2609_generate_session_report as generator
import pvc2609_preopen_review_publish as publisher
import publish_feishu_markdown_doc as feishu_publisher


FIXTURE = Path(__file__).parent / "fixtures" / "pvc2609_20260713.json"


def load_fixture() -> tuple[dict, list[generator.Bar], list[generator.Bar], list[generator.Bar]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    quote = dict(payload["quote"])
    quote["quote_dt"] = datetime.fromisoformat(quote["quote_dt"])

    def bars(key: str) -> list[generator.Bar]:
        return [
            generator.Bar(generator.parse_dt(row[0]), *map(float, row[1:]))
            for row in payload[key]
        ]

    return quote, bars("daily"), bars("3m"), bars("15m")


def prior_report_text() -> str:
    return """# prior

## 12. 午盘情景概率表

| 剧本 | 触发条件 | 预期路径 | 估计概率 | 关键证据 | 失效条件 |
|---|---|---|---:|---|---|
| A：4585-4600 承压回落 | 反抽到压力区后3m转弱，不能站稳 `4610` | 回落 | 40% | 压力 | 站稳 `4610` |
| B：4610 修复延续 | 站稳确认位，并回踩 `4585-4600` 不破 | 上行 | 25% | 修复 | 跌回 `4520` |
| C：跌回 `4510` 后修复失败 | 跌破支撑，反抽 `4520` 不过 | 下行 | 25% | 失守 | 重新站回 `4530` |
| D：`4515` 再破新低 | 跌破本阶段低点后反抽不过 | 下行 | 10% | 破位 | 跌破后快速收回 `4510` |

```text
STATE_HANDOFF
contract: PVC2609
```
"""


class GeneratorRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quote, self.daily, self.rows3, self.rows15 = load_fixture()

    def test_completed_day_quote_updates_daily_and_ma5(self) -> None:
        summary = generator.summarize_bars(self.rows3)
        rows = generator.apply_realtime_session_daily(
            self.daily, self.quote, summary, date(2026, 7, 13), "day", date(2026, 7, 13)
        )
        self.assertEqual(rows[-1].dt.date(), date(2026, 7, 13))
        self.assertEqual(rows[-1].close, 4488)
        self.assertAlmostEqual(generator.moving_average(rows, 5), 4490.4)

    def test_close_near_low_is_bearish_not_range(self) -> None:
        summary = generator.summarize_bars(self.rows3)
        rows = generator.apply_realtime_session_daily(
            self.daily, self.quote, summary, date(2026, 7, 13), "day", date(2026, 7, 13)
        )
        self.assertEqual(generator.infer_bias(summary, rows, self.rows3, self.rows15), "bearish")

    def test_levels_are_near_core_and_far(self) -> None:
        summary = generator.summarize_bars(self.rows3)
        plan = generator.build_plan_levels(generator.derive_levels(summary, self.quote, self.rows15))
        self.assertEqual((plan["pressure_low"], plan["pressure_high"]), (4490, 4500))
        self.assertEqual((plan["core_pressure_low"], plan["core_pressure_high"]), (4510, 4520))
        self.assertEqual((plan["far_pressure_low"], plan["far_pressure_high"]), (4585, 4595))

    def test_prior_scenarios_follow_trigger_then_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prior = Path(tmp) / "prior.md"
            prior.write_text(prior_report_text(), encoding="utf-8")
            scenarios = generator.extract_prior_scenarios(prior)
        summary = generator.summarize_bars(self.rows3)
        statuses = [generator.evaluate_scenario(item, self.rows3, summary)[0] for item in scenarios]
        self.assertEqual(statuses, ["触发且确认", "未触发", "触发且确认", "触发且确认"])

    def test_generated_report_is_consistent_and_machine_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "prior.md"
            prior.write_text(prior_report_text(), encoding="utf-8")
            output = root / "report.md"
            args = argparse.Namespace(
                date=date(2026, 7, 13), session="day", next_session="night",
                next_date=date(2026, 7, 13), output=output, overwrite=True, update_levels=True,
            )
            klines = {3: self.rows3, 15: self.rows15, 30: self.rows15, 60: self.rows15, 120: self.rows15}
            markdown, prediction = generator.build_report(args, self.quote, klines, self.daily, prior)
            spec = publisher.TARGETS["night"]
            publisher.validate_report_bundle(markdown, prediction, date(2026, 7, 13), spec, prior)
            prices = [item["price"] for item in prediction["levels"]]
            self.assertEqual(len(prices), len(set(prices)))
        self.assertIn("MA5/10/20=4490/", markdown)
        self.assertIn("| 近端压力 | 4490-4500 |", markdown)
        self.assertIn("| 核心压力 | 4510-4520 |", markdown)
        self.assertIn("| 远端强反抽压力 | 4585-4595 |", markdown)
        self.assertIn("| 方案 B：4610 修复延续", markdown)
        self.assertIn("| 未触发 | 价格未到达前序触发位 4610", markdown)

    def test_all_three_targets_pass_offline_dry_run(self) -> None:
        night_rows = [
            generator.Bar(generator.parse_dt("2026-07-13 21:03:00"), 4490, 4500, 4480, 4495, 1000, 1226000),
            generator.Bar(generator.parse_dt("2026-07-13 22:57:00"), 4495, 4510, 4485, 4505, 1200, 1227000),
        ]
        cases = [
            (publisher.TARGETS["afternoon"], self.rows3, self.rows15, self.quote, date(2026, 7, 13)),
            (publisher.TARGETS["night"], self.rows3, self.rows15, self.quote, date(2026, 7, 13)),
            (publisher.TARGETS["morning"], night_rows, night_rows, {
                **self.quote,
                "open": 4490, "high": 4510, "low": 4480, "last": 4505,
                "quote_dt": datetime.fromisoformat("2026-07-13T22:59:00+08:00"),
            }, date(2026, 7, 14)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "prior.md"
            prior.write_text(prior_report_text(), encoding="utf-8")
            for spec, rows3, rows15, quote, next_date in cases:
                with self.subTest(target=spec.target):
                    args = argparse.Namespace(
                        date=date(2026, 7, 13), session=spec.review_session,
                        next_session=spec.next_session, next_date=next_date,
                        output=root / f"{spec.target}.md", overwrite=True, update_levels=False,
                    )
                    klines = {3: rows3, 15: rows15, 30: rows15, 60: rows15, 120: rows15}
                    markdown, prediction = generator.build_report(args, quote, klines, self.daily, prior)
                    publisher.validate_report_bundle(markdown, prediction, date(2026, 7, 13), spec, prior)


class PublisherGateTests(unittest.TestCase):
    def test_bad_short_target_is_rejected(self) -> None:
        quality = {
            "review_date": "2026-07-13", "quote_dt": "2026-07-13T15:04:28+08:00",
            "daily_date": "2026-07-13", "bias": "bearish",
            "session": {"open": 4566, "high": 4590, "low": 4487, "close": 4488},
            "plan": {
                "pressure_low": 4490, "pressure_high": 4500, "core_pressure_low": 4510,
                "core_pressure_high": 4520, "far_pressure_low": 4585, "far_pressure_high": 4595,
                "near_distance_limit": 36,
            },
            "scenarios": [
                {"scenario_id": "A", "direction": "short", "entry_low": 4490, "entry_high": 4500,
                 "stop_anchor": 4520, "target1_anchor": 4505, "target2_anchor": 4470},
                {"scenario_id": "B", "direction": "observe"}, {"scenario_id": "C", "direction": "observe"},
                {"scenario_id": "D", "direction": "observe"}, {"scenario_id": "E", "direction": "observe"},
            ],
        }
        markdown = "\n".join([f"## {number}. 方案 {scenario_id}" for number, scenario_id in ((13, "A"), (14, "B"), (15, "C"), (16, "D"))])
        with tempfile.TemporaryDirectory() as tmp:
            prior = Path(tmp) / "prior.md"
            prior.write_text("prior", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "止损/止盈方向错误"):
                publisher.validate_report_bundle(markdown, {"_quality": quality}, date(2026, 7, 13), publisher.TARGETS["night"], prior)

    def test_validation_failure_does_not_write_report_or_levels(self) -> None:
        quote, daily, rows3, rows15 = load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "report.md"
            levels = root / "latest_prediction_levels.json"
            with patch.object(generator, "fetch_text", return_value=""), \
                 patch.object(generator, "parse_quote", return_value=quote), \
                 patch.object(generator, "fetch_klines", side_effect=lambda minutes: rows3 if minutes == 3 else rows15), \
                 patch.object(generator, "fetch_daily", return_value=daily), \
                 patch.object(generator, "find_prior_report", return_value=None), \
                 patch.object(generator, "PREDICTION_LEVELS_PATH", levels), \
                 patch.object(generator, "RUNTIME_DIR", root):
                with self.assertRaisesRegex(RuntimeError, "前序正式计划"):
                    publisher.generate_report(date(2026, 7, 13), date(2026, 7, 13), publisher.TARGETS["night"], output, True)
            self.assertFalse(output.exists())
            self.assertFalse(levels.exists())

    def test_publish_failure_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            report.write_text("# report", encoding="utf-8")
            failed = SimpleNamespace(returncode=1, stdout="", stderr="network failed")
            with patch.object(publisher.subprocess, "run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "network failed"):
                    publisher.publish_report(report, "title", dry_run=False)

    def test_empty_online_raw_content_blocks_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.md"
            report.write_text("# report\n\nbody", encoding="utf-8")

            def fake_api(method: str, path: str, token: str | None = None, **kwargs):
                if path == "/open-apis/docx/v1/documents":
                    return {"code": 0, "data": {"document": {"document_id": "doc123"}}}
                if path.endswith("/blocks/convert"):
                    return {"code": 0, "data": {"first_level_block_ids": ["b1"], "blocks": [{"block_id": "b1"}]}}
                if "/descendant" in path:
                    return {"code": 0, "data": {}}
                if "/permissions/" in path:
                    return {"code": 0, "data": {"permission_public": {}}}
                if "/metas/batch_query" in path:
                    return {"code": 0, "data": {"metas": [{"url": "https://example.test/doc", "title": "report"}]}}
                if path.endswith("/raw_content"):
                    return {"code": 0, "data": {"content": ""}}
                raise AssertionError(path)

            with patch.object(feishu_publisher, "get_tenant_token", return_value="token"), \
                 patch.object(feishu_publisher, "api_request", side_effect=fake_api):
                with self.assertRaisesRegex(feishu_publisher.PublishError, "empty document"):
                    feishu_publisher.publish(report, "title", None, no_patch=False)
            self.assertNotIn("飞书在线文档", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
