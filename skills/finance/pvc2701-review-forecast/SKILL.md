---
name: pvc2701-review-forecast
description: PVC2701（大商所 PVC 2701 / 新浪 V2701）专属复盘、预测与飞书投递 Skill。用户提到 pvc2701、PVC2701、V2701、PVC 2701、塑料2701、该合约的上午盘/日盘/夜盘复盘、下一时段预测、操作计划、飞书文档或发到 pvc2701 群时必须使用；生成中文多周期条件化报告，维护前序计划链，并只投递到飞书群 pvc2701。
metadata:
  hermes:
    version: 1.0.0
    tags: [futures, pvc2701, review, forecast, feishu]
    related_skills: [futures-trading-assistant]
---

# PVC2701 复盘预测助手

## 目标

围绕大商所 PVC2701 合约建立可持续的“前序计划 → 实际走势复盘 → 下一时段预测 → 飞书文档 → 群内链接”闭环。

输出是条件化交易研究，不是确定性喊单。每份预测都要给出触发条件、失效条件、止损、目标、风险和无信号时的观望方案。

## 固定标的与投递目标

- 合约显示名：`PVC2701`
- 新浪行情代码：`V2701`
- 新浪快照代码：`nf_V2701`
- 飞书群名：`pvc2701`
- 飞书群 ID：`oc_d5aa041b453e9b6f8a38fba75fa94b37`
- Cron 投递目标：`feishu:oc_d5aa041b453e9b6f8a38fba75fa94b37`

群投递是硬隔离边界。发送前读取 `configs/pvc2701_feishu.json` 并同时核对群名与群 ID；不要沿用 `PVC2609` 的“期货通知”群，也不要仅凭群名模糊匹配。

## 使用前读取

本 Skill 复用成熟期货母版的通用规则。按任务读取以下文件：

- 行情与指标：`../futures-trading-assistant/references/china-futures-public-data.md`
- 前序计划链：`../futures-trading-assistant/references/session-state-chain.md`
- 报告结构：`../futures-trading-assistant/references/report-structure-benchmarks.md`
- 关键位层级：`../futures-trading-assistant/references/pvc-level-sanity-and-session-local-levels.md`
- 飞书文档：`../futures-trading-assistant/references/feishu-report-publishing.md`
- 群通知：`../futures-trading-assistant/references/feishu-futures-alerts.md`

引用母版时把 `PVC2609/V2609/pvc2609_feishu_monitor` 映射为 `PVC2701/V2701/pvc2701_feishu_monitor`，但不要修改或覆盖母版的运行数据。

## 标准流程

1. 确认北京时间、交易日和已完成的复盘时段。
2. 抓取 quote、3m、15m、30m、60m、120m、日 K，并验证返回日期。
3. 只用被复盘时段自己的 15m/3m K 线推导近端支撑压力；日 K 远端位只能作为大级别观察位。
4. 读取治理该时段的前序报告，逐项验证 A/B/C/D 方案；未触发也必须记录。
5. 生成约 20 节中文 Markdown，包含多周期结构、时间切片、预测 vs 实际、偏差归因、下一时段 A/B/C/D/E 方案和 `STATE_HANDOFF`。
6. 运行质量门禁；日期错位、前序缺失（非首期）、关键位层级异常、止损止盈方向错误时禁止发布。
7. 将正式报告保存到本 Skill 的 `reports/`，并更新 `runtime/pvc2701_feishu_monitor/latest_prediction_levels.json`。
8. 创建飞书在线文档，验证 raw content 非空，回写本地 Markdown 的在线文档 URL。
9. 用户要求发群或任务是已授权的 PVC2701 定时发布时，只把标题、摘要和最终文档链接发送到固定群。

## 首期建档规则

第一份报告没有前序计划时，使用 `pvc2701_bootstrap_publish.py`：

