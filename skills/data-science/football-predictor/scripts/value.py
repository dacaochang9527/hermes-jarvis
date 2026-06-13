"""Betting-market value checks for football predictions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketValue:
    market: str
    selection: str
    model_probability: float
    market_probability: float
    edge: float
    fair_odds: float
    offered_odds: float | None
    verdict: str


def implied_probability(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        raise ValueError("decimal odds must be > 1.0")
    return 1.0 / decimal_odds


def normalize_1x2_market(home_odds: float, draw_odds: float, away_odds: float) -> dict[str, float]:
    raw = {
        "home": implied_probability(home_odds),
        "draw": implied_probability(draw_odds),
        "away": implied_probability(away_odds),
    }
    overround = sum(raw.values())
    return {key: value / overround for key, value in raw.items()}


def fair_odds(probability: float) -> float:
    if probability <= 0:
        return float("inf")
    return 1.0 / probability


def value_verdict(edge: float, min_edge: float = 0.04) -> str:
    if edge >= min_edge * 1.5:
        return "可下注"
    if edge >= min_edge:
        return "小注/观察"
    if edge > 0:
        return "优势不足"
    return "放弃"


def evaluate_selection(
    market: str,
    selection: str,
    model_probability: float,
    offered_odds: float | None = None,
    market_probability: float | None = None,
    min_edge: float = 0.04,
) -> MarketValue:
    if market_probability is None:
        if offered_odds is None:
            raise ValueError("offered_odds or market_probability is required")
        market_probability = implied_probability(offered_odds)

    edge = model_probability - market_probability
    return MarketValue(
        market=market,
        selection=selection,
        model_probability=model_probability,
        market_probability=market_probability,
        edge=edge,
        fair_odds=fair_odds(model_probability),
        offered_odds=offered_odds,
        verdict=value_verdict(edge, min_edge=min_edge),
    )


def best_1x2_value(
    home_probability: float,
    draw_probability: float,
    away_probability: float,
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    min_edge: float = 0.04,
) -> list[MarketValue]:
    market = normalize_1x2_market(home_odds, draw_odds, away_odds)
    values = [
        evaluate_selection("1X2", "主胜", home_probability, home_odds, market["home"], min_edge),
        evaluate_selection("1X2", "平局", draw_probability, draw_odds, market["draw"], min_edge),
        evaluate_selection("1X2", "客胜", away_probability, away_odds, market["away"], min_edge),
    ]
    return sorted(values, key=lambda item: item.edge, reverse=True)
