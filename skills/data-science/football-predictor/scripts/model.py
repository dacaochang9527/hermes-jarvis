"""
Football Match Predictor — MVP
Poisson-based model using team attack/defense ratings.
"""

from dataclasses import dataclass, field
from itertools import product

import numpy as np
from scipy.stats import poisson

# ── data structures ────────────────────────────────────────────

@dataclass
class TeamRating:
    """Attack and defense strength relative to league average (1.0)."""
    name: str
    attack: float = 1.0    # >1 means above average scoring
    defense: float = 1.0   # <1 means tighter defense (multiplier on opponent goals)


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
    top_scores: list[tuple[str, float]]  # [(score, prob), ...]
    home_xg: float
    away_xg: float


# ── core model ─────────────────────────────────────────────────

def expected_goals(
    home: TeamRating,
    away: TeamRating,
    league_avg: float = 1.4,
    home_advantage: float = 1.15,
) -> tuple[float, float]:
    """
    λ_home = league_avg × home_attack × away_defense × home_advantage
    λ_away = league_avg × away_attack × home_defense
    """
    lam_home = league_avg * home.attack * away.defense * home_advantage
    lam_away = league_avg * away.attack * home.defense
    return lam_home, lam_away


def score_probability_matrix(
    lam_home: float, lam_away: float, max_goals: int = 6
) -> np.ndarray:
    """Return (max_goals+1)×(max_goals+1) matrix of score probabilities."""
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
    """Run full prediction for a match."""
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

            # 1X2
            if i > j:
                home_win += p
            elif i == j:
                draw += p
            else:
                away_win += p

            # Over/Under
            total = i + j
            if total > over_line:
                over += p
            else:
                under += p

            # BTTS
            if i > 0 and j > 0:
                btts_yes += p
            else:
                btts_no += p

            # Exact score
            score_probs.append((f"{i}-{j}", p))

    # Sort by probability desc, take top N
    score_probs.sort(key=lambda x: x[1], reverse=True)

    # Normalize truncated tail
    rest = 1.0 - (home_win + draw + away_win)
    home_win += rest * (home_win / (home_win + draw + away_win + 1e-12)) if (home_win + draw + away_win) > 0 else rest / 3
    draw     += rest * (draw     / (home_win + draw + away_win + 1e-12)) if (home_win + draw + away_win) > 0 else rest / 3
    away_win += rest * (away_win / (home_win + draw + away_win + 1e-12)) if (home_win + draw + away_win) > 0 else rest / 3

    return Prediction(
        home=home.name,
        away=away.name,
        home_win=round(home_win, 4),
        draw=round(draw, 4),
        away_win=round(away_win, 4),
        over25=round(over, 4),
        under25=round(under, 4),
        btts_yes=round(btts_yes, 4),
        btts_no=round(btts_no, 4),
        top_scores=score_probs[:top_n],
        home_xg=round(lam_home, 2),
        away_xg=round(lam_away, 2),
    )


# ── team rating estimation from match history ──────────────────

def estimate_ratings(
    matches: list[dict],
    league_avg: float = 1.4,
    home_advantage: float = 1.15,
    max_iter: int = 50,
    tol: float = 1e-6,
) -> dict[str, TeamRating]:
    """
    Simple iterative maximum-likelihood estimation of attack/defense ratings.

    matches: list of {"home": str, "away": str, "home_goals": int, "away_goals": int}
    Returns: {team_name: TeamRating}
    """
    # Collect teams
    teams = set()
    for m in matches:
        teams.add(m["home"])
        teams.add(m["away"])
    teams = sorted(teams)

    # Init all ratings to 1.0
    attack = {t: 1.0 for t in teams}
    defense = {t: 1.0 for t in teams}

    for iteration in range(max_iter):
        att_num = {t: 0.0 for t in teams}
        att_den = {t: 0.0 for t in teams}
        def_num = {t: 0.0 for t in teams}
        def_den = {t: 0.0 for t in teams}

        for m in matches:
            h = m["home"]
            a = m["away"]
            hg = m["home_goals"]
            ag = m["away_goals"]

            # Home team attack denominator: league_avg * away_defense * home_advantage
            att_den[h] += league_avg * defense[a] * home_advantage
            att_num[h] += hg

            # Home team defense denominator: league_avg * away_attack
            def_den[h] += league_avg * attack[a]
            def_num[h] += ag

            # Away team attack denominator: league_avg * home_defense
            att_den[a] += league_avg * defense[h]
            att_num[a] += ag

            # Away team defense denominator: league_avg * home_attack * home_advantage
            def_den[a] += league_avg * attack[h] * home_advantage
            def_num[a] += hg

        # Update: new_rating = goals_scored / expected_from_defense_context
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


# ── pretty print ───────────────────────────────────────────────

def format_prediction(p: Prediction) -> str:
    """Return a formatted prediction summary string."""
    lines = [
        f"╔══════════════════════════════════╗",
        f"║  {p.home} vs {p.away}",
        f"╠══════════════════════════════════╣",
        f"║  xG:  {p.home} {p.home_xg} — {p.away_xg} {p.away}",
        f"╠══════════════════════════════════╣",
        f"║  主胜: {p.home_win:.1%}  平: {p.draw:.1%}  客胜: {p.away_win:.1%}",
        f"║  大2.5: {p.over25:.1%}  小2.5: {p.under25:.1%}",
        f"║  BTTS Yes: {p.btts_yes:.1%}  No: {p.btts_no:.1%}",
        f"╠══════════════════════════════════╣",
        f"║  最可能比分:",
    ]
    for score, prob in p.top_scores:
        lines.append(f"║    {score}  {prob:.1%}")
    lines.append("╚══════════════════════════════════╝")
    return "\n".join(lines)
