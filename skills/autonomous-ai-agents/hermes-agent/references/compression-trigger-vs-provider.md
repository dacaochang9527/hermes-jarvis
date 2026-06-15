# Compression configured but context still grows

Use this when the user asks why Hermes did not compress even though `auxiliary.compression` is configured.

## Key distinction

`auxiliary.compression` only chooses which model performs summarization after compression is triggered. It does not decide when compression triggers.

Automatic compression is driven primarily by:

- `model.context_length`
- `compression.threshold`
- current prompt/input tokens

Effective trigger point:

```text
threshold_tokens = model.context_length * compression.threshold
```

If `model.context_length` is manually set very high, e.g. `1048576`, and `compression.threshold` is `0.25`, Hermes will not auto-compress until roughly `262144` tokens. A 120k–140k token prompt can therefore be below the configured threshold even if the upstream model/proxy is already unstable at that size.

## Diagnostic checklist

1. Check `~/.hermes/logs/agent.log` for the target turn:
   - `conversation turn`
   - `API call #... in=...`
   - `Fallback activated`
   - `context-overflow failure`
2. Check whether there are actual compression calls around the turn:
   - `compression`
   - `compress`
   - `Auxiliary compression`
3. Inspect config values:
   - `model.context_length`
   - `compression.threshold`
   - `compression.target_ratio`
   - `auxiliary.compression.provider/model/context_length`
4. Calculate the trigger point. Do not infer that compression failed unless logs show a compression attempt.

## Interpretation pattern

- If no compression call appears, the likely cause is “compression did not trigger,” not “the compression model failed.”
- If `model.context_length` is larger than the provider’s practical stable window, Hermes may delay compression too long.
- Gateway long sessions can grow through many tool calls even with compression enabled if the threshold is calculated against an overly optimistic context length.

## Practical mitigation

For custom/OpenAI-compatible proxy models whose advertised context is larger than their stable serving window, set `model.context_length` to the practical stable value, not the theoretical maximum. Examples: `128000` or `200000`.

With `model.context_length: 128000` and `compression.threshold: 0.25`, compression triggers around `32000` tokens, which is much safer for long gateway sessions.

Also verify fallback models that support reasoning/thinking mode. If a DeepSeek fallback errors with `reasoning_content ... must be passed back`, treat that as a fallback message-format compatibility issue, not as evidence that compression was attempted.