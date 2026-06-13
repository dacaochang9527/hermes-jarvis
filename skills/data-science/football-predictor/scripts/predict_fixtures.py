"""Predict a list of fixtures from imported World Cup-scope match history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from goals import GoalModelResult, summarize_goal_matrix
from post_calibration import calibrate_over_under
from ratings import elo_gap_to_goal_adjustment
from signals import grade_1x2_value, grade_ou25_lean, overall_discipline
from backtest import update_elo, update_goal_stats, team_attack_defense

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MATCHES = ROOT_DIR / "data/world_cup_matches_2014_onward.json"


def load_matches(path: Path) -> list[dict]:
    return sorted(json.loads(path.read_text()), key=lambda row: (row["date"], row["home"], row["away"]))


def build_state(matches: list[dict]) -> tuple[dict[str, float], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
    elo_ratings: dict[str, float] = {}
    elo_counts: dict[str, int] = {}
    scored: dict[str, int] = {}
    conceded: dict[str, int] = {}
    played: dict[str, int] = {}
    for match in matches:
        update_elo(match, elo_ratings, elo_counts)
        update_goal_stats(match, scored, conceded, played)
    return elo_ratings, scored, conceded, played, elo_counts


def choose_primary(result: GoalModelResult) -> tuple[str, float]:
    options = [("主胜", result.home_win), ("平局", result.draw), ("客胜", result.away_win)]
    return max(options, key=lambda item: item[1])


def predict_fixture(
    home: str,
    away: str,
    elo_ratings: dict[str, float],
    scored: dict[str, int],
    conceded: dict[str, int],
    played: dict[str, int],
    league_avg: float = 1.35,
    home_advantage: float = 1.12,
    rho: float = -0.04,
    ou_base_rate: float = 0.45,
    ou_shrinkage: float = 0.45,
) -> GoalModelResult:
    home_elo = elo_ratings.get(home, 1500.0)
    away_elo = elo_ratings.get(away, 1500.0)
    home_factor, away_factor = elo_gap_to_goal_adjustment(home_elo, away_elo)
    home_attack, home_defense = team_attack_defense(home, scored, conceded, played, league_avg)
    away_attack, away_defense = team_attack_defense(away, scored, conceded, played, league_avg)
    home_xg = max(min(league_avg * home_attack * away_defense * home_advantage * home_factor, 4.5), 0.15)
    away_xg = max(min(league_avg * away_attack * home_defense * away_factor, 4.5), 0.15)
    result = summarize_goal_matrix(home, away, home_xg, away_xg, rho=rho)
    over25, under25 = calibrate_over_under(result.over25, ou_base_rate, ou_shrinkage)
    return GoalModelResult(
        home=result.home,
        away=result.away,
        home_xg=result.home_xg,
        away_xg=result.away_xg,
        home_win=result.home_win,
        draw=result.draw,
        away_win=result.away_win,
        over25=over25,
        under25=under25,
        btts_yes=result.btts_yes,
        btts_no=result.btts_no,
        top_scores=result.top_scores,
    )


def format_fixture(home: str, away: str, result: GoalModelResult, elo_ratings: dict[str, float]) -> str:
    primary, primary_prob = choose_primary(result)
    ou_signal = grade_ou25_lean(result.over25, result.under25)
    value_signal = grade_1x2_value(None)
    scores = "、".join(f"{score} {prob:.1%}" for score, prob in result.top_scores[:3])
    return "\n".join([
        f"{home} vs {away}",
        f"- Elo: {elo_ratings.get(home, 1500.0):.1f} vs {elo_ratings.get(away, 1500.0):.1f}；xG: {result.home_xg:.2f}-{result.away_xg:.2f}",
        f"- 胜平负: 主 {result.home_win:.1%} / 平 {result.draw:.1%} / 客 {result.away_win:.1%}；结论: {primary} {primary_prob:.1%}",
        f"- 大小球: 大2.5 {result.over25:.1%} / 小2.5 {result.under25:.1%}；{ou_signal.label} / {ou_signal.grade}",
        f"- 比分倾向: {scores}",
        f"- 纪律: {overall_discipline(value_signal, ou_signal)}（无赔率，不做 value 下注判断）",
    ])


def parse_fixture(text: str) -> tuple[str, str]:
    if ":" in text:
        text = text.split(":", 1)[1]
    if "-" in text:
        home, away = text.split("-", 1)
    elif "vs" in text:
        home, away = text.split("vs", 1)
    else:
        raise ValueError(f"Fixture must be HOME-AWAY or HOME vs AWAY: {text}")
    return home.strip(), away.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict multiple World Cup fixtures from imported history")
    parser.add_argument("fixtures", nargs="+", help="Fixtures as 'Home-Away' or 'Home vs Away'")
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matches = load_matches(args.matches)
    elo_ratings, scored, conceded, played, _ = build_state(matches)
    for fixture in args.fixtures:
        home, away = parse_fixture(fixture)
        result = predict_fixture(home, away, elo_ratings, scored, conceded, played)
        print(format_fixture(home, away, result, elo_ratings))
        print()


if __name__ == "__main__":
    main()
