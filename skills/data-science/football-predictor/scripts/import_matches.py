"""Import and filter international football match results for World Cup 2026 modeling."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.request import urlopen

DEFAULT_SOURCE_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DEFAULT_START_DATE = date(2014, 6, 12)
INCLUDED_TOURNAMENTS = {"FIFA World Cup", "FIFA World Cup qualification"}

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DEFAULT_JSON_OUT = DATA_DIR / "world_cup_matches_2014_onward.json"
DEFAULT_CSV_OUT = DATA_DIR / "world_cup_matches_2014_onward.csv"


@dataclass(frozen=True)
class ImportedMatch:
    date: str
    home: str
    away: str
    home_goals: int
    away_goals: int
    competition: str
    is_neutral: bool
    city: str
    venue_country: str
    source: str


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y"}


def read_csv_rows(source: str) -> list[dict[str, str]]:
    if source.startswith("http://") or source.startswith("https://"):
        with urlopen(source, timeout=60) as response:
            text = response.read().decode("utf-8")
    else:
        text = Path(source).read_text()
    return list(csv.DictReader(text.splitlines()))


def normalize_row(row: dict[str, str], source_label: str) -> ImportedMatch:
    return ImportedMatch(
        date=row["date"],
        home=row["home_team"],
        away=row["away_team"],
        home_goals=int(row["home_score"]),
        away_goals=int(row["away_score"]),
        competition=row["tournament"],
        is_neutral=parse_bool(row["neutral"]),
        city=row.get("city", ""),
        venue_country=row.get("country", ""),
        source=source_label,
    )


def filter_world_cup_scope(rows: list[dict[str, str]], start_date: date, source_label: str) -> list[ImportedMatch]:
    matches: list[ImportedMatch] = []
    for row in rows:
        match_date = date.fromisoformat(row["date"])
        if match_date < start_date:
            continue
        if row["tournament"] not in INCLUDED_TOURNAMENTS:
            continue
        if row["home_score"] == "NA" or row["away_score"] == "NA":
            continue
        matches.append(normalize_row(row, source_label))
    return sorted(matches, key=lambda match: (match.date, match.home, match.away))


def write_json(matches: list[ImportedMatch], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(match) for match in matches], indent=2, ensure_ascii=False))


def write_csv(matches: list[ImportedMatch], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ImportedMatch.__dataclass_fields__.keys())
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            writer.writerow(asdict(match))


def print_summary(matches: list[ImportedMatch]) -> None:
    competitions: dict[str, int] = {}
    teams: set[str] = set()
    for match in matches:
        competitions[match.competition] = competitions.get(match.competition, 0) + 1
        teams.add(match.home)
        teams.add(match.away)

    print(f"Imported matches: {len(matches)}")
    print(f"Teams: {len(teams)}")
    if matches:
        print(f"Date range: {matches[0].date} → {matches[-1].date}")
    for competition, count in sorted(competitions.items()):
        print(f"  {competition}: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import World Cup finals + qualifiers from international results CSV")
    parser.add_argument("--source", default=DEFAULT_SOURCE_URL, help="CSV URL or local path")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE.isoformat(), help="Inclusive start date, default 2014-06-12")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT, help="Output JSON path")
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV_OUT, help="Output CSV path")
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)
    rows = read_csv_rows(args.source)
    matches = filter_world_cup_scope(rows, start_date, source_label=args.source)
    write_json(matches, args.json_out)
    if not args.no_csv:
        write_csv(matches, args.csv_out)
    print_summary(matches)
    print(f"JSON written: {args.json_out}")
    if not args.no_csv:
        print(f"CSV written: {args.csv_out}")


if __name__ == "__main__":
    main()
