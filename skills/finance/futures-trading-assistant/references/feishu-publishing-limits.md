# Feishu Document Publishing Limits & Workarounds

## 1000-Block Descendant Limit

The Feishu `POST /docx/v1/documents/{id}/blocks/{id}/descendant` endpoint rejects requests where `descendants` array exceeds 1000 blocks:

- Error: `code 99992402, "the max len is 1000"`
- This is a hard limit; do not attempt to send >1000 blocks in a single call.

### Chunking Does NOT Work

The descendant endpoint is designed for one-shot document population. Calling it a second time:
- Without `children_id` → `code 1770041 "open schema mismatch"`
- With `children_id: []` → same error
- With the original `children_id` → replaces first batch's children

**Do not build multi-call chunking into the publisher script.** It will fail.

### Working Solution: Pre-Trim Markdown

Trim the markdown before conversion to stay under 1000 blocks:

```python
import re

# 1. Strip STATE_HANDOFF code block (machine-only, saves ~10 blocks)
md = re.sub(r'\n```text\nSTATE_HANDOFF\n.*?\n```\n', '\n', md, flags=re.DOTALL)

# 2. Strip optional sections (e.g., Section 18 小资金点数现实, saves ~65 blocks)
md = re.sub(r'\n## 18\. 小资金点数现实与风险可行性\n.*?(?=\n## 19\.)', '', md, flags=re.DOTALL)
```

Typical block counts for a full 20-section PVC review:
- Full: ~1008 blocks
- Without STATE_HANDOFF: ~1007 blocks
- Without STATE_HANDOFF + Section 18: ~943 blocks
- Without Sections 13-18 (detailed plans): ~724 blocks

Target well under 1000 — 900-950 is safe. The trimmed Feishu version loses no analytical content; the trade mechanics table (Section 18) and the machine-only STATE_HANDOFF are the least critical for online reading.

### Script-Level Guard

The `publish_feishu_markdown_doc.py` should check block count after conversion and fail with a clear message if >1000, rather than silently hitting the API limit. Consider:

```python
if len(blocks) > 1000:
    raise PublishError(f"Document has {len(blocks)} blocks (limit: 1000). "
                       f"Trim markdown before publishing.")
```

## Monitor Plan-Loading Timing Issue

When a day session review generates a new prediction plan (e.g., `day_review_night_plan.md`), the Feishu monitor for the next session should load the NEW plan's prediction levels. However, if the monitor starts before the new plan is generated or deployed:

- The monitor loads the OLD plan's `latest_prediction_levels.json`
- Alert triggers fire against stale levels
- Verification in Section 5 of the review must note which plan the monitor actually used

**Best practice**: After finalizing a day/night review, run `--update-levels` (on a reviewed plan) to push new prediction levels to `runtime/pvc2609_feishu_monitor/latest_prediction_levels.json` BEFORE the next session's monitor starts.

If the timing gap cannot be closed (e.g., day review finishes during the evening break after night monitor already started), note the discrepancy in the next review's Section 7 (命中/偏差归因) so the reader knows which plan the alerts were tested against.
