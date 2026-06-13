"""Team-strength ratings for football prediction."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class EloRating:
    team: str
    rating: float
    matches: int = 0


def expected_result(rating_a: float, rating_b: float) -> float:
    """Expected score for team A against team B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def match_result(home_goals: int, away_goals: int) -> tuple[float, float]:
    if home_goals > away_goals:
        return 1.0, 0.0
    if home_goals < away_goals:
        return 0.0, 1.0
    return 0.5, 0.5


def margin_multiplier(goal_diff: int) -> float:
    """Dampen blowouts without ignoring margin of victory."""
    diff = abs(goal_diff)
    if diff <= 1:
        return 1.0
    return 1.0 + 0.35 * (diff - 1)


def build_elo_ratings(
    matches: list[dict],
    base_rating: float = 1500.0,
    k_factor: float = 28.0,
    home_advantage: float = 60.0,
) -> dict[str, EloRating]:
    """Estimate national-team strength from chronological match history."""
    ratings: dict[str, float] = {}
    counts: dict[str, int] = {}

    for match in matches:
        home = match["home"]
        away = match["away"]
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])

        ratings.setdefault(home, base_rating)
        ratings.setdefault(away, base_rating)
        counts.setdefault(home, 0)
        counts.setdefault(away, 0)

        home_rating = ratings[home]
        away_rating = ratings[away]
        expected_home = expected_result(home_rating + home_advantage, away_rating)
        actual_home, actual_away = match_result(home_goals, away_goals)
        multiplier = margin_multiplier(home_goals - away_goals)
        change = k_factor * multiplier * (actual_home - expected_home)

        ratings[home] = home_rating + change
        ratings[away] = away_rating - change
        counts[home] += 1
        counts[away] += 1

    return {
        team: EloRating(team=team, rating=round(rating, 1), matches=counts.get(team, 0))
        for team, rating in sorted(ratings.items())
    }


def elo_gap_to_goal_adjustment(home_elo: float, away_elo: float, scale: float = 600.0) -> tuple[float, float]:
    """Convert Elo gap into smooth attack multipliers for expected goals."""
    gap = max(min(home_elo - away_elo, 500.0), -500.0)
    home_factor = exp(gap / scale)
    away_factor = exp(-gap / scale)
    return home_factor, away_factor
