#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import akshare as ak

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "src"))

from stock_assistant.akshare_provider import AkshareSinaDailyProvider  # noqa: E402
from stock_assistant.strategy_tulong import (  # noqa: E402
    estimate_d1_support,
    evaluate_d1_board,
    hhmm_to_int,
    is_d2_pullback,
    is_d2_balanced_cross,
    safe_float,
)


@dataclass
class OutputPaths:
    report: Path
    csv: Path
    d1_report: Path | None = None
    d1_csv: Path | None = None


@dataclass
class SelectionArgs:
    d1_date: date
    d2_date: date
    d3_date: date | None
    d3_label: str
    timestamp: str
    max_report: int
    max_candidates: int
    project: Path
    d1_only: bool


@dataclass
class Candidate:
    code: str
    name: str
    industry: str
    score: float
    trigger_price: float
    invalid_price: float
    zone_low: float
    zone_high: float
    d1_close: float
    d1_amount: float
    d1_turnover: float
    d1_first_seal: str
    d1_open_breaks: int
    d1_fund: float
    d2_open: float
    d2_high: float
    d2_low: float
    d2_close: float
    d2_pct: float
    d2_amount: float
    d2_turnover: float
    d2_volume_ratio: float
    d2_pullback: float
    above_support: float
    note: str
    flags: str


AUTO_NARROW_EXCLUDE_FLAGS = (
    "高开低走",
    "D2仍大涨",
    "D2走弱",
    "安全垫薄",
    "成交小",
    "成交拥挤",
    "换手过高",
    "量能过大",
    "缩量过弱",
    "上引线过长",
)


