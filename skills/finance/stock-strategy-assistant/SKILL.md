---
name: stock-strategy-assistant
description: "设计和实现个人股票策略助手：选股规则化、回测、日报、盘中提醒与风控边界。"
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [stocks, quant, backtesting, alerts, finance, product]
    category: finance
---

# Stock Strategy Assistant 股票策略助手

> 屠龙运行时已内置于本 skill（2026-05-31 从旧项目 `a-share-stock-assistant` 迁入）。
> 代码与数据就在本 skill 目录内：`scripts/tulong/`（runtime/selection/legacy）、`src/stock_assistant/`（依赖子集）、`data/`、`reports/`、`tests/`、`pyproject.toml`、`.venv/`。
> Hermes cron（`~/.hermes/scripts/*.sh` + `~/.hermes/cron/jobs.json` workdir）已指向本 skill 根。运行命令：`cd 本skill根 && .venv/bin/python scripts/tulong/runtime/<脚本>.py`；测试：`.venv/bin/python -m pytest -q`。以后只在本 skill 内维护，无需回到旧项目。

## 适用场景

当用户希望讨论、设计或实现以下系统时加载本 skill：

- 选股助手、股票监控、买卖信号提醒；
- A 股/港股/美股的中短线、波段、事件交易、量化筛选；
- 把口头战法/朋友策略/图片策略规则化；
- 回测某个选股策略或验证正反案例；
- 构建每日收盘报告、盘中提醒、风控/复盘系统。

当后续和用户确认新的股票策略规则、D3/D4 指标、提醒格式、频率、监控池流转或风控口径后，应同步更新本 skill；若是屠龙 D3/D4 细节，优先更新 `references/tulong-d3-d4-monitoring.md`，SKILL.md 只保留摘要和路由。

## 合规与安全边界

1. **不直接给个性化投资建议**：不要输出“必须买/卖某只股票”“保证收益”等表述。
2. **输出策略信号而非交易指令**：使用“候选、观察、触发、失效、风险提示、复盘”语言。
3. **先验证再实时化**：实时提醒前，优先做历史回测/半自动筛选，避免把未经验证的策略包装成确定机会。
4. **强调风控和失效条件**：每个信号必须给出失效条件、退出规则或风险位。
5. **避免诱导频繁交易**：盘中提醒应限制在候选池/自选股，不全市场噪音扫描。

## 工作流

### 1. 明确参数

先收集最少必要参数：

- 市场：A 股 / 港股 / 美股 / 加密资产；
- 风格：稳健趋势 / 中短线波段 / 高成长 / 低估值反转 / 高风险题材；
- 输出形式：收盘日报 / 盘中提醒 / 两者都要；
- 数据源约束：是否可安装依赖、是否有 Tushare token、是否需要完全免费数据源。

### 2. 将口头策略规则化

把用户提供的“战法”拆成：

- 状态机：D1/D2/D3 或建仓/持有/退出阶段；
- 硬条件：必须满足，机器可判断；
- 排除条件：风险票、出货形态、行情退潮；
- 模糊条件：需要先给近似定义，之后用案例验证；
- 买点/卖点/止损/到期退出；
- 数据需求：日线、分钟线、实时行情、公告/新闻。

优先把“主力”“洗盘”“强势”等主观词翻译为价格、量能、形态和时间窗口。

### 3. 先做离线扫描与回测

推荐阶段：

1. 离线扫描：日线数据 + 候选池 + Markdown 日报；
2. 回测验证：历史样本、胜率、平均收益、回撤、盈亏比、连续亏损；
3. 盘中提醒：只监控昨日候选/自选股，3–5 分钟轮询；
   - 若用户要求“实时监控并通知”，优先落成 `cronjob(no_agent=True)` + 脚本 watchdog：stdout 有内容才投递，静默无信号；脚本内维护去重状态，避免微信刷屏。
   - 若用户要求“建议买入时机”，不要输出确定性买卖指令；用“候选买入时机 / 低吸观察区 / 小仓试错 / 失效位 / 不追高”等语言，把买点表达为可复盘的观察条件。
   - 盘中脚本应同时写结构化事件日志（JSONL）、行情快照（CSV）和普通运行日志，便于收盘复盘。
   - 微信/WeChat 投递股票告警时，若用户要求“每个指标都换行”或截图显示换行被折叠，使用 fenced code block（例如 ```text ... ```）包裹整段告警；不要只依赖普通 `\n` 或 Markdown 段落，因为网关/客户端可能折叠单换行。每只股票一块，每个指标一行。
   - 做投递链路演示时，不要假设 `schedule="1m"` + `repeat=2` 一定会按间隔重复；先用 `cronjob(action='list')` 验证实际 `repeat` 与 `next_run_at`，必要时用两个明确的一次性任务或手动 `cronjob(action='run')` 补发，避免用户等不到第二次。
