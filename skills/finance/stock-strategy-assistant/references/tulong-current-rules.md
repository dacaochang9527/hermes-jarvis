# 屠龙当前规则

本文件只保留当前有效的屠龙 D1/D2/D3 规则口径。运行、cron、切池、日志、微信投递等工程步骤见 `references/tulong-operations.md`。旧底稿和一次性迁移笔记已从当前 skill references 中删除，不作为当前事实源。

## 核心边界

- 输出策略信号，不输出确定性买卖建议。
- 当前只做 A 股沪深主板 10cm；用户当前无创/科权限时过滤 `300/301/688/689`，同时过滤北交所等非主板前缀。
- 统一使用“D1过滤规则”“D2过滤规则”“D1/D2过滤规则”，不要混用“硬过滤”“硬条件”“基础风险过滤”等近义词。
- 观察票使用 `日期 + D几`，例如 `0603D3`；买入后统一转为 `HOLD`，不再使用 D4/D5 这类持仓阶段标签。
- 验证期内不预设买入后的退出、加仓、止盈、止损策略；HOLD 只表达持仓事实和 T+1 可卖性。

## D1 过滤规则

D1 是首板底池，只做首板识别和基础过滤，不做 D2/D3 判断。

保留：

- 沪深主板 10cm：`600/601/603/605`、`000/001/002/003`；
- 非 ST / *ST / 退市风险；
- 当日首板：`涨停统计` 形如 `1/x` 或 `连板数 == 1`；
- D1 封板结构可接受：早盘/上午封板更优；尾盘封板、长期封不住、反复烂板、封板资金弱，需要结合 D2 验证；
- D1 炸板不能只看接口次数：0 次最好，1–2 次可接受；多次炸板必须结合回封速度、最后封板时间、封板资金和用户分时图校正；
- 成交额、换手率需要可跟踪：过小难跟踪，过大可能拥挤。

剔除：

- 20cm / 北交所 / 非主板；
- ST、*ST、退市风险；
- 非首板：2 连板、3 连板、4 连板等；
- 虽然强势但不属于当前 D1 首板定义的趋势票或连板票；
- D1 反复烂板、长时间封不住、封板资金弱，且 D2 未能给出有效承接验证。

D1 底池字段至少保留：

```text
code, name, industry, pct, price, amount_yi, turnover,
fund_yi, first_seal, last_seal, breaks, stat, limit_boards
```

## D2 过滤规则

D2 在 D1 底池基础上确认承接和分歧。遇到周一/节假日按真实交易日回退，不按自然日推导。

保留：

- D2 量能在 D1 2 倍以内更好；
- D2 量能为 D1 2–3 倍时，只要其他 D2 条件都符合，仍可保留；
- D2 不能过度缩量，缩量过弱说明承接和分歧交换不足；
- D2 盘中有上冲和回落，且收盘不跌破 D1 支撑；
- D2 收盘近十字 / 分歧平衡更优；
- D2 成交额、换手率需要可跟踪，过小难跟踪，过大可能拥挤；
- D2 明显强势延续但未破 D1 支撑、量能不极端时，可进入“强势确认观察”路径，不要只因缺少回落就机械剔除。

剔除：

- D2 成交量超过 D1 3 倍；
- D2 缩量过弱；
- D2 盘中冲高不足，且也不满足强势确认路径；
- D2 收盘跌破 D1 支撑位；
- D2 高开低走，疑似出货；
- D2 上引线太长、收盘离高点太远，说明上方抛压重。

## D3 观察规则

D3 当天统一称为 `D3观察区`，不是“低吸池”。D3 观察区的主口径是：

```text
低吸可执行性 AND 强势潜质
```

这里的低吸可执行性表示必须有舒服的参与/风控点，不代表只做水下低吸。D3 至少分三类看：

