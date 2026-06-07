#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import akshare as ak

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "src"))

from stock_assistant.akshare_provider import AkshareSinaDailyProvider
from stock_assistant.strategy_tulong import (
    ACTIVE_POOL_CAP,
    RADAR_POOL_CAP,
    D3CandidateProfile,
    d3_entry_comfort,
    d3_pool_subtype,
    estimate_d1_support,
    evaluate_d1_board,
    hhmm_to_int,
    safe_float,
)

D1_DATE = date(2026, 6, 2)
D2_DATE = date(2026, 6, 3)
D3_LABEL = "0604D3"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT = PROJECT / f"reports/daily/{D3_LABEL}_new_strategy_full_scan_{TIMESTAMP}.md"
CSV = PROJECT / f"data/watchlists/{D3_LABEL}_new_strategy_full_watch_scan_{TIMESTAMP}.csv"
D1_REPORT = PROJECT / f"reports/daily/{D3_LABEL}_new_strategy_D1_filtered_{TIMESTAMP}.md"
D1_CSV = PROJECT / f"data/watchlists/{D3_LABEL}_new_strategy_D1_filtered_{TIMESTAMP}.csv"

@dataclass
class D1Row:
    code: str
    name: str
    industry: str
    pct: float
    price: float
    amount_yi: float
    turnover: float
    fund_yi: float
    first_seal: str
    last_seal: str
    breaks: int
    stat: str
    limit_boards: int
    d1_score: float
    d1_note: str
    d1_risk: str

@dataclass
class Pick:
    d1: D1Row
    score: float
    trigger: float
    invalid: float
    zone_low: float
    zone_high: float
    rank_reason: str
    risk: str
    d2_open: float
    d2_high: float
    d2_low: float
    d2_close: float
    d2_pct: float
    vol_ratio: float
    body_ratio: float
    close_below_high: float
    upper_shadow_ratio: float
    open_gap: float
    amount: float
    turnover: float


def fmt_yi(x: float) -> str:
    return f"{x / 100000000:.2f}亿"


def pick_profile(pick: Pick) -> D3CandidateProfile:
    return D3CandidateProfile(
        score=pick.score,
        trigger_price=pick.trigger,
        invalid_price=pick.invalid,
        zone_low=pick.zone_low,
        zone_high=pick.zone_high,
        d2_pullback=pick.close_below_high,
        flags=pick.risk,
    )


def pick_pool_subtype(pick: Pick) -> str:
    return d3_pool_subtype(pick_profile(pick))


def d1_record(row) -> D1Row:
    first_seal = str(row.get("首次封板时间", ""))
    last_seal = str(row.get("最后封板时间", ""))
    breaks = int(safe_float(row.get("炸板次数")))
    fund_yi = safe_float(row.get("封板资金")) / 1e8
    amount_yi = safe_float(row.get("成交额")) / 1e8
    turnover = safe_float(row.get("换手率"))
    first_i = hhmm_to_int(first_seal)
    last_i = hhmm_to_int(last_seal)
    notes = []
    risks = []
    score = 50.0

    if first_i <= 93000:
        score += 12; notes.append("早盘快速封板")
    elif first_i <= 100000:
        score += 9; notes.append("上午较早封板")
    elif first_i <= 113000:
        score += 5; notes.append("上午封板")
    elif first_i >= 140000:
        score -= 18; notes.append("尾盘封板/偷袭嫌疑"); risks.append("尾盘板")
    else:
        score -= 6; notes.append("午后封板降级"); risks.append("午后板")

    if breaks == 0:
        score += 8; notes.append("未炸板")
    elif breaks <= 2:
        score += 2; notes.append(f"炸板{breaks}次可接受")
    elif breaks <= 5:
        score -= 12; notes.append(f"炸板{breaks}次偏多"); risks.append("炸板偏多")
    else:
        score -= 24; notes.append(f"炸板{breaks}次过多"); risks.append("反复烂板")

    if last_i and first_i and last_i - first_i > 30000 and breaks >= 3:
        score -= 10; notes.append("长时间封不住"); risks.append("封板不稳")
    if fund_yi >= 1.0:
        score += 8; notes.append("封板资金强")
    elif fund_yi >= 0.5:
        score += 4; notes.append("封板资金尚可")
    elif fund_yi < 0.1:
        score -= 10; notes.append("封板资金弱"); risks.append("封板资金弱")
    if amount_yi < 1:
        score -= 8; notes.append("成交额过小"); risks.append("成交小")
    elif amount_yi > 50:
        score -= 6; notes.append("成交额偏拥挤"); risks.append("成交拥挤")
    if turnover > 30:
        score -= 8; notes.append("换手过高"); risks.append("换手过高")

    return D1Row(
        code=str(row["代码"]).zfill(6), name=str(row["名称"]), industry=str(row.get("所属行业", "")),
        pct=safe_float(row.get("涨跌幅")), price=safe_float(row.get("最新价")), amount_yi=amount_yi,
        turnover=turnover, fund_yi=fund_yi, first_seal=first_seal, last_seal=last_seal,
        breaks=breaks, stat=str(row.get("涨停统计", "")), limit_boards=int(safe_float(row.get("连板数"))),
        d1_score=score, d1_note="；".join(notes), d1_risk="；".join(risks),
    )


