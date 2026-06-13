"""Grid-search calibration for the World Cup football predictor."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from backtest import DEFAULT_MATCHES, REPORTS_DIR, load_matches, run_backtest, summarize

DEFAULT_RESULTS_OUT = REPORTS_DIR / "calibration_results.csv"
DEFAULT_BEST_OUT = REPORTS_DIR / "calibration_best.json"


@dataclass(frozen=True)
class CalibrationResult:
    league_avg: float
    home_adv: float
    rho: float
    min_training_matches: int
    matches: int
    accuracy_1x2: float
    accuracy_ou25: float
    log_loss_1x2: float
    log_loss_ou25: float
    score: float


def parse_float_grid(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def parse_int_grid(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def calibration_score(log_loss_1x2: float, log_loss_ou25: float) -> float:
    """Primary objective is 1X2; O/U is a secondary stabilizer."""
    return log_loss_1x2 * 0.7 + log_loss_ou25 * 0.3


def run_calibration(
    matches: list[dict],
    league_avgs: list[float],
    home_advs: list[float],
    rhos: list[float],
    min_training_grid: list[int],
) -> list[CalibrationResult]:
    results: list[CalibrationResult] = []
    total = len(league_avgs) * len(home_advs) * len(rhos) * len(min_training_grid)
    completed = 0

    for min_training_matches in min_training_grid:
        for league_avg in league_avgs:
            for home_adv in home_advs:
                for rho in rhos:
                    completed += 1
                    predictions = run_backtest(
                        matches,
                        min_training_matches=min_training_matches,
                        league_avg=league_avg,
                        home_advantage=home_adv,
                        rho=rho,
                    )
                    metrics = summarize(predictions)
                    if metrics.get("matches", 0) == 0:
                        continue
                    log_loss_1x2 = float(metrics["log_loss_1x2"])
                    log_loss_ou25 = float(metrics["log_loss_ou25"])
                    results.append(
                        CalibrationResult(
                            league_avg=league_avg,
                            home_adv=home_adv,
                            rho=rho,
                            min_training_matches=min_training_matches,
                            matches=int(metrics["matches"]),
                            accuracy_1x2=float(metrics["accuracy_1x2"]),
                            accuracy_ou25=float(metrics["accuracy_ou25"]),
                            log_loss_1x2=log_loss_1x2,
                            log_loss_ou25=log_loss_ou25,
                            score=calibration_score(log_loss_1x2, log_loss_ou25),
                        )
                    )
                    print(f"[{completed}/{total}] league_avg={league_avg} home_adv={home_adv} rho={rho} min_train={min_training_matches}")

    return sorted(results, key=lambda item: (item.score, item.log_loss_1x2, item.log_loss_ou25))


def write_results(results: list[CalibrationResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(CalibrationResult.__dataclass_fields__.keys())
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.__dict__)


def write_best(result: CalibrationResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.__dict__, indent=2, ensure_ascii=False))


def print_best(results: list[CalibrationResult], results_out: Path, best_out: Path) -> None:
    if not results:
        print("No calibration results generated.")
        return
    best = results[0]
    print("Best calibration:")
    print(f"  league_avg: {best.league_avg}")
    print(f"  home_adv: {best.home_adv}")
    print(f"  rho: {best.rho}")
    print(f"  min_training_matches: {best.min_training_matches}")
    print(f"  matches: {best.matches}")
    print(f"  1X2 accuracy: {best.accuracy_1x2:.1%}")
    print(f"  O/U 2.5 accuracy: {best.accuracy_ou25:.1%}")
    print(f"  1X2 log loss: {best.log_loss_1x2:.4f}")
    print(f"  O/U 2.5 log loss: {best.log_loss_ou25:.4f}")
    print(f"  score: {best.score:.4f}")
    print(f"Results written: {results_out}")
    print(f"Best written: {best_out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grid-search calibration for World Cup predictor")
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES, help="Imported match JSON")
    parser.add_argument("--league-avgs", default="1.05,1.15,1.25,1.35,1.45", help="Comma-separated league_avg grid")
    parser.add_argument("--home-advs", default="1.00,1.03,1.06,1.09,1.12", help="Comma-separated home advantage multipliers")
    parser.add_argument("--rhos", default="-0.12,-0.08,-0.04,0.00", help="Comma-separated Dixon-Coles rho grid")
    parser.add_argument("--min-training", default="100,200,300", help="Comma-separated min training matches")
    parser.add_argument("--results-out", type=Path, default=DEFAULT_RESULTS_OUT, help="Calibration CSV output")
    parser.add_argument("--best-out", type=Path, default=DEFAULT_BEST_OUT, help="Best calibration JSON output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    matches = load_matches(args.matches)
    results = run_calibration(
        matches,
        league_avgs=parse_float_grid(args.league_avgs),
        home_advs=parse_float_grid(args.home_advs),
        rhos=parse_float_grid(args.rhos),
        min_training_grid=parse_int_grid(args.min_training),
    )
    write_results(results, args.results_out)
    if results:
        write_best(results[0], args.best_out)
    print_best(results, args.results_out, args.best_out)


if __name__ == "__main__":
    main()