- D3低吸观察：回落到买点区、失效位清楚、风险收益比舒服；
- D3强势观察/回收确认：D2结构强，D3不一定给深水低吸，但可观察回收观察价、突破前高、强回封或板块共振；
- D3持仓管理：若已买入，立即转为 `HOLD/position`，不能和未买入观察混写。

观察标的必须同时满足：

- 有清楚的买点 / 止损 / 回落承接位置；
- 具备 D3 回收观察价并向上扩展的可能。

排除：

- 低吸但没有强势潜质的弱修复票；
- 强但没有合理低吸/承接参与点的追高票。

默认容量：

- D3 观察区 8–10 只；
- 高频/强提醒不超过 4–5 只；
- 其余观察区票只进低频快照。

## 自动窄化

每次生成或更新 D3 初选后，必须立即按规则自动检查和窄化。用户提供的新信息只能作为规则输入或规则修订候选，不能直接绕过规则把股票补入 D3。

复核清单：

- 先查重：读取 `data/trades/tulong_trades.csv` 并按成交记录汇总当前 open position；同一只票默认保留在 HOLD，不重复放入 D3，除非用户明确要求双标签；
- 点位有效：检查 `zone_low <= zone_high`，观察区不能过度贴近失效线；安全垫过薄或观察区倒挂时剔除/降为备选；
- AND 口径：必须同时具备低吸可执行性和强势潜质；
- D2 形态：优先收盘近十字/分歧平衡、量比健康、回落充分但未破位；
- D1 封板结构：早盘/上午封板优于尾盘；炸板但快速回封可接受；
- 拥挤度：成交额过大或过热时不要只当备注，应纳入保留或剔除判断；
- 外部信息输入：若用户提供分时图、板块强度或漏筛线索，只能转化为可执行检查项后重新跑规则，并在 note 中保留触发/排除原因。

输出时直接给出自动窄化后的观察名单，并列出未输出原因。落盘文件统一使用 `MMDDD3_watch_scan_YYYYMMDD_HHMMSS.csv`。

## D1 底池复盘口径

当用户指定 `{MMDDD3}_D1_filtered_*` 并问“里面的票今天表现如何”时，这是 D1 首板底池全量复盘，不是实际 D3 watch 监控池复盘。必须区分：

- D1 filtered 全量底池：只经过 D1过滤规则；
- D3 watch 观察池：经过 D2确认和 D3 自动窄化；
- HOLD 持仓：买入后的事实层。

分析步骤：

- 读取用户指定 D1 filtered CSV，统计全量代码数、行业、D1封板时间、炸板次数、成交额等；
- 读取同标签最新 `MMDDD3_watch_*`，标注 `in_watch=true/false`；
- 获取当日行情，按涨跌幅、是否涨停/近涨停、成交额、盘中高低、收盘相对高低分层；
- 分开输出 D1底池总体、已入 watch、未入 watch 但强势延续、未入 watch 且走弱的样本。

## HOLD 持仓事实层

买入后统一进入 `HOLD`。HOLD 不再依赖独立 `HOLD_position_*` 文件，当前持仓从 `data/trades/tulong_trades.csv` 的买卖记录汇总派生：同一代码买入数量减卖出数量后仍大于 0，即视为 open position。

交易记录字段至少包括：

```text
trade_date
session_label
action            # buy / sell
code
name
quantity
price
amount
fee
net_amount
position_ref      # 原始 D3 入场标签，如 0603D3
note
d3_watch
```

运行时派生出的 HOLD 字段建议：

```text
stage = HOLD
pool_type = position
entry_date        # 从首笔未平买入 trade_date 派生
entry_stage       # 从 position_ref 派生
entry_price       # 按剩余持仓成本或加权买入成本派生
quantity          # 当前剩余持仓数量
sellable_quantity # T+1 可卖性由 entry_date / trade_date 派生
cost_amount
source_file = data/trades/tulong_trades.csv
```

