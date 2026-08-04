#!/usr/bin/env python3
"""Create the first PVC2701 review without inventing a prior prediction."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from pvc2701_adapter import load_generator, load_publisher


generator = load_generator()
publisher = load_publisher()


def parse_date(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


def mark_as_bootstrap(markdown: str) -> str:
    markdown = markdown.replace(
        "> 前序计划：`未找到`",
        "> 前序计划：`首期建档，无前序预测；从本报告开始建立可验证基线`",
    )
    bootstrap_section = """## 5. 前序计划逐项验证

本报告是 PVC2701 跟踪链的首期建档。此前没有由本 Skill 在交易前生成的可验证计划，因此本节不评价方向命中率，也不使用已发生行情倒推“预测正确”。从本报告给出的下一时段 A/B/C/D/E 条件化方案开始，后续复盘将逐项记录触发、确认、失效与执行含义。

| 前序方案 | 计划触发 | 实际路径 | 匹配状态 | 原因 | 执行含义 |
|---|---|---|---|---|---|
| 首期建档 | 无前序预测 | 以本报告行情摘要为准 | 不适用 | 防止事后归因与虚构命中率 | 从下一时段开始按方案编号严格复盘 |
"""
    markdown = re.sub(
        r"## 5\. 前序计划逐项验证\n.*?(?=\n## 6\.)",
        bootstrap_section.rstrip(),
        markdown,
        flags=re.DOTALL,
    )
    markdown = re.sub(
        r"invalidated_levels:\n(?:  - price: TBD\n    reason:.*\n)?",
        "invalidated_levels: []\n",
        markdown,
    )
    return markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap the first PVC2701 review and Feishu document.")
    parser.add_argument("--target", required=True, choices=tuple(publisher.TARGETS))
    parser.add_argument("--date", required=True, type=parse_date)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = publisher.TARGETS[args.target]
    review_date, next_date = publisher.resolve_dates(spec, args.date)
    output = publisher.report_path_for(args.date, spec, None)
    output.parent.mkdir(parents=True, exist_ok=True)

    klines = {minutes: generator.fetch_klines(minutes) for minutes in generator.MINUTE_PERIODS}
    daily = generator.fetch_daily()
    session_rows = generator.bars_for_session(klines.get(3, []), review_date, spec.review_session)
    if not session_rows:
        raise RuntimeError(f"{review_date:%Y-%m-%d} {generator.session_title(spec.review_session)} 3m K线不足")
    live_quote = generator.parse_quote(generator.fetch_text(generator.QUOTE_URL))
    quote = generator.select_review_quote(live_quote, session_rows, review_date, spec.review_session)
    generator_args = publisher.make_generator_args(review_date, next_date, spec, output, not args.dry_run)
    markdown, prediction_payload = generator.build_report(generator_args, quote, klines, daily, None)
    markdown = mark_as_bootstrap(markdown)
    prediction_payload.setdefault("_quality", {})["prior_report"] = "bootstrap:first_issue"

    publisher.validate_report_bundle(markdown, prediction_payload, review_date, spec, Path("BOOTSTRAP_FIRST_ISSUE"))
    publisher.atomic_write_text(output, markdown)
    publisher.validate_level_sanity(output)
    if not args.dry_run:
        generator.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        publisher.atomic_write_text(
            generator.PREDICTION_LEVELS_PATH,
            json.dumps(generator.runtime_prediction_payload(prediction_payload), ensure_ascii=False, indent=2),
        )

    title = f"PVC2701 {args.date:%Y-%m-%d} {spec.title_session}复盘+预测（首期建档）"
    published = publisher.publish_report(output, title, args.dry_run)
    url = published.get("url") or published.get("document_url") or f"DRY-RUN:{output}"
    print(publisher.build_group_message(title, url, publisher.extract_summary(output), output, args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

