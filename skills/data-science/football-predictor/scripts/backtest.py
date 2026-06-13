"""Rolling backtest for World Cup 2026 football predictor scope."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from goals import summarize_goal_matrix
from post_calibration import calibrate_over_under
from ratings import EloRating, elo_gap_to_goal_adjustment, expected_result, margin_multiplier, match_result

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
REPORTS_DIR = ROOT_DIR / "reports"
DEFAULT_MATCHES = DATA_DIR / "world_cup_matches_2014_onward.json"
DEFAULT_PREDICTIONS_OUT = REPORTS_DIR / "backtest_predictions.csv"


@dataclass(frozen=True)
class BacktestPrediction:
    date: str
    home: str
    away: str
    competition: str
    home_goals: int
    away_goals: int
    actual_1x2: str
    predicted_1x2: str
    home_win_prob: float
    draw_prob: float
    away_win_prob: float
    actual_total: int
    actual_ou25: str
    predicted_ou25: str
    over25_prob: float
    under25_prob: float
    home_elo: float
    away_elo: float
    home_xg: float
    away_xg: float


def load_matches(path: Path) -> list[dict]:
    return sorted(json.loads(path.read_text()), key=lambda row: (row["date"], row["home"], row["away"]))


def actual_1x2(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def actual_ou25(home_goals: int, away_goals: int) -> str:
    return "over" if home_goals + away_goals > 2.5 else "under"


def argmax_1x2(home_win: float, draw: float, away_win: float) -> str:
    return max(
        [("home", home_win), ("draw", draw), ("away", away_win)],
        key=lambda item: item[1],
    )[0]


def safe_log_loss(probability: float) -> float:
    return -math.log(max(min(probability, 1 - 1e-12), 1e-12))


def competition_weight(competition: str) -> float:
    if competition == "FIFA World Cup":
        return 1.25
    return 1.0


def weighted_training_matches(matches: list[dict]) -> list[dict]:
    """Repeat high-weight matches once in a simple dependency-free way."""
    weighted: list[dict] = []
    for match in matches:
        weighted.append(match)
        if competition_weight(match["competition"]) >= 1.25:
            weighted.append(match)
    return weighted


def estimate_goal_priors(training_matches: list[dict], default_avg: float = 1.25) -> tuple[dict[str, float], dict[str, float]]:
    scored: dict[str, int] = {}
    conceded: dict[str, int] = {}
    played: dict[str, int] = {}

    for match in training_matches:
        home = match["home"]
        away = match["away"]
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        scored[home] = scored.get(home, 0) + home_goals
        conceded[home] = conceded.get(home, 0) + away_goals
        played[home] = played.get(home, 0) + 1
        scored[away] = scored.get(away, 0) + away_goals
        conceded[away] = conceded.get(away, 0) + home_goals
        played[away] = played.get(away, 0) + 1

    attack: dict[str, float] = {}
    defense: dict[str, float] = {}
    teams = set(played)
    for team in teams:
        matches = max(played.get(team, 0), 1)
        goals_for = scored.get(team, 0) / matches
        goals_against = conceded.get(team, 0) / matches
        attack[team] = max(min((goals_for + default_avg) / (2 * default_avg), 1.8), 0.45)
        defense[team] = max(min((goals_against + default_avg) / (2 * default_avg), 1.8), 0.45)
    return attack, defense


def update_goal_stats(match: dict, scored: dict[str, int], conceded: dict[str, int], played: dict[str, int]) -> None:
    repetitions = 2 if competition_weight(match["competition"]) >= 1.25 else 1
    home = match["home"]
    away = match["away"]
    home_goals = int(match["home_goals"])
    away_goals = int(match["away_goals"])
    for _ in range(repetitions):
        scored[home] = scored.get(home, 0) + home_goals
        conceded[home] = conceded.get(home, 0) + away_goals
        played[home] = played.get(home, 0) + 1
        scored[away] = scored.get(away, 0) + away_goals
        conceded[away] = conceded.get(away, 0) + home_goals
        played[away] = played.get(away, 0) + 1


def team_attack_defense(team: str, scored: dict[str, int], conceded: dict[str, int], played: dict[str, int], default_avg: float) -> tuple[float, float]:
    matches = max(played.get(team, 0), 1)
    goals_for = scored.get(team, 0) / matches
    goals_against = conceded.get(team, 0) / matches
    attack = max(min((goals_for + default_avg) / (2 * default_avg), 1.8), 0.45)
    defense = max(min((goals_against + default_avg) / (2 * default_avg), 1.8), 0.45)
    return attack, defense


def update_elo(match: dict, ratings: dict[str, float], counts: dict[str, int], base_rating: float = 1500.0, k_factor: float = 28.0, home_advantage: float = 45.0) -> None:
    repetitions = 2 if competition_weight(match["competition"]) >= 1.25 else 1
    home = match["home"]
    away = match["away"]
    home_goals = int(match["home_goals"])
    away_goals = int(match["away_goals"])
    for _ in range(repetitions):
        ratings.setdefault(home, base_rating)
        ratings.setdefault(away, base_rating)
        counts.setdefault(home, 0)
        counts.setdefault(away, 0)
        home_rating = ratings[home]
        away_rating = ratings[away]
        neutral = bool(match.get("is_neutral"))
        expected_home = expected_result(home_rating + (0.0 if neutral else home_advantage), away_rating)
        actual_home, _ = match_result(home_goals, away_goals)
        change = k_factor * margin_multiplier(home_goals - away_goals) * (actual_home - expected_home)
        ratings[home] = home_rating + change
        ratings[away] = away_rating - change
        counts[home] += 1
        counts[away] += 1


def probability_for_actual(prediction: BacktestPrediction) -> float:
    if prediction.actual_1x2 == "home":
        return prediction.home_win_prob
    if prediction.actual_1x2 == "draw":
        return prediction.draw_prob
    return prediction.away_win_prob


def probability_for_actual_ou25(prediction: BacktestPrediction) -> float:
    if prediction.actual_ou25 == "over":
        return prediction.over25_prob
    return prediction.under25_prob


def run_backtest(
    matches: list[dict],
    min_training_matches: int = 100,
    league_avg: float = 1.25,
    home_advantage: float = 1.06,
    rho: float = -0.08,
    ou_base_rate: float = 0.45,
    ou_shrinkage: float = 0.45,
) -> list[BacktestPrediction]:
    predictions: list[BacktestPrediction] = []
    elo_ratings: dict[str, float] = {}
    elo_counts: dict[str, int] = {}
    scored: dict[str, int] = {}
    conceded: dict[str, int] = {}
    played: dict[str, int] = {}

    for index, match in enumerate(matches):
        home = match["home"]
        away = match["away"]
        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])

        if index >= min_training_matches:
            home_elo = elo_ratings.get(home, 1500.0)
            away_elo = elo_ratings.get(away, 1500.0)
            home_factor, away_factor = elo_gap_to_goal_adjustment(home_elo, away_elo)

            neutral_factor = 1.0 if match.get("is_neutral") else home_advantage
            home_attack, home_defense = team_attack_defense(home, scored, conceded, played, league_avg)
            away_attack, away_defense = team_attack_defense(away, scored, conceded, played, league_avg)
            home_xg = max(min(league_avg * home_attack * away_defense * neutral_factor * home_factor, 4.5), 0.15)
            away_xg = max(min(league_avg * away_attack * home_defense * away_factor, 4.5), 0.15)

            result = summarize_goal_matrix(home, away, home_xg, away_xg, rho=rho)
            over25_prob, under25_prob = calibrate_over_under(
                result.over25,
                base_over_rate=ou_base_rate,
                shrinkage=ou_shrinkage,
            )
            predicted_1x2 = argmax_1x2(result.home_win, result.draw, result.away_win)
            predicted_ou25 = "over" if over25_prob > under25_prob else "under"

            predictions.append(
                BacktestPrediction(
                    date=match["date"],
                    home=home,
                    away=away,
                    competition=match["competition"],
                    home_goals=home_goals,
                    away_goals=away_goals,
                    actual_1x2=actual_1x2(home_goals, away_goals),
                    predicted_1x2=predicted_1x2,
                    home_win_prob=result.home_win,
                    draw_prob=result.draw,
                    away_win_prob=result.away_win,
                    actual_total=home_goals + away_goals,
                    actual_ou25=actual_ou25(home_goals, away_goals),
                    predicted_ou25=predicted_ou25,
                    over25_prob=over25_prob,
                    under25_prob=under25_prob,
                    home_elo=home_elo,
                    away_elo=away_elo,
                    home_xg=result.home_xg,
                    away_xg=result.away_xg,
                )
            )

        update_elo(match, elo_ratings, elo_counts)
        update_goal_stats(match, scored, conceded, played)

    return predictions


def summarize(predictions: list[BacktestPrediction]) -> dict[str, float | int]:
    if not predictions:
        return {"matches": 0}

    correct_1x2 = sum(p.actual_1x2 == p.predicted_1x2 for p in predictions)
    correct_ou25 = sum(p.actual_ou25 == p.predicted_ou25 for p in predictions)
    log_loss_1x2 = sum(safe_log_loss(probability_for_actual(p)) for p in predictions) / len(predictions)
    log_loss_ou25 = sum(safe_log_loss(probability_for_actual_ou25(p)) for p in predictions) / len(predictions)
    return {
        "matches": len(predictions),
        "accuracy_1x2": correct_1x2 / len(predictions),
        "accuracy_ou25": correct_ou25 / len(predictions),
        "log_loss_1x2": log_loss_1x2,
        "log_loss_ou25": log_loss_ou25,
    }


def write_predictions(predictions: list[BacktestPrediction], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(BacktestPrediction.__dataclass_fields__.keys())
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for prediction in predictions:
            writer.writerow(asdict(prediction))


def print_summary(summary: dict[str, float | int], predictions_out: Path) -> None:
    if summary.get("matches", 0) == 0:
        print("No predictions generated. Lower --min-training-matches or check input data.")
        return
    print(f"Backtested matches: {summary['matches']}")
    print(f"1X2 accuracy: {summary['accuracy_1x2']:.1%}")
    print(f"O/U 2.5 accuracy: {summary['accuracy_ou25']:.1%}")
    print(f"1X2 log loss: {summary['log_loss_1x2']:.4f}")
    print(f"O/U 2.5 log loss: {summary['log_loss_ou25']:.4f}")
    print(f"Predictions written: {predictions_out}")
    print("Note: betting ROI is not evaluated because historical odds are not included yet.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rolling backtest for World Cup finals + qualifiers")
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES, help="Imported match JSON")
    parser.add_argument("--predictions-out", type=Path, default=DEFAULT_PREDICTIONS_OUT, help="Prediction CSV output")
    parser.add_argument("--no-predictions-out", action="store_true", help="Do not write per-match prediction CSV")
    parser.add_argument("--min-training-matches", type=int, default=100, help="Skip early matches until enough history exists")
    parser.add_argument("--league-avg", type=float, default=1.25, help="Baseline goals per team")
    parser.add_argument("--home-adv", type=float, default=1.06, help="Home advantage multiplier for non-neutral matches")
    parser.add_argument("--rho", type=float, default=-0.08, help="Dixon-Coles low-score adjustment")
    parser.add_argument("--ou-base-rate", type=float, default=0.45, help="Historical over 2.5 base rate for O/U probability shrinkage")
    parser.add_argument("--ou-shrinkage", type=float, default=0.45, help="Shrink O/U probabilities toward the historical base rate")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matches = load_matches(args.matches)
    predictions = run_backtest(
        matches,
        min_training_matches=args.min_training_matches,
        league_avg=args.league_avg,
        home_advantage=args.home_adv,
        rho=args.rho,
        ou_base_rate=args.ou_base_rate,
        ou_shrinkage=args.ou_shrinkage,
    )
    if not args.no_predictions_out:
        write_predictions(predictions, args.predictions_out)
    print_summary(summarize(predictions), args.predictions_out)


if __name__ == "__main__":
    main()
