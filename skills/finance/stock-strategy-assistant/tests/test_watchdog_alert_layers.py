from datetime import datetime
from pathlib import Path
import importlib.util
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tulong" / "runtime" / "watchdog.py"


def load_module(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("tulong_watchdog", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "EVENTS_JSONL_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(module, "SNAPSHOTS_CSV_PATH", tmp_path / "snapshots.csv")
    return module


def watch_item():
    return {
        "code": "600000",
        "name": "测试银行",
        "industry": "银行",
        "stage": "0604D3",
        "pool_type": "watch",
        "trigger_price": 10.0,
        "invalid_price": 9.0,
        "zone_low": 9.8,
        "zone_high": 10.03,
    }


def quote(price, last_close=10.0, high=None):
    high = price if high is None else high
    return {
        "code": "600000",
        "name": "测试银行",
        "price": price,
        "pct": (price / last_close - 1) * 100,
        "open": last_close,
        "high": high,
        "low": price,
        "prev_close": last_close,
        "amount": 123_000_000,
        "volume": 10_000,
        "ts": "2026-06-04 10:00:00",
    }


def test_underwater_static_is_local_only(monkeypatch, tmp_path):
    mod = load_module(monkeypatch, tmp_path)
    state = {"last_prices": {}, "alert_statuses": {}}

    alerts = mod.build_alerts(
        datetime(2026, 6, 4, 10, 0),
        {"600000": quote(9.7)},
        state,
        [watch_item()],
    )

    assert alerts == []
    assert state["alert_statuses"]["600000"] == "underwater"
    assert '"event": "underwater"' in (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert '"push": false' in (tmp_path / "events.jsonl").read_text(encoding="utf-8")


def test_entry_zone_pushes_once_until_status_changes(monkeypatch, tmp_path):
    mod = load_module(monkeypatch, tmp_path)
    state = {"last_prices": {}, "alert_statuses": {}}
    item = watch_item()

    first = mod.build_alerts(datetime(2026, 6, 4, 10, 0), {"600000": quote(9.9)}, state, [item])
    repeat = mod.build_alerts(datetime(2026, 6, 4, 10, 1), {"600000": quote(9.9)}, state, [item])

    assert [alert["event"] for alert in first] == ["entry_zone"]
    assert repeat == []


def test_recover_trigger_pushes_after_underwater(monkeypatch, tmp_path):
    mod = load_module(monkeypatch, tmp_path)
    state = {"last_prices": {"600000": 9.7}, "alert_statuses": {"600000": "underwater"}}

    alerts = mod.build_alerts(
        datetime(2026, 6, 4, 10, 5),
        {"600000": quote(10.05, last_close=10.0)},
        state,
        [watch_item()],
    )

    assert [alert["event"] for alert in alerts] == ["recover_trigger"]
    assert state["alert_statuses"]["600000"] == "recover_trigger"


def test_observe_resets_status_so_entry_zone_can_push_again(monkeypatch, tmp_path):
    mod = load_module(monkeypatch, tmp_path)
    state = {"last_prices": {"600000": 9.9}, "alert_statuses": {"600000": "entry_zone"}}
    item = watch_item()

    observe = mod.build_alerts(datetime(2026, 6, 4, 10, 2), {"600000": quote(10.2)}, state, [item])
    again = mod.build_alerts(datetime(2026, 6, 4, 10, 3), {"600000": quote(9.9)}, state, [item])

    assert observe == []
    assert [alert["event"] for alert in again] == ["entry_zone"]
