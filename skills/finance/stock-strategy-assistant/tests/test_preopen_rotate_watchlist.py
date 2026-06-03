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


def test_find_sources_uses_only_today_d3_watch(monkeypatch, tmp_path):
    mod = load_module()
    monkeypatch.setattr(mod, "WATCHLIST_DIR", tmp_path)
    active = tmp_path / "tulong_active_watchlist.csv"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)

    d3_watch = tmp_path / "0529D3_watch_scan_20260529_214437.csv"
    hold_position = tmp_path / "HOLD_position_rollover_20260529_214437.csv"
    for path in (d3_watch, hold_position, active):
        path.write_text("code,name\n", encoding="utf-8")

    sources = mod.find_sources(datetime(2026, 5, 29, 8, 50))
    assert sources == [d3_watch]


def test_derive_open_positions_from_trades_uses_fifo_and_excludes_closed(monkeypatch, tmp_path):
    mod = load_module()
    trades = tmp_path / "tulong_trades.csv"
    monkeypatch.setattr(mod, "TRADES_PATH", trades)
    monkeypatch.setattr(mod, "PROJECT", tmp_path)
    trades.write_text(
        "trade_date,session_label,action,code,name,quantity,price,amount,fee,net_amount,position_ref,note,d3_watch\n"
        "2026-06-02,0602D3,buy,600001,测试A,100,10.000,1000,5,-1005,0602D3,,yes\n"
        "2026-06-03,0603D3,sell,600001,测试A,40,11.000,440,5,435,0602D3,,yes\n"
        "2026-06-03,0603D3,buy,002001,测试B,200,5.000,1000,5,-1005,0603D3,,yes\n"
        "2026-06-03,0603D3,buy,600002,测试C,100,8.000,800,5,-805,0603D3,,yes\n"
        "2026-06-03,0603D3,sell,600002,测试C,100,8.500,850,5,845,0603D3,,yes\n",
        encoding="utf-8",
    )

    rows = mod.derive_open_positions_from_trades(datetime(2026, 6, 3, 8, 50))
    by_code = {row["code"]: row for row in rows}

    assert set(by_code) == {"600001", "002001"}
    assert by_code["600001"]["quantity"] == "60"
    assert by_code["600001"]["sellable_quantity"] == "60"
    assert by_code["600001"]["entry_stage"] == "0602D3"
    assert by_code["002001"]["quantity"] == "200"
    assert by_code["002001"]["sellable_quantity"] == "0"
    assert by_code["002001"]["source_file"] == "tulong_trades.csv"


def test_write_active_watchlist_appends_trade_derived_hold(monkeypatch, tmp_path):
    mod = load_module()
    active = tmp_path / "tulong_active_watchlist.csv"
    state = tmp_path / "state.json"
    trades = tmp_path / "tulong_trades.csv"
    monkeypatch.setattr(mod, "ACTIVE_WATCHLIST", active)
    monkeypatch.setattr(mod, "LEGACY_ACTIVE_D3", tmp_path / "tulong_d3.csv")
    monkeypatch.setattr(mod, "TRADES_PATH", trades)
    monkeypatch.setattr(mod, "PROJECT", tmp_path)
    monkeypatch.setattr(mod, "STATE_PATH", state)

    source = tmp_path / "0603D3_watch_scan_20260603_080000.csv"
    source.write_text(
        "code,name,industry,stage,pool_type,trigger_price,invalid_price,zone_low,zone_high\n"
        "600000,浦发银行,银行,0603D3,watch,10,9,9.8,10.1\n",
        encoding="utf-8",
    )
    trades.write_text(
        "trade_date,session_label,action,code,name,quantity,price,amount,fee,net_amount,position_ref,note,d3_watch\n"
        "2026-06-02,0602D3,buy,000001,平安银行,100,12.000,1200,5,-1205,0602D3,,yes\n",
        encoding="utf-8",
    )

    count, filtered, source_names, stages, pool_types = mod.write_active_watchlist([source], datetime(2026, 6, 3, 8, 50))

    assert count == 2
    assert filtered == []
    assert source_names == [source.name, "tulong_trades.csv"]
    assert stages == ["0603D3", "HOLD"]
    assert pool_types == ["position", "watch"]
    content = active.read_text(encoding="utf-8")
    assert "600000" in content
    assert "000001" in content
    assert "HOLD" in content
    assert "position_status" not in content.splitlines()[0]


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

    assert mod.active_state_matches(datetime(2026, 5, 31, 8, 50)) is True
