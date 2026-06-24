# Gateway Display Platform Overrides

Use this when a user reports that a Feishu/Telegram/Slack/etc. display setting appears ignored even after restarting the gateway.

## Symptom

A config such as:

```yaml
display:
  interim_assistant_messages: true
  platforms:
    feishu:
      interim_assistant_messages: false
```

still produces Feishu mid-turn assistant commentary messages.

## Diagnostic Pattern

1. Check the user's effective `~/.hermes/config.yaml` and confirm both the global setting and `display.platforms.<platform>` override.
2. Search the source for the setting name.
3. Compare the call site with `tool_progress` or another known-good setting.
4. Settings that should support platform overrides must be read via `gateway.display_config.resolve_display_setting(user_config, platform_key, <setting>, <fallback>)`, not by direct `display_config.get(<setting>)`.
5. Confirm the setting is present in `gateway/display_config.py` `_GLOBAL_DEFAULTS` / `OVERRIDEABLE_KEYS` and normalized if it is boolean-like.
6. Add a regression test in `tests/gateway/test_run_progress_topics.py` or the relevant gateway test module using a config with global enabled and platform disabled.

## Fix Pattern

For `interim_assistant_messages`, the fix was:

- Add `"interim_assistant_messages": True` to display resolver defaults and platform tiers where appropriate.
- Normalize it alongside other boolean display settings.
- Replace direct reads in `gateway/run.py` with `resolve_display_setting(...)`.
- Restart the gateway after the code change.

## Verification

Minimal verification without installing extra test dependencies:

```bash
venv/bin/python -m py_compile gateway/display_config.py gateway/run.py tests/gateway/test_run_progress_topics.py
venv/bin/python - <<'PY'
from gateway.display_config import resolve_display_setting
cfg={'display': {'interim_assistant_messages': True, 'platforms': {'feishu': {'interim_assistant_messages': False}}}}
print(resolve_display_setting(cfg, 'feishu', 'interim_assistant_messages', True))
print(resolve_display_setting(cfg, 'telegram', 'interim_assistant_messages', True))
PY
```

Expected output:

```text
False
True
```

If pytest is available, also run the focused gateway tests for interim commentary/platform overrides.