def d1_pass_for_new_strategy(d1: D1Row) -> tuple[bool, str]:
    hard = []
    if "反复烂板" in d1.d1_risk:
        hard.append("D1反复烂板")
    if "尾盘板" in d1.d1_risk and d1.breaks >= 3:
        hard.append("D1尾盘且炸板偏多")
    if "封板资金弱" in d1.d1_risk and d1.breaks >= 3:
        hard.append("封板资金弱且炸板偏多")
    if d1.d1_score < 35:
        hard.append(f"D1质量分过低{d1.d1_score:.1f}")
    return (not hard), "；".join(hard)


def score_d2_new_strategy(d1r: D1Row, d1, d2):
    support = estimate_d1_support(d1)
    vol_ratio = d2.volume / d1.volume if d1.volume else 99.0
    day_range = max(d2.high - d2.low, 0.0001)
    body_ratio = abs(d2.close - d2.open) / day_range
    close_below_high = 1 - d2.close / d2.high if d2.high else 0.0
    upper_shadow_ratio = (d2.high - max(d2.open, d2.close)) / day_range
    open_gap = d2.open / d1.close - 1 if d1.close else 0.0
    high_above_open = d2.high / d2.open - 1 if d2.open else 0.0
    above_support = d2.close / support - 1 if support else 0.0
    pct = d2.pct_chg or 0.0
    amount = d2.amount
    turnover = d2.turnover_rate or 0.0

    rejects = []
    notes = []
    risks = []
    score = d1r.d1_score

    if vol_ratio < 1:
        rejects.append(f"D2量比{vol_ratio:.2f}<1，缩量淘汰")
    if vol_ratio > 3:
        rejects.append(f"D2量比{vol_ratio:.2f}>3，放量失控淘汰")
    if open_gap > 0.04 and d2.close < d2.open and pct <= 2:
        rejects.append("D2高开低走且收盘弱")
    if d2.close < support:
        rejects.append("D2收盘跌破D1支撑")
    if high_above_open < 0.02:
        rejects.append("D2盘中冲高不足")

    if rejects:
        return None, "；".join(rejects)

    if 1 <= vol_ratio <= 2.5:
        score += 18; notes.append(f"量比可控{vol_ratio:.2f}")
    elif vol_ratio <= 3:
        score += 4; notes.append(f"量比{vol_ratio:.2f}偏高但未超3"); risks.append("量能偏高")

    if body_ratio <= 0.15 and upper_shadow_ratio > 0.12:
        score += 20; notes.append(f"标准十字/小实体 body={body_ratio:.2f}")
    elif body_ratio <= 0.25:
        score += 12; notes.append(f"准十字/小实体 body={body_ratio:.2f}")
    elif body_ratio > 0.35 and pct > 3:
        score -= 20; notes.append(f"D2实体偏大 body={body_ratio:.2f}"); risks.append("实体偏大")
    else:
        score += 2; notes.append(f"实体中性 body={body_ratio:.2f}")

    if close_below_high >= 0.03:
        score += 14; notes.append(f"冲高回落 {close_below_high*100:.1f}%")
    elif close_below_high >= 0.02:
        score += 6; notes.append(f"回落刚达标 {close_below_high*100:.1f}%")
    else:
        score -= 12; notes.append("D2回落不足"); risks.append("回落不足")

    if open_gap < 0:
        score += 8; notes.append(f"D2低开 {open_gap*100:.1f}%")
    elif open_gap <= 0.02:
        score += 4; notes.append(f"D2平/小高开 {open_gap*100:.1f}%")
    elif open_gap > 0.04:
        score -= 8; notes.append(f"D2高开 {open_gap*100:.1f}%"); risks.append("高开")

    if abs(pct) <= 2:
        score += 10; notes.append(f"收盘涨跌温和 {pct:.2f}%")
    elif pct > 5:
        score -= 22; notes.append(f"D2涨幅{pct:.2f}%偏强，洗盘不足"); risks.append("强延续高风险")
    elif pct < -3:
        score -= 8; notes.append(f"D2偏弱 {pct:.2f}%"); risks.append("偏弱")

    if above_support >= 0.04:
        score += 6; notes.append(f"安全垫{above_support*100:.1f}%")
    elif above_support >= 0.015:
        score += 2; notes.append(f"未破支撑，安全垫{above_support*100:.1f}%")
    else:
        score -= 8; notes.append("安全垫薄"); risks.append("安全垫薄")

    if upper_shadow_ratio > 0.6 and body_ratio <= 0.2:
        score -= 10; notes.append(f"上影占比{upper_shadow_ratio:.2f}过高"); risks.append("长上影降级")
    if amount > 5_000_000_000:
        score -= 6; notes.append("成交额偏拥挤"); risks.append("成交拥挤")
    elif 200_000_000 <= amount <= 3_000_000_000:
        score += 3; notes.append("成交额可跟踪")
    if turnover > 25:
        score -= 8; notes.append("换手过高"); risks.append("换手过高")

    trigger = d2.close
    invalid = support
    zone_low = max(invalid * 1.015, trigger * 0.985)
    zone_high = trigger * 1.003
    return Pick(
        d1=d1r, score=score, trigger=trigger, invalid=invalid, zone_low=zone_low, zone_high=zone_high,
        rank_reason="；".join(notes), risk="；".join([r for r in [d1r.d1_risk, "；".join(risks)] if r]),
        d2_open=d2.open, d2_high=d2.high, d2_low=d2.low, d2_close=d2.close, d2_pct=pct,
        vol_ratio=vol_ratio, body_ratio=body_ratio, close_below_high=close_below_high,
        upper_shadow_ratio=upper_shadow_ratio, open_gap=open_gap, amount=amount, turnover=turnover,
    ), ""


