"""Signal grading and betting-discipline helpers."""

from __future__ import annotations

from dataclasses import dataclass

from value import MarketValue


@dataclass(frozen=True)
class Signal:
    kind: str
    label: str
    grade: str
    action: str
    rationale: str


def grade_1x2_value(values: list[MarketValue] | None) -> Signal:
    if not values:
        return Signal(
            kind="1X2 value",
            label="无赔率",
            grade="NO_ODDS",
            action="只看方向，不下注",
            rationale="没有 1X2 市场赔率，无法判断模型概率是否有价值。",
        )

    best = values[0]
    if best.edge >= 0.08 and best.model_probability >= 0.35:
        grade = "A"
        action = "可下注"
    elif best.edge >= 0.05 and best.model_probability >= 0.30:
        grade = "B"
        action = "小注/观察"
    elif best.edge >= 0.03:
        grade = "C"
        action = "仅观察"
    else:
        grade = "NO_BET"
        action = "放弃"

    return Signal(
        kind="1X2 value",
        label=best.selection,
        grade=grade,
        action=action,
        rationale=(
            f"模型 {best.model_probability:.1%} vs 市场 {best.market_probability:.1%}，"
            f"edge {best.edge:+.1%}，公允赔率 {best.fair_odds:.2f}。"
        ),
    )


def grade_ou25_lean(over_probability: float, under_probability: float) -> Signal:
    if over_probability >= under_probability:
        label = "大2.5"
        probability = over_probability
    else:
        label = "小2.5"
        probability = under_probability

    if probability >= 0.68:
        grade = "LEAN_STRONG"
        action = "强辅助信号"
    elif probability >= 0.60:
        grade = "LEAN"
        action = "辅助倾向"
    else:
        grade = "WEAK"
        action = "不作为依据"

    return Signal(
        kind="O/U 2.5 lean",
        label=label,
        grade=grade,
        action=action,
        rationale=f"收缩校准后概率 {probability:.1%}；O/U 当前只作辅助信号，不单独触发下注。",
    )


def overall_discipline(value_signal: Signal, ou_signal: Signal) -> str:
    if value_signal.grade == "A":
        if ou_signal.grade in {"LEAN", "LEAN_STRONG"}:
            return "主信号可下注；O/U 只作节奏参考，不加仓。"
        return "主信号可下注；缺少 totals 共振，控制仓位。"
    if value_signal.grade == "B":
        return "仅小注或观察，等待赔率更好。"
    if value_signal.grade == "C":
        return "边际不足，记录观察，不下注。"
    return "无有效投注信号。"
