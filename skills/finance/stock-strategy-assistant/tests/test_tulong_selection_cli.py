from datetime import date
from pathlib import Path
import importlib.util
from types import SimpleNamespace


import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tulong" / "selection" / "generate_d3_candidates.py"


def load_module():
    spec = importlib.util.spec_from_file_location("generate_d3_candidates", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_args_accepts_explicit_dates_and_label():
    mod = load_module()
    args = mod.parse_args([
        "--d1-date", "20260527",
        "--d2-date", "20260528",
        "--d3-label", "0529D3",
        "--timestamp", "214437",
        "--max-report", "20",
    ])

    assert args.d1_date == date(2026, 5, 27)
    assert args.d2_date == date(2026, 5, 28)
    assert args.d3_label == "0529D3"
    assert args.timestamp == "214437"
    assert args.max_report == 20


def test_build_output_paths_include_label_and_timestamp(tmp_path):
    mod = load_module()
    paths = mod.build_output_paths(tmp_path, "0529D3", "20260529_214437")

    assert paths.report == tmp_path / "reports" / "daily" / "0529D3_candidate_scan_20260529_214437.md"
    assert paths.csv == tmp_path / "data" / "watchlists" / "0529D3_watch_scan_20260529_214437.csv"


def test_default_timestamp_includes_yyyymmdd_prefix():
    mod = load_module()
    args = mod.parse_args([
        "--d1-date", "20260527",
        "--d2-date", "20260528",
        "--d3-date", "20260529",
    ])

    assert len(args.timestamp) == len("20260529_214437")
    assert args.timestamp[8] == "_"
    assert args.timestamp[:8].isdigit()
    assert args.timestamp[9:].isdigit()


def test_infer_label_from_d3_date_when_label_omitted():
    mod = load_module()
    args = mod.parse_args([
        "--d1-date", "20260527",
        "--d2-date", "20260528",
        "--d3-date", "20260529",
    ])

    assert args.d3_label == "0529D3"


def candidate(**overrides):
    base = dict(
        code="600000", score=80, flags="", trigger_price=10.0, invalid_price=9.0,
        zone_low=9.85, zone_high=10.03, d2_pullback=0.04,
        industry="通用设备", d2_pct=1.0, sector_strength_score=0.0, sector_strength_note="",
        note="原note",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_auto_narrow_prefers_candidates_without_severe_flags():
    mod = load_module()
    clean = candidate(code="600000", score=80, flags="")
    risky = candidate(code="600001", score=99, flags="高开低走")
    selected, narrowed_out = mod.auto_narrow_candidates([risky, clean], 1)

    assert selected == [clean]
    assert narrowed_out == [risky]


def test_strong_continuation_without_entry_comfort_routes_to_radar():
    mod = load_module()
    strong_far = candidate(score=88, flags="strong_continuation", zone_low=10.15, zone_high=10.25, d2_pullback=0.005)

    assert mod.pool_subtype_for(strong_far) == "radar"


def test_strong_continuation_routes_to_radar_even_when_comfortable():
    mod = load_module()
    strong_comfortable = candidate(score=88, flags="strong_continuation", zone_low=9.88, zone_high=10.03, d2_pullback=0.06)

    assert mod.pool_subtype_for(strong_comfortable) == "radar"


def test_thin_safety_buffer_routes_to_radar():
    mod = load_module()
    thin_buffer = candidate(score=88, flags="", trigger_price=10.0, invalid_price=9.7, zone_low=9.92, zone_high=10.03, d2_pullback=0.06)

    assert mod.pool_subtype_for(thin_buffer) == "radar"


def test_comfortable_candidate_routes_to_active():
    mod = load_module()
    comfortable = candidate(score=78, flags="", zone_low=9.88, zone_high=10.03, d2_pullback=0.04)

    assert mod.pool_subtype_for(comfortable) == "active"


def test_hard_risk_flags_route_to_radar_even_with_high_score():
    mod = load_module()
    crowded = candidate(score=92, flags="成交拥挤；radar_only", zone_low=9.88, zone_high=10.03, d2_pullback=0.04)

    assert mod.pool_subtype_for(crowded) == "radar"


def test_active_pool_cap_is_compressed_to_six():
    mod = load_module()

    assert mod.ACTIVE_POOL_CAP == 6


def test_apply_sector_strength_scores_adjusts_score_and_note():
    mod = load_module()
    first = candidate(code="600001", score=70, industry="化学原料", d2_pct=6.0)
    second = candidate(code="600002", score=70, industry="化学原料", d2_pct=5.0)
    weak = candidate(code="600003", score=70, industry="专用设备", d2_pct=-3.0)

    mod.apply_sector_strength_scores([first, second, weak])

    assert first.sector_strength_score == 8.0
    assert first.score == 78.0
    assert "板块强势" not in first.flags
    assert "化学原料同批候选2只" in first.note
    assert weak.sector_strength_score == -4.0
    assert weak.score == 66.0
    assert "板块弱势" in weak.flags


def test_watch_csv_keeps_sector_strength_fields():
    mod = load_module()
    paths = mod.build_output_paths(Path("/tmp/project"), "0615D3", "20260615_002133")

    fields = ["code","name","industry","stage","pool_type","pool_subtype","source_file","trigger_price","invalid_price","zone_low","zone_high","rank","score","sector_strength_score","sector_strength_note","note"]

    assert "sector_strength_score" in fields
    assert paths.csv.name == "0615D3_watch_scan_20260615_002133.csv"