def write_d1_outputs(zt_count, d1_kept, d1_excluded):
    lines = [
        "# 0604D3 新策略 D1 重筛结果",
        "",
        "- 市场边界：只做沪深主板 10cm",
        "- 策略来源：new-strategy-0604",
        "- D1 口径：首板 + 主动封板质量；尾盘/反复烂板/弱封单强降级或剔除",
        f"- D1涨停池总数：{zt_count}",
        f"- D1新策略保留：{len(d1_kept)}",
        f"- D1新策略剔除：{len(d1_excluded)}",
        "",
        "## D1新策略保留",
    ]
    for i, r in enumerate(d1_kept, 1):
        lines.append(f"{i}. {r.code} {r.name}｜{r.industry}｜D1分 {r.d1_score:.1f}｜首次 {r.first_seal}｜炸板 {r.breaks}｜封资 {r.fund_yi:.2f}亿｜{r.d1_note}" + (f"｜风险:{r.d1_risk}" if r.d1_risk else ""))
    lines.extend(["", "## D1剔除样本/原因"])
    for r, reason in d1_excluded:
        lines.append(f"- {r.code} {r.name}｜{reason}｜首次 {r.first_seal}｜炸板 {r.breaks}｜封资 {r.fund_yi:.2f}亿")
    D1_REPORT.write_text("\n".join(lines), encoding="utf-8")
    with D1_CSV.open("w", newline="", encoding="utf-8") as f:
        fields = ["code","name","industry","pct","price","amount_yi","turnover","fund_yi","first_seal","last_seal","breaks","stat","limit_boards","d1_score","d1_note","d1_risk"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in d1_kept:
            w.writerow(r.__dict__)


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    CSV.parent.mkdir(parents=True, exist_ok=True)
    D1_REPORT.parent.mkdir(parents=True, exist_ok=True)
    D1_CSV.parent.mkdir(parents=True, exist_ok=True)

    zt = ak.stock_zt_pool_em(date=D1_DATE.strftime("%Y%m%d"))
    provider = AkshareSinaDailyProvider()
    try:
        provider.stock_codes()
    except Exception:
        pass

    d1_kept = []
    d1_excluded = []
    picks = []
    d2_rejects = []

    for _, row in zt.iterrows():
        base_eval = evaluate_d1_board(row)
        d1r = d1_record(row)
        if not base_eval.passed:
            d1_excluded.append((d1r, base_eval.reject_reason))
            continue
        ok, reason = d1_pass_for_new_strategy(d1r)
        if not ok:
            d1_excluded.append((d1r, reason))
            continue
        d1_kept.append(d1r)
        provider._names[d1r.code] = d1r.name
        try:
            bars = provider.history(d1r.code, start=D1_DATE, end=D2_DATE)
        except Exception as exc:
            d2_rejects.append((d1r.code, d1r.name, f"行情获取失败：{exc}"))
            continue
        by_date = {b.trade_date: b for b in bars}
        d1, d2 = by_date.get(D1_DATE), by_date.get(D2_DATE)
        if not d1 or not d2:
            d2_rejects.append((d1r.code, d1r.name, "缺少D1/D2行情"))
            continue
        pick, reject = score_d2_new_strategy(d1r, d1, d2)
        if pick:
            picks.append(pick)
        else:
            d2_rejects.append((d1r.code, d1r.name, reject))

    d1_kept.sort(key=lambda r: (-r.d1_score, hhmm_to_int(r.first_seal), r.breaks))
    write_d1_outputs(len(zt), d1_kept, d1_excluded)

    picks.sort(key=lambda p: (p.score, d3_entry_comfort(pick_profile(p))), reverse=True)
    active_picks = [p for p in picks if pick_pool_subtype(p) == "active"][:ACTIVE_POOL_CAP]
    radar_picks = [p for p in picks if pick_pool_subtype(p) == "radar" and p not in active_picks][:RADAR_POOL_CAP]
    selected = active_picks + radar_picks
    narrowed = [p for p in picks if p not in selected]

    lines = [
        "# 0604D3 新策略完整重筛",
        "",
        "- 策略来源：new-strategy-0604",
        "- 处理方式：D1 从涨停池重新筛，只保留沪深主板 10cm；D2 再按新策略确认，不直接补票",
        f"- D1={D1_DATE:%Y%m%d}，D2={D2_DATE:%Y%m%d}",
        f"- D1涨停池总数：{len(zt)}",
        f"- D1新策略保留：{len(d1_kept)}",
        f"- D2新策略通过：{len(picks)}",
        f"- 自动输出：active {len(active_picks)}，radar {len(radar_picks)}",
        "- 核心偏好：D1主动封板质量；D2量比1-2.5、小实体/十字、冲高回落、低开/平开承接。",
        "",
        "## 观察排序",
    ]
    for i, p in enumerate(selected, 1):
        r = p.d1
        lines.extend([
            f"### {i}. {r.code} {r.name}｜{r.industry}｜评分 {p.score:.1f}",
            f"- 观察价 {p.trigger:.2f}｜参与区 {p.zone_low:.2f}-{p.zone_high:.2f}｜失效 {p.invalid:.2f}",
            f"- D1：分 {r.d1_score:.1f}｜首次封板 {r.first_seal}｜炸板 {r.breaks}｜封资 {r.fund_yi:.2f}亿｜{r.d1_note}",
            f"- D2：开 {p.d2_open:.2f} 高 {p.d2_high:.2f} 低 {p.d2_low:.2f} 收 {p.d2_close:.2f}｜涨跌 {p.d2_pct:.2f}%｜成交额 {fmt_yi(p.amount)}｜换手 {p.turnover:.2f}%",
            f"- 结构：量比 {p.vol_ratio:.2f}｜实体/振幅 {p.body_ratio:.2f}｜高点回落 {p.close_below_high*100:.1f}%｜开盘缺口 {p.open_gap*100:.1f}%",
            f"- 规则命中：{p.rank_reason}",
        ])
        if p.risk:
            lines.append(f"- 风险/降级：{p.risk}")
        lines.append("")
    if narrowed:
        lines.extend(["## 通过但未输出", ""])
        for p in narrowed[:30]:
            lines.append(f"- {p.d1.code} {p.d1.name}｜评分 {p.score:.1f}｜{p.risk or '容量限制'}")
    if d2_rejects:
        lines.extend(["", "## D2剔除样本", ""])
        for code, name, reason in d2_rejects[:60]:
            lines.append(f"- {code} {name}：{reason}")
    if d1_excluded:
        lines.extend(["", "## D1剔除样本", ""])
        for r, reason in d1_excluded[:60]:
            lines.append(f"- {r.code} {r.name}：{reason}")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    with CSV.open("w", newline="", encoding="utf-8") as f:
        fields = ["code","name","industry","stage","pool_type","pool_subtype","source_file","trigger_price","invalid_price","zone_low","zone_high","rank","score","note"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, p in enumerate(selected, 1):
            r = p.d1
            psub = pick_pool_subtype(p)
            w.writerow({
                "code": r.code, "name": r.name, "industry": r.industry, "stage": D3_LABEL, "pool_type": "watch",
                "pool_subtype": psub,
                "source_file": CSV.name, "trigger_price": f"{p.trigger:.2f}", "invalid_price": f"{p.invalid:.2f}",
                "zone_low": f"{p.zone_low:.2f}", "zone_high": f"{p.zone_high:.2f}", "rank": i, "score": f"{p.score:.1f}",
                "note": f"{D3_LABEL}｜watch｜{psub}｜new_strategy_full｜D1:{r.d1_note}｜D2:{p.rank_reason}" + (f"｜风险:{p.risk}" if p.risk else ""),
            })
    print(f"REPORT={REPORT}")
    print(f"CSV={CSV}")
    print(f"D1_REPORT={D1_REPORT}")
    print(f"D1_CSV={D1_CSV}")
    print(f"D1_KEEP={len(d1_kept)} D2_PASS={len(picks)} SELECTED={len(selected)}")

if __name__ == "__main__":
    main()
