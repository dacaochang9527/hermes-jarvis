from datetime import datetime
from pathlib import Path
import importlib.util
import json
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tulong" / "runtime" / "preopen_rotate_watchlist.py"


def load_module():
    spec = importlib.util.spec_from_file_location("preopen_rotate_watchlist", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_timestamp_score_prefers_yyyymmdd_hhmmss_suffix(tmp_path):
    mod = load_module()
    older = tmp_path / "0529D3_watch_scan_20260529_214437.csv"
    newer = tmp_path / "0529D3_watch_scan_20260530_001500.csv"
    legacy = tmp_path / "0529D3_watch_scan_214437.csv"
    for path in (older, newer, legacy):
        path.write_text("code,name\n", encoding="utf-8")

    assert mod.timestamp_score(older)[0] == "20260529_214437"
    assert mod.timestamp_score(newer)[0] == "20260530_001500"
    assert mod.timestamp_score(legacy)[0] == ""
    assert sorted([older, newer], key=mod.timestamp_score, reverse=True)[0] == newer


def test_find_latest_source_uses_full_timestamp(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "WATCHLIST_DIR", tmp_path)
    active = tmp_path / "tulong_active_watchlist.csv"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)

    old = tmp_path / "0529D3_watch_scan_20260529_214437.csv"
    new = tmp_path / "0529D3_watch_scan_20260530_001500.csv"
    legacy = tmp_path / "0529D3_watch_scan_214437.csv"
    for path in (old, new, legacy, active):
        path.write_text("code,name\n", encoding="utf-8")

    found = mod.find_latest_source(datetime(2026, 5, 29, 8, 50), "D3", "watch")
    assert found == new


def test_find_sources_uses_hold_position_sources(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "WATCHLIST_DIR", tmp_path)
    active = tmp_path / "tulong_active_watchlist.csv"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)

    d3_watch = tmp_path / "0529D3_watch_scan_20260529_214437.csv"
    hold_watch = tmp_path / "HOLD_watch_manual_review_20260529_214437.csv"
    hold_position = tmp_path / "HOLD_position_rollover_20260529_214437.csv"
    for path in (d3_watch, hold_watch, hold_position, active):
        path.write_text("code,name\n", encoding="utf-8")

    sources = mod.find_sources(datetime(2026, 5, 29, 8, 50))
    assert d3_watch in sources
    assert hold_position in sources
    assert hold_watch not in sources


def test_find_sources_uses_latest_hold_position_regardless_of_date(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "WATCHLIST_DIR", tmp_path)
    active = tmp_path / "tulong_active_watchlist.csv"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)

    d3_watch = tmp_path / "0531D3_watch_scan_20260531_085000.csv"
    old_hold = tmp_path / "HOLD_position_rollover_20260528_214902.csv"
    new_hold = tmp_path / "HOLD_position_rollover_20260530_171700.csv"
    for path in (d3_watch, old_hold, new_hold, active):
        path.write_text("code,name\n", encoding="utf-8")

    # 切池在 0531；HOLD 持仓取最新快照(0530)，与当日日期前缀无关
    sources = mod.find_sources(datetime(2026, 5, 31, 8, 50))
    assert d3_watch in sources
    assert new_hold in sources
    assert old_hold not in sources


def test_normalize_source_rows_rejects_hold_watch_rows(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "WATCHLIST_DIR", tmp_path)
    source = tmp_path / "HOLD_watch_manual_review_20260529_214437.csv"
    source.write_text(
        "code,name,stage,pool_type,trigger_price,invalid_price,zone_low,zone_high\n"
        "600000,浦发银行,HOLD,watch,10,9,9.8,10.1\n",
        encoding="utf-8",
    )

    try:
        mod.normalize_source_rows(source)
    except RuntimeError as exc:
        assert "HOLD only accepts position" in str(exc)
    else:
        raise AssertionError("expected HOLD watch rows to be rejected")


def test_active_state_matches_exempts_hold_positions(monkeypatch, tmp_path):
    mod = load_module()
    active = tmp_path / "tulong_active_watchlist.csv"
    state = tmp_path / "state.json"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)
    monkeypatch.setattr(mod, "STATE_PATH", state)

    state.write_text(json.dumps({"watch_date": "2026-05-31"}), encoding="utf-8")
    active.write_text(
        "code,name,stage,pool_type\n"
        "600000,浦发银行,0531D3,watch\n"
        "600863,华能蒙电,HOLD,position\n",
        encoding="utf-8",
    )

    # watch 行带当日前缀、HOLD 持仓行无日期应被豁免 -> 视为已切池
    assert mod.active_state_matches(datetime(2026, 5, 31, 8, 50)) is True
