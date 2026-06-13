"""
Football prediction CLI.

Usage:
  python3 scripts/predict.py "Mexico" "South Africa"
  python3 scripts/predict.py "Mexico" "South Africa" --build
  python3 scripts/predict.py "Mexico" "South Africa" --advanced
  python3 scripts/predict.py "Mexico" "South Africa" --advanced --odds-1x2 1.80 3.40 4.80
  python3 scripts/predict.py --sample
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from goals import GoalModelResult, summarize_goal_matrix
from post_calibration import calibrate_over_under
from ratings import build_elo_ratings, elo_gap_to_goal_adjustment
from signals import grade_1x2_value, grade_ou25_lean, overall_discipline
from football_types import TeamRating
from value import MarketValue, best_1x2_value

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_RATINGS_FILE = DATA_DIR / "ratings.json"
DEFAULT_MATCHES_FILE = DATA_DIR / "matches.json"

SAMPLE_RATINGS = {
    "Mexico": TeamRating("Mexico", attack=1.35, defense=0.85),
    "South Africa": TeamRating("South Africa", attack=0.85, defense=1.10),
    "Canada": TeamRating("Canada", attack=1.15, defense=1.05),
    "USA": TeamRating("USA", attack=1.25, defense=0.95),
    "Argentina": TeamRating("Argentina", attack=1.60, defense=0.75),
    "Brazil": TeamRating("Brazil", attack=1.55, defense=0.80),
    "France": TeamRating("France", attack=1.50, defense=0.85),
    "England": TeamRating("England", attack=1.45, defense=0.88),
    "Germany": TeamRating("Germany", attack=1.40, defense=0.90),
    "Spain": TeamRating("Spain", attack=1.42, defense=0.87),
    "Portugal": TeamRating("Portugal", attack=1.38, defense=0.92),
    "Japan": TeamRating("Japan", attack=1.10, defense=0.95),
    "South Korea": TeamRating("South Korea", attack=1.05, defense=1.00),
    "China PR": TeamRating("China PR", attack=0.70, defense=1.25),
    "Saudi Arabia": TeamRating("Saudi Arabia", attack=0.75, defense=1.20),
    "Nigeria": TeamRating("Nigeria", attack=0.90, defense=1.10),
    "Costa Rica": TeamRating("Costa Rica", attack=0.78, defense=1.15),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_ratings(filepath: Path | None = None) -> dict[str, TeamRating]:
    path = filepath or DEFAULT_RATINGS_FILE
    if path.exists():
        data = cast(dict[str, dict[str, float]], load_json(path))
        return {name: TeamRating(name=name, **values) for name, values in data.items()}
    return SAMPLE_RATINGS


def load_matches(filepath: Path | None = None) -> list[dict]:
    path = filepath or DEFAULT_MATCHES_FILE
    if not path.exists():
        return []
    return cast(list[dict], load_json(path))


def build_ratings_from_matches(matches_file: Path | None = None) -> dict[str, TeamRating]:
    matches = load_matches(matches_file)
    if not matches:
        print(f"Match data not found: {matches_file or DEFAULT_MATCHES_FILE}")
        print("Using built-in sample ratings instead.")
        return SAMPLE_RATINGS

    from model import estimate_ratings

    legacy_ratings = estimate_ratings(matches)
    ratings = {
        name: TeamRating(name=rating.name, attack=rating.attack, defense=rating.defense)
        for name, rating in legacy_ratings.items()
    }
    print(f"\nEstimated attack/defense ratings from {len(matches)} matches:\n")
    for name, rating in sorted(ratings.items()):
        print(f"  {name:20s}  attack={rating.attack:.3f}  defense={rating.defense:.3f}")
    return ratings


def save_ratings(ratings: dict[str, TeamRating]) -> None:
    out = {name: {"attack": rating.attack, "defense": rating.defense} for name, rating in ratings.items()}
    DEFAULT_RATINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_RATINGS_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nRatings saved to {DEFAULT_RATINGS_FILE}")


def choose_primary_pick(result: GoalModelResult) -> tuple[str, float]:
    options = [
        ("主胜", result.home_win),
        ("平局", result.draw),
        ("客胜", result.away_win),
    ]
    return max(options, key=lambda item: item[1])


def format_advanced_prediction(
    result: GoalModelResult,
    home_elo: float,
    away_elo: float,
    values: list[MarketValue] | None = None,
    value_signal=None,
    ou_signal=None,
) -> str:
    pick, pick_probability = choose_primary_pick(result)
    total_xg = result.home_xg + result.away_xg
    totals_pick = "大2.5" if result.over25 > result.under25 else "小2.5"
    totals_probability = max(result.over25, result.under25)

    lines = [
        "╔════════════════════════════════════════╗",
        f"║  {result.home} vs {result.away}",
        "╠════════════════════════════════════════╣",
        f"║  Elo: {result.home} {home_elo:.1f} — {away_elo:.1f} {result.away}",
        f"║  xG:  {result.home} {result.home_xg:.2f} — {result.away_xg:.2f} {result.away}  总xG={total_xg:.2f}",
        "╠════════════════════════════════════════╣",
        f"║  胜平负: 主胜 {result.home_win:.1%}  平 {result.draw:.1%}  客胜 {result.away_win:.1%}",
        f"║  大小球: 大2.5 {result.over25:.1%}  小2.5 {result.under25:.1%}",
        f"║  BTTS:  Yes {result.btts_yes:.1%}  No {result.btts_no:.1%}",
        "╠════════════════════════════════════════╣",
        f"║  模型结论: {pick}倾向 {pick_probability:.1%}；{totals_pick}倾向 {totals_probability:.1%}",
        "║  最可能比分:",
    ]
    for score, probability in result.top_scores:
        lines.append(f"║    {score}  {probability:.1%}")

    if value_signal and ou_signal:
        lines.extend([
            "╠════════════════════════════════════════╣",
            "║  信号纪律:",
            f"║    {value_signal.kind}: {value_signal.label} / {value_signal.grade} / {value_signal.action}",
            f"║      {value_signal.rationale}",
            f"║    {ou_signal.kind}: {ou_signal.label} / {ou_signal.grade} / {ou_signal.action}",
            f"║      {ou_signal.rationale}",
            f"║    总纪律: {overall_discipline(value_signal, ou_signal)}",
        ])

    if values:
        lines.extend([
            "╠════════════════════════════════════════╣",
            "║  1X2 价值判断:",
        ])
        for item in values:
            odds_text = f"  赔率 {item.offered_odds:.2f}" if item.offered_odds else ""
            lines.append(
                f"║    {item.selection}: 模型 {item.model_probability:.1%} / 市场 {item.market_probability:.1%} "
                f"/ Edge {item.edge:+.1%} / 公允赔率 {item.fair_odds:.2f}{odds_text} / {item.verdict}"
            )
    else:
        lines.extend([
            "╠════════════════════════════════════════╣",
            "║  投注判断: 未输入赔率，只能给方向，不能判断 value。",
        ])

    lines.append("╚════════════════════════════════════════╝")
    return "\n".join(lines)


def run_advanced_prediction(args: argparse.Namespace, ratings: dict[str, TeamRating]) -> None:
    matches = load_matches(args.matches)
    if matches:
        elo_ratings = build_elo_ratings(matches)
    else:
        elo_ratings = {}

    home_rating = ratings.get(args.home)
    away_rating = ratings.get(args.away)
    if home_rating is None or away_rating is None:
        report_missing_team(args.home, args.away, ratings)
        return

    home_elo = elo_ratings[args.home].rating if args.home in elo_ratings else 1500.0
    away_elo = elo_ratings[args.away].rating if args.away in elo_ratings else 1500.0
    home_factor, away_factor = elo_gap_to_goal_adjustment(home_elo, away_elo)

    base_home_xg = args.league_avg * home_rating.attack * away_rating.defense * args.home_adv
    base_away_xg = args.league_avg * away_rating.attack * home_rating.defense
    home_xg = max(min(base_home_xg * home_factor, 4.5), 0.15)
    away_xg = max(min(base_away_xg * away_factor, 4.5), 0.15)

    result = summarize_goal_matrix(
        args.home,
        args.away,
        home_xg,
        away_xg,
        max_goals=args.max_goals,
        over_line=args.over_line,
        rho=args.rho,
    )
    calibrated_over25, calibrated_under25 = calibrate_over_under(
        result.over25,
        base_over_rate=args.ou_base_rate,
        shrinkage=args.ou_shrinkage,
    )
    result = GoalModelResult(
        home=result.home,
        away=result.away,
        home_xg=result.home_xg,
        away_xg=result.away_xg,
        home_win=result.home_win,
        draw=result.draw,
        away_win=result.away_win,
        over25=calibrated_over25,
        under25=calibrated_under25,
        btts_yes=result.btts_yes,
        btts_no=result.btts_no,
        top_scores=result.top_scores,
    )

    values = None
    if args.odds_1x2:
        values = best_1x2_value(
            result.home_win,
            result.draw,
            result.away_win,
            args.odds_1x2[0],
            args.odds_1x2[1],
            args.odds_1x2[2],
            min_edge=args.min_edge,
        )

    value_signal = grade_1x2_value(values)
    ou_signal = grade_ou25_lean(result.over25, result.under25)

    print(format_advanced_prediction(result, home_elo, away_elo, values, value_signal, ou_signal))


def report_missing_team(home: str, away: str, ratings: dict[str, TeamRating]) -> None:
    missing = [team for team in [home, away] if team not in ratings]
    for team in missing:
        print(f"⚠️  Team not found: {team}")
    print(f"Available: {', '.join(sorted(ratings.keys()))}")
    sys.exit(1)


def run_demo() -> None:
    print("=" * 60)
    print("  Football Predictor — Demo")
    print("=" * 60)

    from model import TeamRating as LegacyTeamRating, format_prediction, predict

    demos = [
        ("世界杯 A 组首轮回顾预测", "Mexico", "South Africa"),
        ("南美德比", "Argentina", "Brazil"),
        ("东亚对决", "China PR", "Japan"),
    ]
    for title, home, away in demos:
        print(f"\n📌 {title}：")
        home_rating = SAMPLE_RATINGS[home]
        away_rating = SAMPLE_RATINGS[away]
        prediction = predict(
            LegacyTeamRating(home_rating.name, home_rating.attack, home_rating.defense),
            LegacyTeamRating(away_rating.name, away_rating.attack, away_rating.defense),
        )
        print(format_prediction(prediction))

    print("\n📌 Advanced + 赔率价值示例：")
    demo_args = argparse.Namespace(
        home="Mexico",
        away="South Africa",
        matches=DEFAULT_MATCHES_FILE,
        league_avg=1.35,
        home_adv=1.12,
        max_goals=8,
        over_line=2.5,
        rho=-0.04,
        ou_base_rate=0.45,
        ou_shrinkage=0.45,
        odds_1x2=[1.80, 3.40, 4.80],
        min_edge=0.04,
    )
    run_advanced_prediction(demo_args, SAMPLE_RATINGS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Football Predictor")
    parser.add_argument("home", nargs="?", help="Home team name")
    parser.add_argument("away", nargs="?", help="Away team name")
    parser.add_argument("--advanced", action="store_true", help="Use Elo + Dixon-Coles + optional market value layer")
    parser.add_argument("--build", action="store_true", help="Estimate attack/defense ratings from match data before predicting")
    parser.add_argument("--sample", action="store_true", help="Run built-in demo")
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES_FILE, help="Path to match history JSON")
    parser.add_argument("--ratings", type=Path, help="Path to ratings JSON")
    parser.add_argument("--league-avg", type=float, default=1.35, help="Average goals per team per match")
    parser.add_argument("--home-adv", type=float, default=1.12, help="Home advantage multiplier")
    parser.add_argument("--max-goals", type=int, default=8, help="Max goals in score matrix")
    parser.add_argument("--over-line", type=float, default=2.5, help="Over/under goal line")
    parser.add_argument("--rho", type=float, default=-0.04, help="Dixon-Coles low-score adjustment")
    parser.add_argument("--ou-base-rate", type=float, default=0.45, help="Historical over 2.5 base rate for O/U probability shrinkage")
    parser.add_argument("--ou-shrinkage", type=float, default=0.45, help="Shrink O/U probabilities toward the historical base rate")
    parser.add_argument("--odds-1x2", nargs=3, type=float, metavar=("HOME", "DRAW", "AWAY"), help="Decimal odds for 1X2 market")
    parser.add_argument("--min-edge", type=float, default=0.04, help="Minimum model-vs-market edge for value")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.sample:
        run_demo()
        return

    if not args.home or not args.away:
        print("\n💡 Quick demo: python3 scripts/predict.py --sample")
        print("💡 Advanced:   python3 scripts/predict.py \"Mexico\" \"South Africa\" --advanced --odds-1x2 1.80 3.40 4.80")
        return

    if args.build:
        ratings = build_ratings_from_matches(args.matches)
        save_ratings(ratings)
    elif args.ratings:
        ratings = load_ratings(args.ratings)
    elif DEFAULT_RATINGS_FILE.exists():
        ratings = load_ratings(DEFAULT_RATINGS_FILE)
    else:
        ratings = SAMPLE_RATINGS

    if args.advanced:
        run_advanced_prediction(args, ratings)
        return

    home_team = ratings.get(args.home)
    away_team = ratings.get(args.away)
    if home_team is None or away_team is None:
        report_missing_team(args.home, args.away, ratings)
        return

    from model import TeamRating as LegacyTeamRating, format_prediction, predict

    legacy_home = LegacyTeamRating(home_team.name, home_team.attack, home_team.defense)
    legacy_away = LegacyTeamRating(away_team.name, away_team.attack, away_team.defense)
    prediction = predict(legacy_home, legacy_away, league_avg=args.league_avg, home_advantage=args.home_adv)
    print(format_prediction(prediction))


if __name__ == "__main__":
    main()
