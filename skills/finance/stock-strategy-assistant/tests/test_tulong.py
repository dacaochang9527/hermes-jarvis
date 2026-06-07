from datetime import date, timedelta

import pytest

from stock_assistant.strategy_tulong import (
    D3CandidateProfile,
    ACTIVE_POOL_CAP,
    MIN_ACTIVE_SAFETY_BUFFER,
    apply_d3_safety_adjustment,
    d3_pool_subtype,
    d3_safety_buffer,
)
from stock_assistant.models import DailyBar
from stock_assistant.strategy_tulong import (
    build_d3_watch_signal,
    estimate_d1_support,
    evaluate_d1_board,
    is_d1_first_board,
    is_d2_balanced_cross,
    is_d2_pullback,
    is_excluded_name,
    is_first_board_from_zt_row,
    is_main_board_10cm,
)


def bar(offset, open_, high, low, close, prev_close, volume=100, limit_up=11.0):
    return DailyBar(
        code="603912",
        name="佳力图",
        trade_date=date(2022, 12, 28) + timedelta(days=offset),
        open=open_, high=high, low=low, close=close, prev_close=prev_close,
        volume=volume, amount=volume * close, limit_up_price=limit_up,
    )


def d1_row(**overrides):
    row = {
        "代码": "603912",
        "名称": "佳力图",
        "所属行业": "通用设备",
        "涨跌幅": 10.02,
        "最新价": 10.98,
        "成交额": 320_000_000,
        "换手率": 8.5,
        "封板资金": 90_000_000,
        "首次封板时间": "093512",
        "最后封板时间": "095201",
        "炸板次数": 1,
        "涨停统计": "1/1",
        "连板数": 1,
    }
    row.update(overrides)
    return row


def test_d1_first_board_requires_today_limit_and_yesterday_not_limit():
    yesterday = bar(0, 9.8, 10.0, 9.6, 9.9, 9.8, limit_up=10.78)
    today = bar(1, 10.0, 11.0, 10.0, 10.98, 9.9, limit_up=11.0)
    assert is_d1_first_board(today, yesterday)


def test_d2_pullback_accepts_volume_between_two_and_three_when_other_conditions_pass():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 10.8, 11.3, 10.5, 10.9, 10.98, volume=250, limit_up=12.08)
    ok, reason = is_d2_pullback(d1, d2, estimate_d1_support(d1))
    assert ok, reason
    assert "2-3倍" in reason


def test_d2_pullback_accepts_strong_continuation_without_pullback():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 11.5, 12.08, 11.3, 12.08, 10.98, volume=180, limit_up=12.08)
    ok, reason = is_d2_pullback(d1, d2, estimate_d1_support(d1))
    assert ok, reason
    assert "强势延续" in reason


def test_d2_pullback_rejects_volume_more_than_three_times_d1():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 10.8, 11.3, 10.5, 10.9, 10.98, volume=320, limit_up=12.08)
    ok, reason = is_d2_pullback(d1, d2, estimate_d1_support(d1))
    assert not ok
    assert "超过3倍" in reason


def test_d2_pullback_rejects_excessive_volume_shrink():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 10.8, 11.3, 10.5, 10.9, 10.98, volume=50, limit_up=12.08)
    ok, reason = is_d2_pullback(d1, d2, estimate_d1_support(d1))
    assert not ok
    assert "缩量过弱" in reason


def test_d2_pullback_rejects_overlong_upper_shadow():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 10.8, 12.0, 10.5, 10.9, 10.98, volume=150, limit_up=12.08)
    ok, reason = is_d2_pullback(d1, d2, estimate_d1_support(d1))
    assert not ok
    assert "上引线太长" in reason


def test_d2_pullback_accepts_valid_washout_and_builds_d3_signal():
    d1 = bar(1, 10, 11, 10, 10.98, 9.9, volume=100, limit_up=11)
    d2 = bar(2, 10.7, 11.2, 10.4, 10.9, 10.98, volume=150, limit_up=12.08)
    support = estimate_d1_support(d1)
    ok, reason = is_d2_pullback(d1, d2, support)
    assert ok, reason
    signal = build_d3_watch_signal(d1, d2, support)
    assert signal.signal_type == "D3_WATCH_UNDERWATER"
    assert signal.trigger_price == d2.close
    assert signal.invalid_price == support
    assert "量能未超过2倍" not in signal.reason


