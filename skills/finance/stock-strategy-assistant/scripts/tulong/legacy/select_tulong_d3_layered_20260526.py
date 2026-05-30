#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import math
import sys

import akshare as ak

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / 'src'))

from stock_assistant.akshare_provider import AkshareSinaDailyProvider  # noqa: E402
from stock_assistant.strategy_tulong import estimate_d1_support, is_d2_pullback  # noqa: E402

D1_DATE = '20260522'
D2_DATE = date(2026, 5, 25)
D3_DATE = date(2026, 5, 26)
MAX_MONITOR = 4
MAX_STRONG = 2
MAX_OBSERVE = 2
MAX_BACKUP = 2

EXCLUDE_PREFIXES = ('688', '689', '8', '4')
EXCLUDE_NAME_PARTS = ('ST', '*ST', '退')

@dataclass
class Candidate:
    code: str
    name: str
    industry: str
    score: float
    tier: str
    trigger: float
    invalid: float
    d1_close: float
    d2_close: float
    d2_high: float
    d2_low: float
    d2_pct: float | None
    d2_turnover: float | None
    d2_amount: float
    d2_volume_ratio: float
    d2_close_below_high: float
    d2_above_support: float
    d1_first_seal: str
    d1_open_breaks: int
    d1_fund: float
    d1_turnover: float
    d1_amount: float
    reason: str
    note: str


def safe_float(x, default=0.0):
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return float(x)
    except Exception:
        return default


def hhmm_to_int(x) -> int:
    s = str(x).strip()
    if not s or s == 'nan':
        return 240000
    try:
        return int(s)
    except Exception:
        return 240000


def fmt_yi(x: float) -> str:
    return f'{x / 100000000:.2f}亿'


def entry_zone(trigger: float, invalid: float) -> tuple[float, float]:
    return max(invalid * 1.015, trigger * 0.985), trigger * 1.003


def tier_for(c: Candidate) -> str:
    # 先按硬风险降档，再看分数。
    if c.d2_close_below_high < 0.02 or c.d2_volume_ratio > 1.6 or (c.d2_turnover and c.d2_turnover > 30):
        return 'B'
    if c.score >= 78:
        return 'A'
    if c.score >= 62:
        return 'B'
    return 'C'


def score_candidate(row, d1, d2, support, reason, industry: str) -> tuple[float, str]:
    vol_ratio = d2.volume / d1.volume if d1.volume else 9.99
    close_below_high = 1 - d2.close / d2.high if d2.high else 0
    above_support = d2.close / support - 1 if support else 0
    high_above_open = d2.high / d2.open - 1 if d2.open else 0
    open_gap = d2.open / d1.close - 1 if d1.close else 0
    amount = d2.amount
    turnover = d2.turnover_rate or 0
    first_seal = hhmm_to_int(row.get('首次封板时间'))
    breaks = safe_float(row.get('炸板次数'))
    fund = safe_float(row.get('封板资金'))
    d1_turnover = safe_float(row.get('换手率'))

    score = 50.0
    notes = []
    # D1：首板质量
    if first_seal <= 93000:
        score += 8; notes.append('D1早盘封板')
    elif first_seal <= 100000:
        score += 5; notes.append('D1较早封板')
    elif first_seal >= 140000:
        score -= 5; notes.append('D1尾盘封板降权')
    if breaks == 0:
        score += 5; notes.append('D1未炸板')
    elif breaks <= 2:
        score += 1; notes.append(f'D1炸板{int(breaks)}次')
    else:
        score -= 6; notes.append(f'D1炸板{int(breaks)}次偏多')
    if fund >= 80_000_000:
        score += 5; notes.append('封板资金较足')
    elif fund < 10_000_000:
        score -= 4; notes.append('封板资金偏弱')

    # D2：冲高回落但不破位，量能不过热
    if 0.55 <= vol_ratio <= 1.25:
        score += 12; notes.append(f'D2量比温和{vol_ratio:.2f}')
    elif 1.25 < vol_ratio <= 1.6:
        score += 5; notes.append(f'D2量比略高{vol_ratio:.2f}')
    elif vol_ratio < 0.55:
        score -= 3; notes.append(f'D2量比偏低{vol_ratio:.2f}')
    else:
        score -= 10; notes.append(f'D2量比偏大{vol_ratio:.2f}')

    if close_below_high >= 0.05:
        score += 8; notes.append('D2回落充分')
    elif close_below_high >= 0.03:
        score += 5; notes.append('D2有冲高回落')
    elif close_below_high >= 0.02:
        score += 2; notes.append('D2回落刚达标')
    else:
        score -= 8; notes.append('D2回落不足')

    if above_support >= 0.04:
        score += 6; notes.append('D2收盘离支撑有安全垫')
    elif above_support >= 0.015:
        score += 3; notes.append('D2未破支撑')
    else:
        score -= 5; notes.append('D2贴近支撑')

    if high_above_open >= 0.04:
        score += 4; notes.append('D2盘中上冲明显')
    if open_gap > 0.04 and d2.close < d2.open:
        score -= 10; notes.append('D2高开低走风险')

    # 流动性/噪声
    if 200_000_000 <= amount <= 3_000_000_000:
        score += 5; notes.append('成交额可跟踪')
    elif amount < 100_000_000:
        score -= 8; notes.append('成交额偏小')
    elif amount > 5_000_000_000:
        score -= 5; notes.append('成交额过大偏拥挤')
    if turnover > 35:
        score -= 8; notes.append('换手过高降噪')
    elif 3 <= turnover <= 20:
        score += 3; notes.append('换手适中')

    # D2如果仍强涨/连板，D3低吸意义下降
    if d2.pct_chg is not None and d2.pct_chg > 7:
        score -= 10; notes.append('D2仍大涨，容易变追高')
    if d2.pct_chg is not None and d2.pct_chg < -5:
        score -= 5; notes.append('D2走弱偏多')

    return score, '；'.join(notes[:8])


