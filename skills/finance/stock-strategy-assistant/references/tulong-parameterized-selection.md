# Parameterized D3 selection generator

Use this when converting dated one-off D3 selection scripts into a reusable generator.

## Problem pattern

One-off scripts often hardcode:

```python
D1_DATE_STR = '20260527'
D1_DATE = date(2026, 5, 27)
D2_DATE = date(2026, 5, 28)
D3_LABEL = '0529D3'
report_path = out_dir / '0529D3_candidate_scan.md'
csv_path = watch_dir / '0529D3_watch_scan_214437.csv'
```

This makes the script unsuitable for tomorrow's pool and encourages copying scripts daily.

## Recommended replacement

Create one reusable script, normally:

```text
scripts/tulong/selection/generate_d3_candidates.py
```

CLI shape:

```bash
.venv/bin/python scripts/tulong/selection/generate_d3_candidates.py \
  --d1-date 20260527 \
  --d2-date 20260528 \
  --d3-date 20260529 \
  --timestamp 214437 \
  --d1-only
```

Arguments:

- `--d1-date YYYYMMDD`: D1 first-board date used for `ak.stock_zt_pool_em(date=...)`.
- `--d2-date YYYYMMDD`: D2 confirmation date used for daily bar lookup.
- `--d3-date YYYYMMDD`: optional; derive `MMDDD3`, e.g. `20260529 -> 0529D3`.
- `--d3-label 0529D3`: optional explicit label; required if `--d3-date` is omitted.
- `--timestamp HHMMSS`: optional deterministic output suffix; default current time.
- `--max-candidates`: rows in watch CSV.
- `--max-report`: candidates shown in Markdown.
- `--d1-only`: also emit D1-only filtered report/CSV.

Output naming:

```text
reports/daily/{D3_LABEL}_candidate_scan_{HHMMSS}.md
data/watchlists/{D3_LABEL}_watch_scan_{HHMMSS}.csv
reports/daily/{D3_LABEL}_D1_filtered_{HHMMSS}.md        # when --d1-only
data/watchlists/{D3_LABEL}_D1_filtered_{HHMMSS}.csv     # when --d1-only
```

Keep old dated scripts temporarily as historical references or move them to `legacy/`; do not keep copying new dated scripts.

## Implementation notes

- Keep pure helpers testable: `parse_yyyymmdd`, `infer_d3_label`, `parse_args`, `build_output_paths`.
- Use `Path(__file__).resolve().parents[3]` or another repo-relative approach instead of hardcoding the user's absolute project root inside the reusable generator.
- Keep D1-only output and D1+D2 candidate generation in one script when they share the same source date and output label; this prevents D1 and D3 outputs from drifting.
- The production `runtime/` scripts should not import dated selection scripts. Selection outputs become watchlist inputs only after explicit review/copy/rotation.

## Rule implementation boundary

D1 hard-filter rules must not live only inside the selection CLI. The reusable generator may orchestrate data fetching and file output, but rule predicates should be imported from `src/stock_assistant/strategy_tulong.py`.

If a generator contains helpers such as:

```python
EXCLUDE_PREFIXES = ("300", "301", "688", "689", "8", "4")
EXCLUDE_NAME_PARTS = ("ST", "*ST", "退")
def is_d1_main_board_first_limit(row): ...
```

refactor them downward into `strategy_tulong.py`, then update the generator to call the shared function. Add tests in `tests/test_tulong.py` or a nearby test file for:

- main-board 10cm passes;
- `300/301/688/689/8/4` prefixes reject;
- ST / *ST / 退 names reject;
- `涨停统计` starts with `1/` or `连板数 == 1` passes;
- non-first-board rows reject with a readable reason.

After this refactor, update project docs (`scripts/tulong/README.md`) and the relevant skill reference in the same change. Do not leave documentation saying the implementation lives in the selection script.

## Cleanup rule

After `generate_d3_candidates.py` is verified for the same date/label as a dated one-off script, delete the superseded one-off scripts rather than keeping multiple sources of truth in `selection/`. Update the project README at the same time.

For the 0529D3 migration, these one-off scripts were removed after replacement by the parameterized generator:

```text
scripts/tulong/selection/list_0529d3_d1_filtered.py
scripts/tulong/selection/select_0529d3_candidates.py
```

The selection directory should normally keep only reusable generators plus any genuinely still-active research script.

## Verification

Add or update tests before implementation when feasible:

```text
tests/test_tulong_selection_cli.py
```

Minimum tests:

- explicit `--d1-date/--d2-date/--d3-label` parsing;
- `--d3-date` infers `MMDDD3`;
- output paths include `{D3_LABEL}` and `{timestamp}`.

Run:

```bash
.venv/bin/python -m pytest tests/test_tulong.py tests/test_tulong_selection_cli.py -q
.venv/bin/python -m py_compile scripts/tulong/selection/generate_d3_candidates.py
```

Then run one real historical example and check the generated report/CSV line counts.

## Importlib/dataclass test pitfall

If a test loads a standalone script with `importlib.util.module_from_spec`, insert it into `sys.modules` before `exec_module`; otherwise `@dataclass` can fail while resolving string annotations:

```python
spec = importlib.util.spec_from_file_location('generate_d3_candidates', MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
```
