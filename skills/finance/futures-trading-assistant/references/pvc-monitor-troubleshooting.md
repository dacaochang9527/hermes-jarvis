# PVC Futures Monitor Troubleshooting Notes

Use this reference when maintaining PVC futures Feishu monitors, especially no-agent cron jobs and event-driven alert scripts.

## Durable Patterns

- Hermes no-agent cron `script` values should point to files under `~/.hermes/scripts/`. If business logic lives inside the skill directory, create a thin shell wrapper in `~/.hermes/scripts/` that `cd`s into the skill directory and runs the Python script.
- Keep business logic in the skill directory and wrapper logic minimal, so code and documentation remain versionable inside the skill.
- When one parser bug appears in quote handling, patch every runtime entry that parses the same quote source: event monitor, half-hour briefing, day pre-open guard, and night pre-open guard if separate.
- After a false event caused by bad state, reset or sanitize the local state file and add code that rejects impossible previous values such as `last_price <= 0`.

## Sina Quote Compatibility

For `https://hq.sinajs.cn/list=nf_V2609`, the latest-price field may be `0.000` during active trading while bid/ask are valid. Treat `last <= 0` as unavailable and fall back to `(bid + ask) / 2` when both sides are positive. If no valid price can be derived, fail closed and avoid generating an alert.

## Manual Scenario Levels

If a group member or user highlights a concrete scenario level that later proves structurally important, promote it to an explicit key level after verification. Do not hide these levels inside dynamic support/resistance calculations.

Common examples:

- Prior settlement / reference price.
- Prior trading-day low or high.
- Named scenario pressure/support from the group discussion.
- Round-number or previous-low support zones that appear in the current plan.

When adding manual scenario levels, verify with historical 3m or 15m bars that a crossing would have triggered at the expected time, and keep dedupe keyed by the specific level.

## Event Alert Noise Control

- A-level key-level alerts should not use 60-second cooldown for normal support/resistance or prediction-level crossings. Use about 10 minutes unless the event is a true risk event such as stop-loss, invalidation, or take-profit.
- One unfinished 3m bar can be observed by multiple 1-minute cron ticks. Persist the last sent 3m bar identity per dedupe key so the same bar cannot generate repeated pushes.
- Same-level chop guard must be stateful. Track repeated crossings per event key + level; after about 3 repeated crosses, suppress group pushes for about 30 minutes and only keep local logs until price leaves the level by a reset distance.
- When adding suppression state inside event classification, ensure the modified state is later saved by the normal state-write path; otherwise the cron's next tick will lose the dedupe metadata.

## Verification Steps

1. Run syntax checks for changed Python scripts.
2. Execute the wrapper directly once if it is safe and non-destructive.
3. Inspect cron status/output to confirm the scheduler sees the wrapper and no longer reports missing scripts.
4. Replay or simulate representative crossings for newly added key levels.
5. Update alert-design documentation when a manual level becomes part of runtime behavior.
