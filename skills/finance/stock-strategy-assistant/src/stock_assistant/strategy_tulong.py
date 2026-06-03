from __future__ import annotations

from dataclasses import dataclass

from .indicators import is_limit_up
from .models import DailyBar, StrategySignal

MAIN_BOARD_10CM_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
EXCLUDED_NAME_PARTS = ("ST", "*ST", "退")


@dataclass(frozen=True)
class D1Evaluation:
    passed: bool
    reject_reason: str = ""


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def hhmm_to_int(value) -> int:
    text = str(value).strip()
    if not text or text.lower() == "nan" or text == "None":
        return 240000
    try:
        return int(text)
    except ValueError:
        return 240000


def is_main_board_10cm(code: str) -> bool:
    normalized = str(code).strip().zfill(6)
    return normalized.startswith(MAIN_BOARD_10CM_PREFIXES)


def is_excluded_name(name: str) -> bool:
    text = str(name).upper()
    return any(part.upper() in text for part in EXCLUDED_NAME_PARTS)


def is_first_board_from_zt_row(row) -> tuple[bool, str]:
    stat = str(row.get("涨停统计", "") or "")
    limit_boards = safe_float(row.get("连板数"))
    if stat.startswith("1/") or limit_boards == 1:
        return True, ""
    return False, f"非首板({stat},连板{limit_boards:g})"


def evaluate_d1_board(row) -> D1Evaluation:
    code = str(row.get("代码", "")).zfill(6)
    name = str(row.get("名称", ""))
    reasons: list[str] = []

    if not is_main_board_10cm(code):
        reasons.append("20cm/北交所/非主板前缀")
    if is_excluded_name(name):
        reasons.append("ST/退市风险")

    first_board, first_board_reason = is_first_board_from_zt_row(row)
    if not first_board:
        reasons.append(first_board_reason)

    if reasons:
        return D1Evaluation(False, "；".join(reasons))
    return D1Evaluation(True)


def estimate_d1_support(d1: DailyBar, recent_platform_high: float | None = None) -> float:
    candidates = [d1.open, d1.prev_close]
    if recent_platform_high is not None:
        candidates.append(recent_platform_high)
    return max(candidates)


def is_d1_first_board(today: DailyBar, yesterday: DailyBar) -> bool:
    return (
        is_limit_up(today.close, today.limit_up_price)
        and not is_limit_up(yesterday.close, yesterday.limit_up_price)
        and today.low < today.limit_up_price * 0.98 if today.limit_up_price else False
    )


def is_d2_strong_continuation(d1: DailyBar, d2: DailyBar, d1_support: float) -> tuple[bool, str]:
    volume_ratio = d2.volume / d1.volume if d1.volume else float("inf")
    close_below_high = 1 - (d2.close / d2.high) if d2.high else 0
    close_near_limit = d2.limit_up_price is not None and d2.close >= d2.limit_up_price * 0.995
    close_strong = d2.pct_chg is not None and d2.pct_chg >= 5 and close_below_high <= 0.025
    if not (close_near_limit or close_strong):
        return False, ""
    if volume_ratio > 3:
        return False, f"D2成交量/D1={volume_ratio:.2f}，超过3倍"
    if d2.close < d1_support:
        return False, "D2收盘跌破D1支撑位"
    return True, f"D2强势延续，量比{volume_ratio:.2f}，收盘贴近高点"


def is_d2_pullback(d1: DailyBar, d2: DailyBar, d1_support: float) -> tuple[bool, str]:
    strong_ok, strong_reason = is_d2_strong_continuation(d1, d2, d1_support)
    if strong_ok:
        return True, strong_reason
    if strong_reason:
        return False, strong_reason

    volume_ratio = d2.volume / d1.volume if d1.volume else float("inf")
    open_gap = (d2.open / d1.close) - 1 if d1.close else 0
    high_above_open = (d2.high / d2.open) - 1 if d2.open else 0
    close_below_high = 1 - (d2.close / d2.high) if d2.high else 0

    if volume_ratio > 3:
        return False, f"D2成交量/D1={volume_ratio:.2f}，超过3倍"
    if volume_ratio < 0.55:
        return False, f"D2成交量/D1={volume_ratio:.2f}，缩量过弱"
    if open_gap > 0.04 and d2.close < d2.open:
        return False, "D2高开低走，疑似出货"
    if high_above_open < 0.02:
        return False, "D2盘中冲高不足"
    if close_below_high < 0.02:
        return False, "D2冲高回落特征不足"
    if close_below_high > 0.08:
        return False, "D2上引线太长，收盘离高点太远"
    if d2.close < d1_support:
        return False, "D2收盘跌破D1支撑位"

    notes = [f"D2冲高回落，量比{volume_ratio:.2f}"]
    if volume_ratio > 2:
        notes.append("2-3倍但其他条件符合")
    if is_d2_balanced_cross(d2):
        notes.append("收盘近十字")
    notes.append("未破支撑")
    return True, "，".join(notes)


def is_d2_balanced_cross(d2: DailyBar) -> bool:
    day_range = d2.high - d2.low
    if day_range <= 0:
        return False
    return abs(d2.close - d2.open) / day_range <= 0.25


def build_d3_watch_signal(d1: DailyBar, d2: DailyBar, d1_support: float) -> StrategySignal:
    return StrategySignal(
        code=d2.code,
        name=d2.name,
        strategy="tulong",
        signal_type="D3_WATCH_UNDERWATER",
        reason="D1首板后，D2通过量能与形态过滤，次日观察水下低吸机会",
        trigger_price=d2.close,
        invalid_price=d1_support,
        risk_note="若D3跌破D1支撑位，策略失效；买入后的退出规则待验证后另行制定",
    )
