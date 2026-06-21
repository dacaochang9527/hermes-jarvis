# Futures Feishu Trading Session Updates

Use this when expanding a futures Feishu monitor from day-only to day + night sessions, or when changing active trading hours.

## Update all three layers

1. Monitor config
   - Update `configs/<contract>_feishu_monitor.yaml`.
   - Keep `trading_sessions.day_session` and `trading_sessions.night_session` explicit.
   - PVC night session currently uses `21:00-23:00`.

2. Runtime scripts
   - Update both event monitor and fixed-interval briefing scripts.
   - Keep `DAY_SESSIONS`, `NIGHT_SESSIONS`, and `in_session()` aligned.
   - Do not rely on cron alone; scripts should remain silent outside configured sessions.

3. Cron schedules
   - Include the same active hours as the scripts.
   - PVC day + night pattern:
     - Event monitor: `* 9-15,21-23 * * 1-5`
     - Briefing monitor: `*/5 9-15,21-23 * * 1-5`

## Verification

Run syntax checks and direct session checks after edits:

- `python3 -m py_compile pvc2609_event_monitor.py pvc2609_half_hour_briefing.py`
- Verify both scripts return:
  - day session, e.g. Monday `09:30` → true
  - day break, e.g. Monday `10:20` → false
  - night session, e.g. Monday `21:30` → true
  - after night, e.g. Monday `23:30` → false
  - weekend night → false

## Pitfalls

- Updating only cron makes jobs wake up at night, but scripts may still return silently if `in_session()` is day-only.
- Updating only scripts does not help if cron never runs during night hours.
- Reuse of day-session state may be acceptable for continuous monitoring, but if cooldown or last-price behavior becomes noisy, split state by `day` / `night` session label.