- 明确写“首期建档，无前序预测”，不计算或暗示历史命中率。
- Section 5 只说明从本期开始建立可验证基线。
- 仍需通过行情日期、场景方向、关键位层级和飞书文档质量校验。
- 首期完成后，后续报告必须恢复严格前序计划门禁。

## 报告链与时间

- 交易时段每 3 分钟：若 3m 收盘有效穿越最新计划关键位，生成盘中操作重估并更新监控位。
- 11:35 / 15:05 / 23:05：自动化预检；全部通过则静默，失败才私聊告警。
- 11:40：复盘上午盘，预测午盘，目标 `afternoon`。
- 15:10：复盘完整日盘，预测夜盘，目标 `night`。
- 23:10：复盘夜盘，预测下一日盘，目标 `morning`。

滚动文件名：

- `reports/pvc2701_YYYYMMDD_afternoon_preopen_review_forecast.md`
- `reports/pvc2701_YYYYMMDD_night_preopen_review_forecast.md`
- `reports/pvc2701_YYYYMMDD_morning_preopen_review_forecast.md`
- `reports/pvc2701_YYYYMMDD_intraday_<session>_<HHMM>_key_level_break_<up|down>_<price>.md`

定时任务：

| 任务 | 时间 | 脚本 | 投递 |
|------|------|------|------|
| 盘中关键位操作重估 | `*/3 9-15,21-23 * * 1-5` | `pvc2701_intraday_key_level_report.sh` | 群 `pvc2701` |
| 上午收盘后午盘复盘 | `40 11 * * 1-5` | `pvc2701_afternoon_review_report.sh` | 群 `pvc2701` |
| 日盘收盘后夜盘复盘 | `10 15 * * 1-5` | `pvc2701_night_review_report.sh` | 群 `pvc2701` |
| 夜盘收盘后次日日盘复盘 | `10 23 * * 1-5` | `pvc2701_morning_review_report.sh` | 群 `pvc2701` |
| 自动化预检 | `5,35 11,15,23 * * 1-5` | `pvc2701_automation_healthcheck.sh` | 个人账号，失败才发 |

## 命令入口

生成草稿但不发飞书：

```bash
python pvc2701_generate_session_report.py --date YYYYMMDD --session morning|day|night
```

首期建档并创建飞书文档：

```bash
python pvc2701_bootstrap_publish.py --target afternoon|night|morning --date YYYYMMDD
```

正常生成、质量校验并创建飞书文档：

```bash
python pvc2701_review_publish.py --target afternoon|night|morning --date YYYYMMDD
```

盘中关键位触发重估（无穿越则静默）：

```bash
python pvc2701_intraday_key_level_report.py
```

正式发布前预检（通过则静默；`--verbose` 打印成功摘要）：

```bash
python pvc2701_automation_healthcheck.py --target auto
```

上述发布脚本只输出群消息正文；定时任务由 Hermes Cron 投递。一次性立即发群时，用 `send_feishu_group.py --message-file <file>`，该脚本的目标群固定且不可由命令行覆盖。

## 风险与数据限制

- 公共 quote 只有一档盘口，没有五档与逐笔主动买卖。
- 量仓变化不能直接标注多开、空开、多平、空平。
- PVC2701 属远月合约时，要检查成交量、持仓量与买卖价差；流动性不足时降低预测置信度。
- 不使用“必涨、必跌、保证盈利、必须开仓”等表述。
- 若用户表示稍后提供个人成交/持仓截图，先等数据，不要提前发布带执行评价的报告。

## 完成检查

- [ ] 报告和运行目录均为 `pvc2701`，未覆盖 `pvc2609`。
- [ ] quote 与复盘日期一致，或已明确使用历史时段收盘锚点。
- [ ] 3m/15m/30m/60m/120m/日 K 已抓取或标记缺失。
- [ ] A/B/C/D/E 含入场、失效、止损/目标和观望条件。
- [ ] 飞书文档 raw content 非空，本地报告已回写 URL。
- [ ] 投递目标严格等于 `pvc2701 / oc_d5aa041b453e9b6f8a38fba75fa94b37`。
