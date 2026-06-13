"""
Reference implementation of the Poisson football predictor.
Copy/modify this for new projects.
"""

from dataclasses import dataclass
from itertools import product

import numpy as np
from scipy.stats import poisson


@dataclass
class TeamRating:
    name: str
    attack: float = 1.0
    defense: float = 1.0


@dataclass
class Prediction:
    home: str
    away: str
    home_win: float
    draw: float
    away_win: float
    over25: float
    under25: float
    btts_yes: float
    btts_no: float
    top_scores: list[tuple[str, float]]
    home_xg: float
    away_xg: float


def expected_goals(
    home: TeamRating,
    away: TeamRating,
    league_avg: float = 1.4,
    home_advantage: float = 1.15,
) -> tuple[float, float]:
    """λ_home / λ_away from team ratings."""
    lam_home = league_avg * home.attack * away.defense * home_advantage
    lam_away = league_avg * away.attack * home.defense
    return lam_home, lam_away


def score_probability_matrix(
    lam_home: float, lam_away: float, max_goals: int = 6
) -> np.ndarray:
    """(max_goals+1)×(max_goals+1) score probability matrix."""
    home_probs = poisson.pmf(np.arange(max_goals + 1), lam_home)
    away_probs = poisson.pmf(np.arange(max_goals + 1), lam_away)
    return np.outer(home_probs, away_probs)


def predict(
    home: TeamRating,
    away: TeamRating,
    league_avg: float = 1.4,
    home_advantage: float = 1.15,
    max_goals: int = 6,
    over_line: float = 2.5,
    top_n: int = 5,
) -> Prediction:
    """Full prediction from team ratings."""
    lam_home, lam_away = expected_goals(home, away, league_avg, home_advantage)
    matrix = score_probability_matrix(lam_home, lam_away, max_goals)

    home_win = draw = away_win = 0.0
    over = under = 0.0
    btts_yes = btts_no = 0.0
    score_probs: list[tuple[str, float]] = []

    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = matrix[i, j]
            if p < 1e-10:
                continue
            if i > j:
                home_win += p
            elif i == j:
                draw += p
            else:
                away_win += p
            if i + j > over_line:
                over += p
            else:
                under += p
            if i > 0 and j > 0:
                btts_yes += p
            else:
                btts_no += p
            score_probs.append((f"{i}-{j}", p))

    score_probs.sort(key=lambda x: x[1], reverse=True)

    # Normalize truncated tail
    total = home_win + draw + away_win
    if total > 0:
        rest = 1.0 - total
        home_win += rest * home_win / total
        draw += rest * draw / total
        away_win += rest * away_win / total

    return Prediction(
        home=home.name, away=away.name,
        home_win=round(home_win, 4), draw=round(draw, 4), away_win=round(away_win, 4),
        over25=round(over, 4), under25=round(under, 4),
        btts_yes=round(btts_yes, 4), btts_no=round(btts_no, 4),
        top_scores=score_probs[:top_n],
        home_xg=round(lam_home, 2), away_xg=round(lam_away, 2),
    )


def estimate_ratings(
    matches: list[dict],
    league_avg: float = 1.4,
    home_advantage: float = 1.15,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> dict[str, TeamRating]:
    """
    Iterative MLE estimation of attack/defense from match history.
    
    matches: [{"home": str, "away": str, "home_goals": int, "away_goals": int}, ...]
    """
    teams = sorted(set(m["home"] for m in matches) | set(m["away"] for m in matches))
    attack = {t: 1.0 for t in teams}
    defense = {t: 1.0 for t in teams}

    for _ in range(max_iter):
        att_num = {t: 0.0 for t in teams}
        att_den = {t: 0.0 for t in teams}
        def_num = {t: 0.0 for t in teams}
        def_den = {t: 0.0 for t in teams}

        for m in matches:
            h, a = m["home"], m["away"]
            hg, ag = m["home_goals"], m["away_goals"]

            # Home attack denominator: league_avg * away_defense * home_advantage
            att_den[h] += league_avg * defense[a] * home_advantage
            att_num[h] += hg
            # Home defense denominator: league_avg * away_attack
            def_den[h] += league_avg * attack[a]
            def_num[h] += ag
            # Away attack denominator: league_avg * home_defense
            att_den[a] += league_avg * defense[h]
            att_num[a] += ag
            # Away defense denominator: league_avg * home_attack * home_advantage
            def_den[a] += league_avg * attack[h] * home_advantage
            def_num[a] += hg

        # Update: rating = goals / expected_from_opponent_context
        max_change = 0.0
        for t in teams:
            new_att = att_num[t] / att_den[t] if att_den[t] > 0 else 1.0
            new_def = def_num[t] / def_den[t] if def_den[t] > 0 else 1.0
            max_change = max(max_change, abs(new_att - attack[t]), abs(new_def - defense[t]))
            attack[t] = new_att
            defense[t] = new_def

        if max_change < tol:
            break

    return {t: TeamRating(name=t, attack=round(attack[t], 3), defense=round(defense[t], 3))
            for t in teams}