4. 收盘复盘：定时生成报告，汇总每只候选的触发事件、监控内高低点、观察价/失效位、低吸观察区、次日处理建议。
5. 复盘闭环：记录提醒结果，人工标记有效/误报/错过。

### 4. 数据源建议

MVP 优先顺序：

- `akshare`：快速上手，适合本地 MVP；
- `tushare`：更稳定但需要 token；
- `baostock`：免费但接口体验一般。

少量自选股盘中监控时，可以优先用新浪行情接口 `https://hq.sinajs.cn/list=sh600000,sz000001` 直接取少量代码，避免全市场 AkShare spot 慢或噪音大。具体 watchdog 模式见 `references/a-share-intraday-watchdog.md`。微信告警格式与日志/复盘案例见 `references/a-share-wechat-alert-format.md`。

日线 MVP 需要字段：代码、名称、日期、开高低收、昨收、成交量、成交额、涨跌幅、换手率、涨停价、行业。

盘中 MVP 不需要 Tick 级，先用每 3–5 分钟轮询即可。

## A 股中短线系统默认设计

### 股票池过滤

默认排除：

- ST / *ST / 退市风险；
- 北交所；
- 创业板 / 科创板等 20cm 标的（用户当前无创/科买卖权限）：
  - 过滤 `300/301` 创业板；
  - 过滤 `688/689` 科创板；
  - 只保留沪深主板 10cm：`600/601/603/605`、`000/001/002/003`；
- 上市未满 60 个交易日；
- 20 日日均成交额低于 1 亿；
- 股价低于 3 元；
- 连续一字板或近期异常暴炒。

### 候选池 vs 实际监控池核对

当用户问“D3/D4 是否在监控池”“列一下当前监控池”时，不要只读日报候选文件或凭记忆回答。必须先核对：

1. `cronjob(action='list')`：确认当前启用的监控任务、脚本名、workdir、最近运行状态、投递错误；
2. 读取监控脚本里的实际 watchlist 来源，例如 `scripts/tulong_watchdog.py` 中的 `WATCHLIST_CSV_PATH` / `load_watchlist()`；
3. 读取实际生效的 CSV（例如 `data/watchlists/tulong_d3.csv`），把它与 `0527D3_*`、`0527D4_*` 等候选文件分开列；
4. 对每只股票按代码前缀标注板块/涨跌幅规则，显式指出 `300/301/688/689` 是否混入；
5. 若候选文件未被监控任务读取，要明确说“候选存在，但当前不在实际监控池”，并给出需要替换/合并监控池的下一步。

如果发现实际监控池混入 20cm 标的，先标为“应剔除”，不要继续把它当作可执行候选。

### 替换监控池时必须同步替换指标

当用户要求把某个候选池（例如 `0527D3_candidate_AND.csv`）切入盘中提醒时，不要只复制 `code/name/trigger_price/invalid_price`。必须同时处理：

1. **保留候选文件里的指标字段**：至少保留 `industry`、`zone_low`、`zone_high`、`score`、`rank`、`note`；否则低吸观察区等指标会被脚本用旧公式或默认公式重新计算，看起来像“指标还是旧的”。
2. **确认监控脚本会读取这些字段**：`load_watchlist()` 应读取 `zone_low/zone_high`；`entry_zone()` 应优先使用 CSV 中的 `zone_low/zone_high`，缺失时才回退公式计算。
3. **同步复盘脚本的数据源**：收盘复盘/日报脚本不要 import 静态 `WATCHLIST`，应调用同一套 `load_watchlist()` 并把 `fetch_quotes(watchlist)` 传入实际池；否则盘中监控是新池，复盘仍可能显示旧四股/旧指标。
4. **更新用户可见标题与口径**：快照/复盘标题中的“四股”“旧日期”“旧池名”要随实际池更新，例如改为“0527D3主板7股盘中快照”。
5. **重置或隔离状态文件**：切池后清空旧 `sent`、`last_prices`、`pending_snapshot`，并记录 `watchlist_source`，避免旧票去重和旧价格穿透到新池。
6. **验证不只看文件内容**：替换后运行一次脚本级验证，检查 `load_watchlist()` 输出、`entry_zone()` 输出、快照标题、事件 JSONL/快照 CSV 的最新行是否都是新池。

常见漏改：只替换监控 CSV，但 `tulong_review.py` 仍 import 静态 `WATCHLIST`；只写观察价/失效位，但丢失 `zone_low/zone_high`；只看候选文件，以为已经入池，却没有确认 cron 实际读取的 CSV。

