from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "screen.py"
SPEC = importlib.util.spec_from_file_location("reversal_screen", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ScreenRuleTest(unittest.TestCase):
    def test_limit_up_is_not_part_of_score(self):
        self.assertNotIn("limit_up", MODULE._score_breakout.__code__.co_varnames)
        self.assertEqual(MODULE._score_breakout(1.01), 20)
        self.assertEqual(MODULE._score_breakout(0.99), 14)

    def test_style_does_not_block_shape(self):
        small = MODULE.Spot("600001", "示例", 8, 3, 3e8, 5, 20, 8e9, 6e9, 8.1, 7.5, 7.6, 7.7)
        large = MODULE.Spot("600002", "示例", 30, 3, 30e8, 1, 10, 2e12, 1e12, 31, 29, 29.5, 29)
        self.assertEqual(MODULE.classify_style(small), ("中盘", True))
        self.assertEqual(MODULE.classify_style(large), ("超大盘", False))

    def test_heat_thresholds_are_independent(self):
        self.assertEqual(MODULE._score_drawdown(35), 15)
        self.assertEqual(MODULE._score_drawdown(25), 10)
        self.assertEqual(MODULE._score_base(15), 15)
        self.assertEqual(MODULE._score_volume(1.5), 10)

    def test_cn_rsi_bounds(self):
        rising = MODULE.rsi_cn([float(i) for i in range(1, 30)], 6)
        falling = MODULE.rsi_cn([float(i) for i in range(30, 1, -1)], 6)
        self.assertGreaterEqual(rising, 99)
        self.assertLessEqual(falling, 1)

    def test_mainboard_and_st_filter(self):
        good = MODULE.Spot("600001", "正常股份", 8, 1, 3e8, 2, 20, 1e10, 8e9, 8.1, 7.8, 7.9, 7.9)
        st = MODULE.Spot("600002", "ST示例", 8, 1, 3e8, 2, 20, 1e10, 8e9, 8.1, 7.8, 7.9, 7.9)
        star = MODULE.Spot("688001", "科创示例", 30, 1, 3e8, 2, 20, 1e10, 8e9, 31, 29, 29.5, 29)
        self.assertTrue(MODULE.is_eligible_spot(good, 2e8))
        self.assertFalse(MODULE.is_eligible_spot(st, 2e8))
        self.assertFalse(MODULE.is_eligible_spot(star, 2e8))

    def test_long_cycle_and_volume_structure_classification(self):
        self.assertEqual(MODULE.classify_long_trend(12, 11, 10, 1, 0.2), "长短共振")
        self.assertEqual(MODULE.classify_long_trend(12, 11, 13, 0.5, -1), "MA60转强")
        self.assertEqual(MODULE.classify_long_trend(10, 10.2, 12, -0.5, -1), "长期修复")
        self.assertEqual(MODULE.classify_long_trend(8, 10, 12, -2, -1), "长压未解")
        self.assertEqual(MODULE.classify_volume_structure(0.85, 1.5, 80), "缩量后放量")
        self.assertEqual(MODULE.classify_volume_structure(1.1, 5, 30), "量价分歧")

    def test_fundamental_and_announcement_risk_are_explicit(self):
        healthy = MODULE.classify_fundamentals({
            "REPORT_DATE_NAME": "2026一季报",
            "ORG_TYPE": "通用",
            "PARENTNETPROFIT": 10,
            "KCFJCXSYJLR": 8,
            "TOTALOPERATEREVETZ": 12,
            "KCFJCXSYJLRTZ": 15,
            "NETCASH_OPERATE_PK": 5e8,
            "ZCFZL": 45,
            "ROEJQ": 4,
        }, 20)
        self.assertEqual(healthy["status"], "正常")
        self.assertFalse(healthy["hard_risk"])

        risky = MODULE.classify_fundamentals({
            "REPORT_DATE_NAME": "2026一季报",
            "ORG_TYPE": "通用",
            "PARENTNETPROFIT": -1,
            "KCFJCXSYJLR": -2,
            "ROEJQ": -1,
        }, -10)
        self.assertEqual(risky["status"], "风险")
        self.assertTrue(risky["hard_risk"])

        flagged, note = MODULE.detect_announcement_risk([
            {"notice_date": "2026-07-10", "title": "关于股东减持计划的公告"},
            {"notice_date": "2026-07-11", "title": "关于股份解除质押的公告"},
        ], as_of=date(2026, 7, 21))
        self.assertTrue(flagged)
        self.assertIn("减持计划", note)
        self.assertNotIn("解除质押", note)

    def test_industry_strength_uses_liquid_universe_members(self):
        def bars(multiplier):
            return [
                MODULE.Bar(str(index), value, value, value, value, 100, 0, 0, 0)
                for index, value in enumerate(
                    [10 + multiplier * index / 60 for index in range(61)]
                )
            ]

        spots = []
        histories = {}
        for industry, multiplier in (("强行业", 0.2), ("弱行业", -0.05)):
            for index in range(3):
                code = f"600{len(spots):03d}"
                spots.append(MODULE.Spot(
                    code, "样本", 10, 1, 3e8, 2, 20, 1e10, 8e9,
                    10, 9, 9.5, 9.5, industry,
                ))
                histories[code] = bars(multiplier)
        stats = MODULE.build_industry_stats(spots, histories)
        self.assertEqual(stats["强行业"].rank_pct, 100)
        self.assertEqual(stats["弱行业"].rank_pct, 0)
        self.assertEqual(stats["强行业"].member_count, 3)


if __name__ == "__main__":
    unittest.main()
