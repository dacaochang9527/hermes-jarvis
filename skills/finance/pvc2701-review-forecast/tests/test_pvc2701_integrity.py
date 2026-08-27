from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import pvc2701_adapter


TZ = ZoneInfo("Asia/Shanghai")


class Pvc2701IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generator = pvc2701_adapter.load_generator()
        cls.intraday = pvc2701_adapter.load_intraday()

    def bar(self, hhmm: str, open_: int, high: int, low: int, close: int):
        return self.generator.Bar(
            datetime.strptime(f"2026-08-27 {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ),
            open_,
            high,
            low,
            close,
            1,
            1,
        )

    def test_future_labelled_bar_is_excluded(self) -> None:
        self.intraday._pvc2701_quote_cutoff = datetime(2026, 8, 27, 10, 30, 24, tzinfo=TZ)
        rows = [
            self.bar("10:15", 4449, 4451, 4445, 4451),
            self.bar("10:33", 4448, 4451, 4440, 4441),
        ]
        filtered = self.intraday.completed_session_rows(rows, date(2026, 8, 27), "morning")
        self.assertEqual([row.dt.strftime("%H:%M") for row in filtered], ["10:15"])

    def test_state_handoff_provides_real_entry_anchors(self) -> None:
        report = SKILL_DIR / "reports" / "pvc2701_20260827_morning_preopen_review_forecast.md"
        scenarios = self.generator.extract_prior_scenarios(report)
        by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}
        self.assertEqual(by_id["A"]["entry_levels"], [4460.0, 4470.0])
        self.assertEqual(by_id["B"]["entry_levels"], [4435.0])
        self.assertEqual(by_id["D"]["entry_levels"], [4445.0])

    def test_intrabar_low_does_not_trigger_breakdown_plan(self) -> None:
        scenario = {
            "scenario_id": "B",
            "name": "方案 B：支撑跌破回吐空",
            "direction": "short",
            "entry_levels": [4435.0],
            "invalidation_levels": [4460.0],
        }
        rows = [
            self.bar("10:33", 4448, 4451, 4440, 4449),
            self.bar("10:36", 4455, 4456, 4449, 4455),
        ]
        status, _, _ = self.generator.evaluate_scenario(scenario, rows, {})
        self.assertEqual(status, "未触发")

    def test_rejection_requires_touch_then_completed_weak_close(self) -> None:
        scenario = {
            "scenario_id": "A",
            "name": "方案 A：近端压力承压空",
            "direction": "short",
            "entry_levels": [4460.0, 4470.0],
            "invalidation_levels": [4490.0],
        }
        rows = [
            self.bar("09:03", 4456, 4464, 4454, 4460),
            self.bar("09:06", 4459, 4461, 4451, 4452),
        ]
        status, _, _ = self.generator.evaluate_scenario(scenario, rows, {})
        self.assertEqual(status, "触发且确认")


if __name__ == "__main__":
    unittest.main()