### Reference 文件分工

本 skill 的 reference 只在这里维护分工说明，避免各文件重复解释关系：

- `references/tulong-d3-d4-monitoring.md`：**当前主规则**。维护屠龙 D3/D4 的日期+D几、D3候选区、D4持有区、提醒指标、频率、事件优先、监控池替换验证。后续确认的新 D3/D4 规则优先更新这里。
- `references/tulong-a-share-mvp.md`：**历史底稿 / 原始战法规则化**。保留早期 D1–D5 状态机、口头规则、正反案例、回测背景；若与当前主规则冲突，以 `tulong-d3-d4-monitoring.md` 为准。
- `references/a-share-intraday-watchdog.md`：**工程运行方案**。维护少量自选股盘中监控的 watchdog、cron/no_agent、行情接口、日志、JSONL/CSV、去重、静默输出等实现方式。
- `references/tulong-script-organization.md`：**脚本目录/cron迁移方案**。维护 `scripts/tulong/runtime|selection|legacy` 分层、Hermes cron wrapper 迁移、README、验证和“完成/未验证”汇报边界。
- `references/tulong-parameterized-selection.md`：**参数化候选池生成器方案**。维护把写死日期的一次性 D3 选股脚本改为 `generate_d3_candidates.py --d1-date --d2-date --d3-date/--d3-label` 的 CLI、输出命名、测试和验证步骤。

### 屠龙 D3/D4 监控专题

当用户讨论“屠龙战术”、D3候选区、D4持有区、日期+D几（如 0527D3/0527D4）、盘中提醒、买点/止损/参与区、监控池替换时，必须加载：`references/tulong-d3-d4-monitoring.md`。

摘要：D3 候选区 = 低吸可执行性 AND 强势潜质；D3 看买点区、回收观察价、止损；买入后进入持仓事实层，按 T+1 可卖性管理，验证期不预设 D4/D5 卖出/加仓策略（已移除，待验证后另定）；事件检测 5 分钟，快照 15 分钟，事件优先，快照被事件挤掉后约 3 分钟补发。

### 大盘/情绪过滤

短线策略不是每天都做。建议分为：

- 可交易：指数在 MA20 上方、涨停家数较多、跌停少、连板高度尚可；
- 谨慎：震荡分歧，只提示最强信号；
- 防守：指数破位、跌停多、高位股 A 杀，只提示风险不提示新买点。

### 日报结构

日报应包含：

- 大盘状态；
- 策略候选池；
- 每个候选的入选理由、观察价、触发价、失效价、风险；
- 明日盘中重点监控；
- 风险开关。

## 屠龙战术规则化参考

详细 D3/D4 执行规则见：`references/tulong-d3-d4-monitoring.md`。旧版 MVP 规则参考：`references/tulong-a-share-mvp.md`。

使用时重点注意：

- 这是首板后的短线事件交易，不是普通价值/趋势投资；
- 术语要收敛：规则描述统一使用“D1过滤规则”“D2过滤规则”或“D1/D2过滤规则”，不要混用“硬过滤”“硬条件”“基础风险过滤”等近义词；
- D2 是核心过滤日：要区分“分歧洗盘”和“高开低走出货”；
- D3 只做水下观察，跌破 D1 支撑则策略失效；
- 买入后的退出/加仓策略（原 D4/D5 规则）验证期已移除，不预设，待数据验证后另定；
- 需要先回测正反样本，再考虑盘中提醒。

## 项目脚手架建议

若用户要新建项目，推荐结构：

```text
stock-assistant/
├── config/                 # 股票池、策略、提醒参数
├── data/                   # raw/processed/watchlists
├── reports/                # daily reports
├── src/stock_assistant/    # data, indicators, strategies, scanner, reporter
├── backtests/              # 回测入口
├── tests/                  # 基础测试
├── README.md
├── docs-plan.md
└── pyproject.toml
```

验证时若未安装成包，可用：

```bash
PYTHONPATH=src python -m stock_assistant.scanner
```

不要因为当前环境缺少 pytest、akshare、tushare token 等就写入长期负面结论；这类是环境状态，不是策略规则。

## 常见错误

- 一上来做实时系统，策略本身没回测；
- 把“候选信号”写成“买卖建议”；
- 给太多候选，导致提醒噪音；
- 只写入场条件，不写退出/失效；
- 用日线强行解释需要分钟线的“启动前位置”；
- 忽略市场情绪，导致退潮期仍持续提示买点；
- 没有复盘记录，无法判断策略是否只是幸存者偏差。