def main():
    zt = ak.stock_zt_pool_em(date=D1_DATE)
    provider = AkshareSinaDailyProvider()
    names = {}
    try:
        provider.stock_codes()
    except Exception:
        pass

    raw = []
    checked = 0
    for _, row in zt.iterrows():
        code = str(row['代码']).zfill(6)
        name = str(row['名称'])
        industry = str(row.get('所属行业', ''))
        if code.startswith(EXCLUDE_PREFIXES) or any(p in name for p in EXCLUDE_NAME_PARTS):
            continue
        # 只要 D1 首板，排除连板股；涨停统计用 1/1 或 连板数=1 双保险。
        stat = str(row.get('涨停统计', ''))
        lb = safe_float(row.get('连板数'))
        if not (stat.startswith('1/') or lb == 1):
            continue
        checked += 1
        try:
            bars = provider.history(code, start=D1_DATE_TO_DATE - timedelta(days=15), end=D2_DATE)
        except Exception:
            continue
        by_date = {b.trade_date: b for b in bars}
        d1 = by_date.get(D1_DATE_TO_DATE)
        d2 = by_date.get(D2_DATE)
        if not d1 or not d2:
            continue
        support = estimate_d1_support(d1)
        ok, reason = is_d2_pullback(d1, d2, support)
        if not ok:
            continue
        score, note = score_candidate(row, d1, d2, support, reason, industry)
        vol_ratio = d2.volume / d1.volume if d1.volume else 9.99
        close_below_high = 1 - d2.close / d2.high if d2.high else 0
        c = Candidate(
            code=code, name=name, industry=industry, score=score, tier='',
            trigger=d2.close, invalid=support, d1_close=d1.close, d2_close=d2.close,
            d2_high=d2.high, d2_low=d2.low, d2_pct=d2.pct_chg,
            d2_turnover=d2.turnover_rate, d2_amount=d2.amount, d2_volume_ratio=vol_ratio,
            d2_close_below_high=close_below_high, d2_above_support=d2.close / support - 1,
            d1_first_seal=str(row.get('首次封板时间', '')), d1_open_breaks=int(safe_float(row.get('炸板次数'))),
            d1_fund=safe_float(row.get('封板资金')), d1_turnover=safe_float(row.get('换手率')),
            d1_amount=safe_float(row.get('成交额')), reason=reason, note=note,
        )
        c.tier = tier_for(c)
        raw.append(c)

    raw.sort(key=lambda x: x.score, reverse=True)
    a = [c for c in raw if c.tier == 'A'][:MAX_STRONG]
    b = [c for c in raw if c.tier == 'B' and c not in a][:MAX_OBSERVE]
    selected = (a + b)[:MAX_MONITOR]
    backups = [c for c in raw if c not in selected][:MAX_BACKUP]

    out_dir = PROJECT / 'reports/daily'
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / 'tulong_d3_layered_20260526.md'
    csv_path = PROJECT / 'data/watchlists/tulong_d3_20260526_layered.csv'
    monitor_path = PROJECT / 'data/watchlists/tulong_d3.csv'

    lines = []
    lines.append('# 屠龙战术 D3 分层筛选 2026-05-26（周二）')
    lines.append('')
    lines.append('## 口径')
    lines.append('- D1：2026-05-22 首板；D2：2026-05-25 冲高回落、量能不过 2 倍、不破 D1 支撑；D3：2026-05-26 只做观察池。')
    lines.append('- 分层 + 限额 + 降噪：A 强观察最多 2 只，B 轻观察最多 2 只，C 备选不进 5 分钟高频监控；总监控不超过 4 只。')
    lines.append('- 输出为策略候选与风控位，不构成买卖建议。')
    lines.append('')
    lines.append(f'## 扫描结果')
    lines.append(f'- D1 首板候选检查：{checked} 只')
    lines.append(f'- 通过 D2 硬条件：{len(raw)} 只')
    lines.append(f'- 今日进入 D3 监控：{len(selected)} 只；备选：{len(backups)} 只')
    lines.append('')

    def append_group(title, items, monitor: bool):
        lines.append(f'## {title}')
        if not items:
            lines.append('- 无')
            lines.append('')
            return
        for i, c in enumerate(items, 1):
            zl, zh = entry_zone(c.trigger, c.invalid)
            lines.append(f'### {i}. {c.code} {c.name}｜{c.industry}｜{c.tier}｜评分 {c.score:.1f}')
            lines.append(f'- D3观察价：{c.trigger:.2f}；低吸观察区：{zl:.2f}–{zh:.2f}；失效位：{c.invalid:.2f}')
            lines.append(f'- D2：收 {c.d2_close:.2f}，高 {c.d2_high:.2f}，低 {c.d2_low:.2f}，涨跌幅 {c.d2_pct if c.d2_pct is not None else 0:.2f}%，成交额 {fmt_yi(c.d2_amount)}')
            lines.append(f'- 结构：D2/D1量比 {c.d2_volume_ratio:.2f}；高点回落 {c.d2_close_below_high*100:.1f}%；距失效位安全垫 {c.d2_above_support*100:.1f}%')
            lines.append(f'- D1质量：首次封板 {c.d1_first_seal}；炸板 {c.d1_open_breaks} 次；封板资金 {fmt_yi(c.d1_fund)}')
            lines.append(f'- 入池理由：{c.note}')
            if monitor:
                lines.append('- 降噪设置：只在进入低吸观察区、回收观察价、跌近/跌破失效位、或强拉升不追高时提醒；普通波动不刷屏。')
            else:
                lines.append('- 处理：备选观察，不进入 5 分钟高频提醒；除非 A/B 池失效或盘中结构显著转强。')
            lines.append('')

    append_group('A层：强观察（优先看，最多2只）', a, True)
    append_group('B层：轻观察（补充看，最多2只）', b, True)
    append_group('C层：备选/降噪池（不进高频监控）', backups, False)

    lines.append('## 今日执行规则')
    lines.append('1. 不追高：快速离开观察价上方较远，只记录“强势/不追高”。')
    lines.append('2. 只看低吸区：优先观察价附近或水下回收；跌破失效位直接移出。')
    lines.append('3. 提醒限额：主监控最多 4 只；同一股票同类事件每天最多提醒一次，避免刷屏。')
    lines.append('')

    report = '\n'.join(lines)
    report_path.write_text(report, encoding='utf-8')

    import csv
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['code','name','trigger_price','invalid_price','rank','tier','score','note'])
        w.writeheader()
        for idx, c in enumerate(selected + backups, 1):
            w.writerow({'code': c.code, 'name': c.name, 'trigger_price': f'{c.trigger:.2f}', 'invalid_price': f'{c.invalid:.2f}', 'rank': idx, 'tier': c.tier, 'score': f'{c.score:.1f}', 'note': c.note})
    with monitor_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['code','name','trigger_price','invalid_price','rank','note'])
        w.writeheader()
        for idx, c in enumerate(selected, 1):
            w.writerow({'code': c.code, 'name': c.name, 'trigger_price': f'{c.trigger:.2f}', 'invalid_price': f'{c.invalid:.2f}', 'rank': idx, 'note': f'{c.tier}层｜{c.note}'})

    print(report)
    print(f'\nREPORT={report_path}')
    print(f'CSV={csv_path}')
    print(f'MONITOR={monitor_path}')

D1_DATE_TO_DATE = date(2026, 5, 22)

if __name__ == '__main__':
    main()