def parse_yyyymmdd(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期必须是 YYYYMMDD，例如 20260527：{value}") from exc


def infer_d3_label(d3_date: date) -> str:
    return d3_date.strftime("%m%d") + "D3"


def parse_args(argv: list[str] | None = None) -> SelectionArgs:
    parser = argparse.ArgumentParser(description="生成屠龙 D3 候选池：D1 首板 + D2 确认 + D3 观察标签")
    parser.add_argument("--d1-date", required=True, type=parse_yyyymmdd, help="D1 首板日期，YYYYMMDD")
    parser.add_argument("--d2-date", required=True, type=parse_yyyymmdd, help="D2 确认日期，YYYYMMDD")
    parser.add_argument("--d3-date", type=parse_yyyymmdd, help="D3 观察日期，YYYYMMDD；未传 --d3-label 时用它推导 MMDDD3")
    parser.add_argument("--d3-label", help="D3 标签，例如 0529D3；未传时由 --d3-date 推导")
    parser.add_argument("--timestamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出文件时间戳，默认当前 YYYYMMDD_HHMMSS")
    parser.add_argument("--max-report", type=int, default=30, help="Markdown 报告最多展示多少只候选")
    parser.add_argument("--max-candidates", type=int, default=12, help="CSV 候选池最多输出多少只")
    parser.add_argument("--project", type=Path, default=PROJECT, help="项目根目录")
    parser.add_argument("--d1-only", action="store_true", help="同时输出仅 D1 过滤结果")
    ns = parser.parse_args(argv)
    if not ns.d3_label:
        if not ns.d3_date:
            parser.error("必须传 --d3-label，或传 --d3-date 让脚本推导，例如 20260529 -> 0529D3")
        ns.d3_label = infer_d3_label(ns.d3_date)
    return SelectionArgs(
        d1_date=ns.d1_date,
        d2_date=ns.d2_date,
        d3_date=ns.d3_date,
        d3_label=ns.d3_label,
        timestamp=ns.timestamp,
        max_report=ns.max_report,
        max_candidates=ns.max_candidates,
        project=ns.project,
        d1_only=ns.d1_only,
    )


def build_output_paths(project: Path, d3_label: str, timestamp: str, include_d1: bool = False) -> OutputPaths:
    report_dir = project / "reports" / "daily"
    watch_dir = project / "data" / "watchlists"
    paths = OutputPaths(
        report=report_dir / f"{d3_label}_candidate_scan_{timestamp}.md",
        csv=watch_dir / f"{d3_label}_watch_scan_{timestamp}.csv",
    )
    if include_d1:
        paths.d1_report = report_dir / f"{d3_label}_D1_filtered_{timestamp}.md"
        paths.d1_csv = watch_dir / f"{d3_label}_D1_filtered_{timestamp}.csv"
    return paths


def fmt_yi(x: float) -> str:
    return f"{x / 100000000:.2f}亿"


def entry_zone(trigger: float, invalid: float) -> tuple[float, float]:
    return max(invalid * 1.015, trigger * 0.985), trigger * 1.003



def score_candidate(row, d1, d2, support) -> tuple[float, str, str]:
    vol_ratio = d2.volume / d1.volume if d1.volume else 9.99
    close_below_high = 1 - d2.close / d2.high if d2.high else 0
    above_support = d2.close / support - 1 if support else 0
    high_above_open = d2.high / d2.open - 1 if d2.open else 0
    open_gap = d2.open / d1.close - 1 if d1.close else 0
    amount = d2.amount
    turnover = d2.turnover_rate or 0
    first_seal_i = hhmm_to_int(row.get("首次封板时间"))
    breaks = safe_float(row.get("炸板次数"))
    fund = safe_float(row.get("封板资金"))

    score = 50.0
    notes = []
    flags = []

    if first_seal_i <= 93000:
        score += 8; notes.append("D1早盘封板")
    elif first_seal_i <= 100000:
        score += 5; notes.append("D1较早封板")
    elif first_seal_i >= 140000:
        score -= 5; notes.append("D1尾盘封板降权"); flags.append("尾盘板")
    if breaks == 0:
        score += 5; notes.append("D1未炸板")
    elif breaks <= 2:
        score += 1; notes.append(f"D1炸板{int(breaks)}次")
    else:
        score -= 6; notes.append(f"D1炸板{int(breaks)}次偏多"); flags.append("炸板偏多")
    if fund >= 80_000_000:
        score += 5; notes.append("封板资金较足")
    elif fund < 10_000_000:
        score -= 4; notes.append("封板资金偏弱"); flags.append("封板资金弱")

    if 0.55 <= vol_ratio <= 1.25:
        score += 12; notes.append(f"D2量比温和{vol_ratio:.2f}")
    elif 1.25 < vol_ratio <= 2:
        score += 5; notes.append(f"D2量比略高{vol_ratio:.2f}")
    elif 2 < vol_ratio <= 3:
        score -= 4; notes.append(f"D2量比{vol_ratio:.2f}在2-3倍，需其他条件补强"); flags.append("量能偏大")
    elif vol_ratio < 0.55:
        score -= 10; notes.append(f"D2缩量过弱{vol_ratio:.2f}"); flags.append("缩量过弱")
    else:
        score -= 20; notes.append(f"D2量比超过3倍{vol_ratio:.2f}"); flags.append("量能过大")

    if close_below_high > 0.08:
        score -= 12; notes.append("D2上引线太长"); flags.append("上引线过长")
    elif close_below_high >= 0.05:
        score += 3; notes.append("D2回落充分")
    elif close_below_high >= 0.03:
        score += 5; notes.append("D2有冲高回落")
    elif close_below_high >= 0.02:
        score += 2; notes.append("D2回落刚达标")
    else:
        score -= 8; notes.append("D2回落不足"); flags.append("回落不足")

    if above_support >= 0.04:
        score += 6; notes.append("D2收盘离支撑有安全垫")
    elif above_support >= 0.015:
        score += 3; notes.append("D2未破支撑")
    else:
        score -= 5; notes.append("D2贴近支撑"); flags.append("安全垫薄")

    if high_above_open >= 0.04:
        score += 4; notes.append("D2盘中上冲明显")
    if is_d2_balanced_cross(d2):
        score += 6; notes.append("D2收盘近十字")
    if open_gap > 0.04 and d2.close < d2.open:
        score -= 10; notes.append("D2高开低走风险"); flags.append("高开低走")

    if 200_000_000 <= amount <= 3_000_000_000:
        score += 5; notes.append("成交额可跟踪")
    elif amount < 100_000_000:
        score -= 8; notes.append("成交额偏小"); flags.append("成交小")
    elif amount > 5_000_000_000:
        score -= 5; notes.append("成交额过大偏拥挤"); flags.append("成交拥挤")
    if turnover > 35:
        score -= 8; notes.append("换手过高降噪"); flags.append("换手过高")
    elif 3 <= turnover <= 20:
        score += 3; notes.append("换手适中")

    if d2.pct_chg is not None and d2.pct_chg > 7:
        score -= 10; notes.append("D2仍大涨，容易变追高"); flags.append("D2仍大涨")
    if d2.pct_chg is not None and d2.pct_chg < -5:
        score -= 5; notes.append("D2走弱偏多"); flags.append("D2走弱")

    return score, "；".join(notes), "；".join(flags)


def auto_narrow_candidates(candidates: list[Candidate], limit: int) -> tuple[list[Candidate], list[Candidate]]:
    """Keep D3 scan outputs current by narrowing every generated candidate set."""
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    preferred = [c for c in ranked if not any(flag in c.flags for flag in AUTO_NARROW_EXCLUDE_FLAGS)]
    fallback = [c for c in ranked if c not in preferred]
    selected = (preferred + fallback)[:limit]
    return selected, [c for c in ranked if c not in selected]


def d1_record(row, exclude_reason: str | None = None) -> dict:
    code = str(row["代码"]).zfill(6)
    rec = {
        "code": code,
        "name": str(row["名称"]),
        "industry": str(row.get("所属行业", "")),
        "pct": safe_float(row.get("涨跌幅")),
        "price": safe_float(row.get("最新价")),
        "amount_yi": safe_float(row.get("成交额")) / 1e8,
        "turnover": safe_float(row.get("换手率")),
        "fund_yi": safe_float(row.get("封板资金")) / 1e8,
        "first_seal": str(row.get("首次封板时间", "")),
        "last_seal": str(row.get("最后封板时间", "")),
        "breaks": int(safe_float(row.get("炸板次数"))),
        "stat": str(row.get("涨停统计", "")),
        "limit_boards": int(safe_float(row.get("连板数"))),
    }
    if exclude_reason:
        rec["exclude_reason"] = exclude_reason
    return rec


def write_d1_outputs(paths: OutputPaths, d3_label: str, d1_date: date, zt, kept: list[dict], excluded: list[dict]) -> None:
    if not paths.d1_report or not paths.d1_csv:
        return
    paths.d1_report.parent.mkdir(parents=True, exist_ok=True)
    paths.d1_csv.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {d3_label}：仅按 D1 规则过滤结果",
        "",
        f"D1={d1_date:%Y-%m-%d}。这里只做 D1 层过滤：主板10cm、非ST、首板；尚未应用 D2 确认规则。",
        "",
        f"- D1涨停池总数：{len(zt)}",
        f"- D1规则保留：{len(kept)}",
        f"- D1规则剔除：{len(excluded)}",
        "",
        "## D1规则保留票",
    ]
    for i, r in enumerate(kept, 1):
        lines.append(f'{i}. {r["code"]} {r["name"]}｜{r["industry"]}｜首次封板 {r["first_seal"]}｜炸板 {r["breaks"]}｜封板资金 {r["fund_yi"]:.2f}亿｜成交额 {r["amount_yi"]:.2f}亿｜换手 {r["turnover"]:.2f}%')
    lines.extend(["", "## D1规则剔除样本/原因"])
    for r in excluded:
        lines.append(f'- {r["code"]} {r["name"]}｜{r["industry"]}｜{r.get("exclude_reason", "") }')
    paths.d1_report.write_text("\n".join(lines), encoding="utf-8")
    with paths.d1_csv.open("w", encoding="utf-8", newline="") as f:
        fields = ["code","name","industry","pct","price","amount_yi","turnover","fund_yi","first_seal","last_seal","breaks","stat","limit_boards"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(kept)


def generate(args: SelectionArgs) -> OutputPaths:
    paths = build_output_paths(args.project, args.d3_label, args.timestamp, include_d1=args.d1_only)
    paths.report.parent.mkdir(parents=True, exist_ok=True)
    paths.csv.parent.mkdir(parents=True, exist_ok=True)

    d1_date_str = args.d1_date.strftime("%Y%m%d")
    zt = ak.stock_zt_pool_em(date=d1_date_str)
    provider = AkshareSinaDailyProvider()
    try:
        provider.stock_codes()
    except Exception:
        pass

    raw: list[Candidate] = []
    rejects = []
    d1_kept: list[dict] = []
    d1_excluded: list[dict] = []
    checked = 0
    for _, row in zt.iterrows():
        code = str(row["代码"]).zfill(6)
        name = str(row["名称"])
        industry = str(row.get("所属行业", ""))
        d1_eval = evaluate_d1_board(row)
        if not d1_eval.passed:
            d1_excluded.append(d1_record(row, d1_eval.reject_reason))
            rejects.append((code, name, d1_eval.reject_reason))
            continue
        d1_kept.append(d1_record(row))
        checked += 1
        try:
            bars = provider.history(code, start=args.d1_date, end=args.d2_date)
        except Exception as e:
            rejects.append((code, name, f"日线获取失败：{type(e).__name__}"))
            continue
        by_date = {b.trade_date: b for b in bars}
        d1 = by_date.get(args.d1_date)
        d2 = by_date.get(args.d2_date)
        if not d1 or not d2:
            rejects.append((code, name, "缺D1/D2日线"))
            continue
        support = estimate_d1_support(d1)
        ok, reason = is_d2_pullback(d1, d2, support)
        if not ok:
            rejects.append((code, name, reason))
            continue
        score, note, flags = score_candidate(row, d1, d2, support)
        vol_ratio = d2.volume / d1.volume if d1.volume else 9.99
        pullback = 1 - d2.close / d2.high if d2.high else 0
        zl, zh = entry_zone(d2.close, support)
        if zl > zh:
            rejects.append((code, name, f"观察区倒挂 {zl:.2f}>{zh:.2f}"))
            continue
        raw.append(Candidate(
            code=code, name=name, industry=industry, score=score,
            trigger_price=d2.close, invalid_price=support, zone_low=zl, zone_high=zh,
            d1_close=d1.close, d1_amount=d1.amount, d1_turnover=d1.turnover_rate or 0,
            d1_first_seal=str(row.get("首次封板时间", "")), d1_open_breaks=int(safe_float(row.get("炸板次数"))), d1_fund=safe_float(row.get("封板资金")),
            d2_open=d2.open, d2_high=d2.high, d2_low=d2.low, d2_close=d2.close, d2_pct=d2.pct_chg or 0,
            d2_amount=d2.amount, d2_turnover=d2.turnover_rate or 0, d2_volume_ratio=vol_ratio,
            d2_pullback=pullback, above_support=d2.close / support - 1, note=note, flags=flags,
        ))

    d1_kept.sort(key=lambda r: (hhmm_to_int(r["first_seal"]), r["breaks"], -r["fund_yi"]))
    write_d1_outputs(paths, args.d3_label, args.d1_date, zt, d1_kept, d1_excluded)

    raw.sort(key=lambda c: c.score, reverse=True)
    selected, narrowed_out = auto_narrow_candidates(raw, args.max_candidates)
    report_candidates = selected[:args.max_report]

    lines = [
        f"# {args.d3_label} 自动窄化扫描（D1={args.d1_date:%m%d}首板，D2={args.d2_date:%m%d}确认）",
        "",
        f"- D1首板池日期：{d1_date_str}",
        f"- 主板首板候选检查：{checked} 只",
        f"- 通过D2过滤规则：{len(raw)} 只",
        f"- 自动窄化后输出：{len(selected)} 只",
        "- 说明：每次生成或更新 D3 初选时先自动窄化，后续如有人工修正再另行落盘。",
        "",
        "## 自动窄化保留排序",
    ]
    for i, c in enumerate(report_candidates, 1):
        lines.append(f"### {i}. {c.code} {c.name}｜{c.industry}｜评分 {c.score:.1f}")
        lines.append(f"- 观察价 {c.trigger_price:.2f}｜买点区 {c.zone_low:.2f}–{c.zone_high:.2f}｜失效 {c.invalid_price:.2f}")
        lines.append(f"- D2 收 {c.d2_close:.2f}，高 {c.d2_high:.2f}，低 {c.d2_low:.2f}，涨跌 {c.d2_pct:.2f}%，成交额 {fmt_yi(c.d2_amount)}，换手 {c.d2_turnover:.2f}%")
        lines.append(f"- 结构：D2/D1量比 {c.d2_volume_ratio:.2f}｜高点回落 {c.d2_pullback*100:.1f}%｜安全垫 {c.above_support*100:.1f}%")
        lines.append(f"- D1封板结构：首次封板 {c.d1_first_seal}｜炸板 {c.d1_open_breaks}｜封板资金 {fmt_yi(c.d1_fund)}")
        lines.append(f"- note：{c.note}")
        if c.flags:
            lines.append(f"- 风险标记：{c.flags}")
        lines.append("")
    lines.append("## 部分剔除原因样本")
    for code, name, why in rejects[:40]:
        lines.append(f"- {code} {name}：{why}")
    if narrowed_out:
        lines.extend(["", "## 自动窄化未输出"])
        for c in narrowed_out[:40]:
            why = c.flags or "容量限制"
            lines.append(f"- {c.code} {c.name}：{why}")

    paths.report.write_text("\n".join(lines), encoding="utf-8")
    with paths.csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["code","name","industry","stage","pool_type","source_file","trigger_price","invalid_price","zone_low","zone_high","rank","score","note"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, c in enumerate(selected, 1):
            w.writerow({
                "code": c.code, "name": c.name, "industry": c.industry, "stage": args.d3_label, "pool_type": "watch",
                "source_file": paths.csv.name, "trigger_price": f"{c.trigger_price:.2f}", "invalid_price": f"{c.invalid_price:.2f}",
                "zone_low": f"{c.zone_low:.2f}", "zone_high": f"{c.zone_high:.2f}", "rank": i, "score": f"{c.score:.1f}",
                "note": f"{args.d3_label}｜watch｜scan｜{c.note}",
            })
    return paths


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = generate(args)
    print(f"REPORT={paths.report}")
    print(f"CSV={paths.csv}")
    if paths.d1_report:
        print(f"D1_REPORT={paths.d1_report}")
    if paths.d1_csv:
        print(f"D1_CSV={paths.d1_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
