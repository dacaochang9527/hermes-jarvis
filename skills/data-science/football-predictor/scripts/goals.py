"""Goal-distribution models for football prediction."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial


@dataclass(frozen=True)
class GoalModelResult:
    home: str
    away: str
    home_xg: float
    away_xg: float
    home_win: float
    draw: float
    away_win: float
    over25: float
    under25: float
    btts_yes: float
    btts_no: float
    top_scores: list[tuple[str, float]]


def poisson_pmf(k: int, lam: float) -> float:
    return exp(-lam) * lam**k / factorial(k)


def dixon_coles_adjustment(home_goals: int, away_goals: int, home_xg: float, away_xg: float, rho: float) -> float:
    """Low-score dependence correction from Dixon-Coles."""
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_xg * away_xg * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_xg * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_xg * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(
    home_xg: float,
    away_xg: float,
    max_goals: int = 8,
    rho: float = 0.0,
) -> list[list[float]]:
    matrix: list[list[float]] = []
    for home_goals in range(max_goals + 1):
        row = []
        for away_goals in range(max_goals + 1):
            probability = poisson_pmf(home_goals, home_xg) * poisson_pmf(away_goals, away_xg)
            if rho:
                probability *= max(dixon_coles_adjustment(home_goals, away_goals, home_xg, away_xg, rho), 0.0)
            row.append(probability)
        matrix.append(row)

    total = sum(sum(row) for row in matrix)
    if total > 0:
        matrix = [[cell / total for cell in row] for row in matrix]
    return matrix


def summarize_goal_matrix(
    home: str,
    away: str,
    home_xg: float,
    away_xg: float,
    max_goals: int = 8,
    over_line: float = 2.5,
    rho: float = -0.08,
    top_n: int = 5,
) -> GoalModelResult:
    matrix = score_matrix(home_xg, away_xg, max_goals=max_goals, rho=rho)
    home_win = draw = away_win = 0.0
    over = under = 0.0
    btts_yes = btts_no = 0.0
    score_probs: list[tuple[str, float]] = []

    for home_goals, row in enumerate(matrix):
        for away_goals, probability in enumerate(row):
            if home_goals > away_goals:
                home_win += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away_win += probability

            if home_goals + away_goals > over_line:
                over += probability
            else:
                under += probability

            if home_goals > 0 and away_goals > 0:
                btts_yes += probability
            else:
                btts_no += probability

            score_probs.append((f"{home_goals}-{away_goals}", probability))

    score_probs.sort(key=lambda item: item[1], reverse=True)
    return GoalModelResult(
        home=home,
        away=away,
        home_xg=round(home_xg, 2),
        away_xg=round(away_xg, 2),
        home_win=home_win,
        draw=draw,
        away_win=away_win,
        over25=over,
        under25=under,
        btts_yes=btts_yes,
        btts_no=btts_no,
        top_scores=score_probs[:top_n],
    )