def test_d2_balanced_cross_detects_small_body_relative_to_range():
    d2 = bar(2, 10.8, 11.3, 10.5, 10.9, 10.98, volume=150, limit_up=12.08)
    assert is_d2_balanced_cross(d2)


@pytest.mark.parametrize("code", ["600000", "601398", "603912", "605006", "000001", "001696", "002415", "003000"])
def test_d1_main_board_10cm_accepts_shenzhen_and_shanghai_main_board(code):
    assert is_main_board_10cm(code)


@pytest.mark.parametrize("code", ["300750", "301001", "688001", "689009", "833000", "430001", "920001"])
def test_d1_main_board_10cm_rejects_20cm_bse_and_non_main_board_prefixes(code):
    assert not is_main_board_10cm(code)


@pytest.mark.parametrize("name", ["ST佳力", "*ST天成", "退市海创", "佳力退"])
def test_d1_excluded_name_rejects_st_and_delisting_risk(name):
    assert is_excluded_name(name)


def test_d1_excluded_name_accepts_normal_name():
    assert not is_excluded_name("佳力图")


@pytest.mark.parametrize(
    "row",
    [
        d1_row(涨停统计="1/2", 连板数=0),
        d1_row(涨停统计="", 连板数=1),
        d1_row(涨停统计=None, 连板数="1"),
    ],
)
def test_first_board_from_zt_row_accepts_stat_starting_with_one_or_limit_boards_one(row):
    ok, reason = is_first_board_from_zt_row(row)
    assert ok, reason


@pytest.mark.parametrize(
    "row, reason_part",
    [
        (d1_row(代码="300750"), "20cm/北交所/非主板前缀"),
        (d1_row(名称="*ST佳力"), "ST/退市风险"),
        (d1_row(涨停统计="2/2", 连板数=2), "非首板"),
    ],
)
def test_evaluate_d1_board_rejects_with_readable_reason(row, reason_part):
    result = evaluate_d1_board(row)
    assert not result.passed
    assert reason_part in result.reject_reason


def test_evaluate_d1_board_passes_for_valid_d1_row():
    result = evaluate_d1_board(d1_row())
    assert result.passed
    assert result.reject_reason == ""


def d3_profile(**overrides):
    return D3CandidateProfile(
        score=float(overrides.get("score", 80.0)),
        trigger_price=float(overrides.get("trigger_price", 10.0)),
        invalid_price=float(overrides.get("invalid_price", 9.0)),
        zone_low=float(overrides.get("zone_low", 9.85)),
        zone_high=float(overrides.get("zone_high", 10.03)),
        d2_pullback=float(overrides.get("d2_pullback", 0.04)),
        flags=str(overrides.get("flags", "")),
    )


def test_d3_pool_subtype_routes_strong_continuation_to_radar_even_when_comfortable():
    assert d3_pool_subtype(d3_profile(score=88, flags="strong_continuation", d2_pullback=0.06)) == "radar"


def test_d3_pool_subtype_routes_thin_safety_buffer_to_radar():
    profile = d3_profile(score=88, invalid_price=9.7, zone_low=9.92, d2_pullback=0.06)

    assert d3_safety_buffer(profile) < MIN_ACTIVE_SAFETY_BUFFER
    assert d3_pool_subtype(profile) == "radar"


def test_d3_pool_subtype_keeps_comfortable_clean_candidate_active():
    assert d3_pool_subtype(d3_profile(score=78)) == "active"


def test_apply_d3_safety_adjustment_marks_thin_buffer():
    score, note, flags = apply_d3_safety_adjustment(80, "原note", "", zone_low=9.92, invalid_price=9.7)

    assert score == 72
    assert "不进active" in note
    assert "安全垫薄" in flags


def test_d3_active_pool_cap_is_six():
    assert ACTIVE_POOL_CAP == 6
