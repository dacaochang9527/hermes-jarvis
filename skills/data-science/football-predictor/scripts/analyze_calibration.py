"""Probability calibration analysis for football predictor backtests."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT_DIR / "reports"
DEFAULT_BACKTEST = REPORTS_DIR / "backtest_predictions.csv"
DEFAULT_BINS_OUT = REPORTS_DIR / "probability_calibration_bins.csv"
DEFAULT_MD_OUT = REPORTS_DIR / "probability_calibration_report.md"


@dataclass(frozen=True)
class CalibrationBin:
    market: str
    selection: str
    bin_start: float
    bin_end: float
    count: int
    avg_predicted_probability: float
    observed_frequency: float
    calibration_error: float


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as file:
        return list(csv.DictReader(file))


def bin_bounds(probability: float, bin_width: float) -> tuple[float, float]:
    start = int(probability / bin_width) * bin_width
    if start >= 1.0:
        start = 1.0 - bin_width
    return round(start, 10), round(start + bin_width, 10)


def append_event(
    buckets: dict[tuple[str, str, float, float], list[tuple[float, int]]],
    market: str,
    selection: str,
    probability: float,
    hit: bool,
    bin_width: float,
) -> None:
    start, end = bin_bounds(probability, bin_width)
    key = (market, selection, start, end)
    buckets.setdefault(key, []).append((probability, 1 if hit else 0))


def build_bins(rows: list[dict[str, str]], bin_width: float = 0.1, min_count: int = 20) -> list[CalibrationBin]:
    buckets: dict[tuple[str, str, float, float], list[tuple[float, int]]] = {}

    for row in rows:
        actual_1x2 = row["actual_1x2"]
        append_event(buckets, "1X2", "home", float(row["home_win_prob"]), actual_1x2 == "home", bin_width)
        append_event(buckets, "1X2", "draw", float(row["draw_prob"]), actual_1x2 == "draw", bin_width)
        append_event(buckets, "1X2", "away", float(row["away_win_prob"]), actual_1x2 == "away", bin_width)

        actual_ou25 = row["actual_ou25"]
        append_event(buckets, "OU25", "over", float(row["over25_prob"]), actual_ou25 == "over", bin_width)
        append_event(buckets, "OU25", "under", float(row["under25_prob"]), actual_ou25 == "under", bin_width)

    bins: list[CalibrationBin] = []
    for (market, selection, start, end), events in sorted(buckets.items()):
        if len(events) < min_count:
            continue
        avg_probability = sum(prob for prob, _ in events) / len(events)
        observed = sum(hit for _, hit in events) / len(events)
        bins.append(
            CalibrationBin(
                market=market,
                selection=selection,
                bin_start=start,
                bin_end=end,
                count=len(events),
                avg_predicted_probability=avg_probability,
                observed_frequency=observed,
                calibration_error=observed - avg_probability,
            )
        )
    return bins


def expected_calibration_error(bins: list[CalibrationBin]) -> dict[str, float]:
    totals: dict[str, int] = {}
    weighted_errors: dict[str, float] = {}
    for item in bins:
        totals[item.market] = totals.get(item.market, 0) + item.count
        weighted_errors[item.market] = weighted_errors.get(item.market, 0.0) + item.count * abs(item.calibration_error)
    return {market: weighted_errors[market] / totals[market] for market in totals}


def write_bins(bins: list[CalibrationBin], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(CalibrationBin.__dataclass_fields__.keys())
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in bins:
            writer.writerow(item.__dict__)


def write_markdown(bins: list[CalibrationBin], path: Path) -> None:
    ece = expected_calibration_error(bins)
    lines = [
        "# Probability Calibration Report",
        "",
        "This report compares predicted probabilities with observed hit rates by probability bucket.",
        "Positive calibration error means the event happened more often than predicted; negative means the model overestimated it.",
        "",
        "## Summary",
        "",
    ]
    for market, value in sorted(ece.items()):
        lines.append(f"- `{market}` expected calibration error: `{value:.3f}`")
    lines.extend(["", "## Bins", ""])

    for market in sorted({item.market for item in bins}):
        lines.extend([f"### {market}", ""])
        lines.append("| Selection | Bin | Count | Avg Pred | Observed | Error |")
        lines.append("|-----------|-----|-------|----------|----------|-------|")
        for item in [bin_item for bin_item in bins if bin_item.market == market]:
            lines.append(
                f"| {item.selection} | {item.bin_start:.1f}-{item.bin_end:.1f} | {item.count} | "
                f"{item.avg_predicted_probability:.1%} | {item.observed_frequency:.1%} | {item.calibration_error:+.1%} |"
            )
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def print_summary(bins: list[CalibrationBin], bins_out: Path, md_out: Path) -> None:
    ece = expected_calibration_error(bins)
    print("Probability calibration summary:")
    for market, value in sorted(ece.items()):
        print(f"  {market} ECE: {value:.3f}")
    worst = sorted(bins, key=lambda item: abs(item.calibration_error), reverse=True)[:5]
    print("Largest bucket errors:")
    for item in worst:
        print(
            f"  {item.market}/{item.selection} {item.bin_start:.1f}-{item.bin_end:.1f}: "
            f"pred {item.avg_predicted_probability:.1%}, obs {item.observed_frequency:.1%}, "
            f"err {item.calibration_error:+.1%}, n={item.count}"
        )
    print(f"Bins written: {bins_out}")
    print(f"Report written: {md_out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze probability calibration from backtest predictions")
    parser.add_argument("--backtest", type=Path, default=DEFAULT_BACKTEST, help="Backtest predictions CSV")
    parser.add_argument("--bin-width", type=float, default=0.1, help="Probability bin width")
    parser.add_argument("--min-count", type=int, default=20, help="Minimum observations per bin")
    parser.add_argument("--bins-out", type=Path, default=DEFAULT_BINS_OUT, help="Calibration bins CSV output")
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT, help="Markdown report output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = read_rows(args.backtest)
    bins = build_bins(rows, bin_width=args.bin_width, min_count=args.min_count)
    write_bins(bins, args.bins_out)
    write_markdown(bins, args.md_out)
    print_summary(bins, args.bins_out, args.md_out)


if __name__ == "__main__":
    main()