验证期内只呈现事实指标：成本、现价、相对盈亏、距失效位、可卖数量、当日强弱。不要给“该卖/该加/止损止盈”的硬结论。

## 规则输入修订

盘中用户可能提供板块强度、分时观察或漏筛线索。处理纪律：

- 不把未通过规则的股票直接补入 `MMDDD3`；
- 先把新信息转成可执行检查项，例如 D1 首板、D2 未破 D1 支撑、D2 量能不超过 3 倍、主板 10cm、无 ST/退市风险、D3 回收观察价或强势确认位；
- 重新运行自动规则生成观察池，仍由规则决定是否进入 D3；
- `note` 写清规则触发、排除或降级原因，不写人工覆盖标签；
- 如新信息暴露规则缺口，先作为策略候选落到 `reports/reviews/tulong_d3_strategy_reviews/`，经复盘确认后再更新当前规则。

## 外部策略输入处理

当用户提供朋友策略、新策略目录、图片策略或外部样本库时，先作为规则输入重新自动评分筛选，不直接改主规则、不直接补入观察池。处理步骤：

1. 读取外部策略的规则、正例和失败样本，提炼可执行检查项。
2. 重新拉取当次所需的 D1/D2/行情数据后再评分，不能沿用本地已有候选池、旧 D1/D2 CSV、旧行情快照或历史扫描结果来套外部策略。输出独立报告和 CSV，文件名可带策略来源，例如 `MMDDD3_new_strategy_scan_YYYYMMDD_HHMMSS.md` 与 `MMDDD3_new_strategy_watch_scan_YYYYMMDD_HHMMSS.csv`。
3. 报告中必须写明“外部策略输入已重新取数并重新评分，不直接补票”，并列出数据拉取时间、通过、未输出和剔除原因。
4. 外部策略若与当前主规则冲突，先保留为候选策略结果；只有经多日复盘确认后，才按“规则变更同步协议”固化到当前规则、规则函数、selection/runtime 脚本、运行手册和测试。
5. 不把历史失败样本当永久黑名单；只把失败原因转成当次可检查的降级/剔除条件。


- 单日或少量样本形成的策略候选，先落到 `reports/reviews/tulong_d3_strategy_reviews/`，不要过早写入当前规则。
- 旧 reference 若从历史版本中重新出现，与本文件冲突时，以本文件为准。

## 规则变更同步协议

当本文件的 D1/D2/D3、自动窄化、HOLD 或规则输入修订发生变化时，不能只改规则文档。每次规则变更必须同步评估并按需修改：

```text
references/tulong-current-rules.md   # 策略口径事实源
src/stock_assistant/strategy_tulong.py # 可复用规则函数和字段计算
scripts/tulong/selection/             # 候选生成、自动窄化、输出字段和报告文本
scripts/tulong/runtime/               # active 池、HOLD 派生、提醒判断、展示文本
references/tulong-operations.md       # 运行流程、字段来源、监控/排障说明
tests/                                # 规则函数、selection CLI、runtime 和文档一致性测试
```

同步判断：

- 改 D1/D2/D3 过滤或评分口径：优先检查 `src/stock_assistant/strategy_tulong.py` 和 `tests/test_tulong.py`；
- 改观察池容量、自动窄化、输出字段或文件命名：检查 `scripts/tulong/selection/`、`tests/test_tulong_selection_cli.py` 和运行手册；
- 改 HOLD、active 池、提醒触发或展示文案：检查 `scripts/tulong/runtime/`、`tests/test_preopen_rotate_watchlist.py` 和运行手册；
- 改运行时字段来源或 cron 行为：检查 `references/tulong-operations.md`、`scripts/tulong/README.md` 和 wrapper 映射；
- 如确认某层无需修改，复盘/提交说明中要明确写出“已评估，无需改动”的原因。

推荐验证命令：

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile scripts/tulong/runtime/*.py scripts/tulong/selection/*.py
```
