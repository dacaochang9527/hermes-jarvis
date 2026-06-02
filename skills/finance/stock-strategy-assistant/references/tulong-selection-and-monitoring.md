# 屠龙 D3 选股与持仓监控

> 验证期调整（2026-05-30）：屠龙战法处于验证阶段，**买入后的决策策略（卖出、加仓、止盈、止损、留仓等）已暂时移除，不再预设**，以免约束后续策略制定。
> 本文继续保留的部分：D1/D2/D3 选股过滤、观察 vs 持仓的事实区分、T+1 可卖性、开盘前换日切池/守门等**工程事实**。凡“持仓应如何卖、如何加、如何止损止盈”的动作规则均已中性化为占位，待数据验证后另行制定。
>
> 持仓标签约定：买入后统一记为 `stage=HOLD`（无日期前缀、不分第几天），持有时长由 `entry_date`（T+1 可卖性）派生；未买入观察票仍用带日期的 `MMDDD3`。已不再使用 `D4/D5` 这类带日期的持仓阶段标签。

## 场景

用于 A 股“屠龙战术”D1/D2/D3 选股与盘中提醒：D3 只监控当天观察区；买入后进入持仓事实层，按 T+1 可卖性管理，验证期不预设卖出/加仓策略。核心目标是把提醒做成“可执行区提醒”，而不是状态播报。

## 状态表达规范

观察票（未买入）在股票池、提醒和复盘中优先使用 **“日期 + D几”**，周几仅作辅助，例如：`0527D3`。持仓票（已买入）统一记为 `HOLD`，不带日期、不分第几天。

推荐写法：

- `0527D3观察区`：5 月 27 日当天正处 D3 观察/低吸窗口；不要再命名为“低吸池”。
- `0526D3观察 → 买入后 HOLD 持仓`：D3 观察票一旦买入即转为 `HOLD` 持仓；持有第几天/可卖性由 `entry_date` 派生，不再用日期前缀表达。
- `HOLD` 只用于已买入持仓（`pool_type=position`）；未买入观察票即使走强，也仍是 `MMDDD3`，不会变成 `HOLD`。
- 源文件落盘时，文件名尾部必须带年月日+时分秒时间戳，并显式包含分区：`MMDDD3_watch_<原因>_YYYYMMDD_HHMMSS.csv`、`HOLD_position_<原因>_YYYYMMDD_HHMMSS.csv`。其中 `<原因>`（如 `scan`、`manual_review`、`position_rollover`）只用于人类理解这次改动来源；监控池选择数据源时，watch 取当日 `MMDDD3_watch_*` 最新，position 取 `HOLD_position_*` 全局最新（不按日期前缀）。不要再生成或依赖仅带 `HHMMSS` 的新文件；看文件名尾部时间戳就应能判断哪个更新。找不到新格式文件时必须失败提醒，而不是静默使用旧格式。
- `0526D3未走强 → 0527删除`：前一日 D3 没走强，次日不再留在观察区。
- `0527新D3观察区`：5 月 27 日新生成的当天 D3 票。

D3 观察区只放当天 D3。前一交易日已经是 D3 的未买入观察票，次日不继续留在 D3；只有买入的持仓才转为 `HOLD`，并按 `HOLD_position_*` 最新快照滚动续期。

## D3 观察区规则

D3 当天统一称为 **D3 观察区**，不是“低吸池”。D3 观察区不是“低吸潜质 OR 强势潜质”的并集，而是：

```text
低吸可执行性 AND 强势潜质
```

这里的“低吸可执行性”不是把 D3 简化成只做低吸；它表示**必须有舒服的参与/风控点**。D3 应分成至少两类观察：

1. **D3低吸观察**：回落到买点区、失效位清楚、风险收益比舒服；
2. **D3强势观察/回收确认**：D2结构强、D3不一定给深水低吸，但可观察回收观察价、突破前高、强回封或板块共振；
3. **D3持仓管理**：若已买入，立即转为 `HOLD/position` 管理 T+1 当日风险，不能和未买入观察混写。

因此，生成和解读 D3 时不要只写“低吸池”或只按“水下低吸”排序；必须同时评价：

- 低吸可执行性：买点区、止损/失效位、安全垫是否舒服；
- 强势潜质：D1封板结构、D2承接、板块共振、回收/突破空间、成交是否可跟踪；
- 可执行分类：核心观察、强势确认观察、低频观察/备选、持仓区。

观察标的必须同时满足：

- 有清楚的买点 / 止损 / 回落承接位置；
- 具备 D3 回收观察价并向上扩展的可能。

排除：

- 低吸但没有强势潜质的弱修复票；
- 强但没有合理低吸/承接参与点的追高票。

默认容量与观察分类：

- D3 观察区：8–10 只，避免 4 只过窄漏掉结构好的票；
- 高频/强提醒：不超过 4–5 只，只对真正进入买点附近、接近失效、回收观察价、明显异动的票发单股提醒；
- 其余观察区票只进低频快照。

跨池去重与点位有效性：

- 确认或更新次日 `MMDDD3观察区` 时，必须先读取已确认/已落盘的 `HOLD_position_*_YYYYMMDD_HHMMSS.csv`。如果同一只票同时满足新 D3 扫描和既有 HOLD 持仓，默认保留在 HOLD 持仓，不重复放入 D3；除非用户明确要求双标签跟踪。
- D3 观察区生成后要检查 `zone_low <= zone_high`。若 `max(invalid*1.015, trigger*0.985) > trigger*1.003` 导致观察区倒挂，说明触发价离失效位太近或点位不舒服，应降为备选/剔除，而不是直接进入高频监控。
- D3 观察与 HOLD 持仓同时存在时，用户可见结论要分开写：先说明 HOLD 持仓已落盘状态，再单独给 D3 初选/建议名单，避免把 D3 观察与 HOLD 持仓混成一个池。

## D1/D2 过滤规则术语

术语要收敛，避免同一类规则在文档、代码和回复中出现多个近义词。统一使用：

- `D1过滤规则`
- `D2过滤规则`
- `D1/D2过滤规则`

不要混用“硬过滤”“硬条件”“基础风险过滤”等说法。若需要区分具体内容，直接写规则项本身，例如“主板10cm、非ST、首板、D2量能2倍以内更好但3倍内可结合其他条件保留、D2冲高回落、D2收盘不破D1支撑”。

## D1 首板底池规则与落盘职责

D1 是后续 D2/D3 的输入底池，必须先作为独立阶段落盘，不要把 D1 过滤、D2 确认、D3 自动窄化混在同一个临时判断里。

### D1 过滤规则

输入通常来自当日涨停池，例如 `ak.stock_zt_pool_em(date=D1_DATE)`。D1 底池只应用 D1 过滤规则，不做 D2 形态判断。

保留条件：

- 沪深主板 10cm 标的；
- 非 ST / *ST / 退市风险；
- 当日首板：`涨停统计` 形如 `1/x` 或 `连板数 == 1`；
- 用户当前无创/科权限时剔除 `300/301/688/689`，同时剔除北交所等非主板前缀。
- D1 封板结构可接受：早盘/上午封板更优；尾盘封板、长期封不住、反复烂板、封板资金弱，需要结合 D2 验证后决定是否保留。
- D1 炸板不能只看接口次数：0 次最好，1–2 次可接受；多次炸板必须结合回封速度、最后封板时间、封板资金和用户分时图校正。
- D1 成交额/换手需要可跟踪：过小难跟踪，过大可能拥挤，需要结合 D2 承接继续过滤。

剔除条件：

- 20cm / 北交所 / 非主板；
- ST、*ST、退市风险；
- 非首板：2连板、3连板、4连板等；
- 虽然强势但不属于当前 D1 首板定义的趋势票或连板票。
- D1 反复烂板、长时间封不住、封板资金弱，且 D2 未能给出有效承接验证。

D1 底池保留字段至少包括：

```text
code, name, industry, pct, price, amount_yi, turnover,
fund_yi, first_seal, last_seal, breaks, stat, limit_boards
```

注意：D1 只产生“首板底池”。是否进入 D3，还必须经过 D2 确认和自动窄化。

### D1 规则文件分工

为避免规则漂移，D1 规则应分三层落盘：

1. **Skill/reference = 规则说明书**
  - 维护在本文件；
  - 说明 D1 定义、D1过滤规则、D2过滤规则、人工校正口径；
  - 给人和 agent 对齐判断标准。
2. **`src/stock_assistant/strategy_tulong.py` = 规则执行器**
  - 实现可复用函数，例如 `is_main_board_10cm()`、`is_excluded_name()`、`is_first_board_from_zt_row()`、`evaluate_d1_board()`；
  - 返回结构化结果：`passed/reject_reason` 等；
  - 所有脚本都应调用这里，不要在临时脚本里复制硬编码规则；
  - 若发现 `scripts/tulong/selection/generate_d3_candidates.py` 内仍保存 `EXCLUDE_PREFIXES`、`EXCLUDE_NAME_PARTS` 或 D1 过滤规则函数，应优先用 TDD 将其下沉到本模块，再让脚本只做 CLI/data IO/write outputs。
3. **`scripts/*.py` = 流程编排器**
  - 负责读取数据源、调用规则执行器、写出 CSV/Markdown；
  - 不应成为唯一保存规则的地方。

### D1 → D2 → D3 阶段流转与职责边界

这里描述的是“阶段产物如何流转”，不是新增规则所有者，也不是要求每天复制一个新的独立规则脚本。规则分工仍以上一节为准：

- 本 reference 只定义 D1/D2/D3 的规则口径；
- `src/stock_assistant/strategy_tulong.py` 只负责执行可复用规则；
- `scripts/tulong/selection/*.py` 只能作为流程编排入口：拉取数据、调用 `strategy_tulong.py`、写出 CSV/Markdown。

因此，生成 D1/D2/D3 产物时，无论入口脚本叫什么，都必须满足：

1. **D1 收盘后**
  - 从当日涨停池拉取数据，例如 `ak.stock_zt_pool_em(date=D1_DATE)`；
  - 调用 `strategy_tulong.py` 的 D1 过滤函数；
  - 只落盘 D1 底池，不做 D2 形态判断；
  - D1 产物归属到对应 D3 扫描链路：例如 `0527D1` 对应 `0529D3_D1_filtered_YYYYMMDD_HHMMSS.csv/.md`，表示“这份 D1 过滤结果服务于 0529D3 扫描链路”。
2. **D2 收盘后**
  - 读取已落盘的 `{D3_LABEL}_D1_filtered_*.csv`，或在同一个参数化入口中复用同一套 D1 过滤结果；
  - 再调用 `strategy_tulong.py` 的 D2 确认规则：量能2倍以内更好但3倍内可结合其他条件保留、冲高回落、未破 D1 支撑、形态过滤判断；
  - 输出 `data/watchlists/MMDDD3_scan_YYYYMMDD_HHMMSS.csv` 和 `reports/daily/MMDDD3_scan_YYYYMMDD_HHMMSS.md`。
3. **生成/更新 D3 初选时自动窄化**
  - 每次生成或更新 D3 初选时，立即按“低吸可执行性 AND 强势潜质”自动窄化；
  - 输出核心 D3 观察、D3 强势确认观察、低频备选、剔除、持仓区；
  - 自动窄化结果直接落盘为 `data/watchlists/MMDDD3_watch_scan_YYYYMMDD_HHMMSS.csv`；后续如有人工修正，再另存为 `MMDDD3_watch_manual_review_YYYYMMDD_HHMMSS.csv`。
4. **次日开盘前**
  - `preopen_rotate_watchlist` 合并当日 `MMDDD3_watch_*` 观察源与最新 `HOLD_position_*` 持仓源；
  - 写入实际监控池 `data/watchlists/tulong_active_watchlist.csv`。

命名纪律：当前屠龙流程不使用独立 `MMDDD1_filtered_*` 分支。明确某天 D1 时，应按交易日推导对应 D3 标签并命名为 `{D3_LABEL}_D1_filtered_*`；例如 `0527D1` 固定对应 `0529D3_D1_filtered_*`。不要把命名问题误判为规则所有权问题：无论入口脚本如何编排，D1 过滤规则都不能写进一次性脚本，必须调用 `strategy_tulong.py`。

### D1 底池全量表现复盘

当用户指定 `{MMDDD3}_D1_filtered_*` 文件并问“这里面的票今天表现如何”时，口径是 **D1 首板底池全量复盘**，不是实际 D3 watch 监控池复盘。必须显式区分三层：

1. **D1 filtered 全量底池**：只经过 D1过滤规则，尚未经过 D2/D3 窄化；
2. **D3 watch 观察池**：经过 D2确认和 D3 自动/人工窄化，偏向“低吸可执行性 AND 强势潜质”；
3. **HOLD 持仓**：买入后的事实层，不混入未买入观察票表现统计。

推荐分析步骤：

1. 读取用户指定的 `{MMDDD3}_D1_filtered_*` CSV，统计全量代码数、行业、D1封板时间、炸板次数、成交额等；
2. 读取同标签最新 `MMDDD3_watch_*`，给每只 D1 底池标注 `in_watch=true/false`；
3. 获取当日收盘行情，按涨跌幅、是否涨停/近涨停、成交额、盘中高低、收盘相对高低分层；
4. 分开输出：
   - D1底池总体分布；
   - 已入 D3 watch 的表现；
   - 未入 watch 但强势延续的漏选样本；
   - 未入 watch 且走弱的合理剔除样本；
5. 结论要服务于规则验证：当前 D3 watch 若偏低吸，可能漏掉“D1底池强势延续但未入 D3 watch”的样本，这类应进入 `D3强势雷达/漏选复盘`，但不要自动等同为低吸观察票。

行情获取建议：若 AkShare 东方财富历史或全市场接口临时断开，不要直接放弃；可用新浪少量行情接口批量拉取同一底池代码：`https://hq.sinajs.cn/list=sh600000,sz000001...`。该接口适合几十只自选代码的收盘复盘，可得到开盘、昨收、收盘、最高、最低、成交额和日期时间；注意加 `Referer` / `User-Agent`，并按代码前缀生成 `sh` / `sz` symbol。

### 规则维护纪律

规则演进原则：屠龙 D3 选股规则会随着复盘持续调整。若同一规则链路内前后描述出现冲突，优先采用后续新确认的规则；确认加入的新规则必须回写到原有 `D1过滤规则` 或 `D2过滤规则` 对应条目里，直接修改原规则，不保留“旧规则 + 新补充”的并列层。

### D2 过滤规则

D2 确认在 D1 底池基础上执行。遇到周一/节假日必须按真实交易日回退，不按自然日推导。

保留条件：

- D2 量能在 D1 2 倍以内更好；
- 若 D2 量能为 D1 2–3 倍，只要其他 D2 条件都符合，仍可保留；
- D2 不能过度缩量，缩量过弱说明承接和分歧交换不足，不应只把“低量比”理解为安全；
- D2 必须有盘中上冲和冲高回落，且收盘不跌破 D1 支撑；
- D2 收盘近十字 / 分歧平衡最好：代表分歧存在但未明显走坏，优先保留；
- D2 成交额、换手率需要可跟踪，过小难跟踪，过大可能拥挤；
- D2 未明显走坏：仍大涨容易变追高，跌幅过深说明承接不足，都需要进入保留或剔除判断。

剔除条件：

- D2 成交量超过 D1 3 倍；
- D2 缩量过弱；
- D2 盘中冲高不足；
- D2 冲高回落特征不足；
- D2 收盘跌破 D1 支撑位；
- D2 高开低走，疑似出货；
- D2 上引线太长、收盘离高点太远，说明上方抛压重，D3 承压风险升高。

这些判断属于生成 `0527D3观察区` 的 D1/D2 过滤规则，不属于 HOLD 持仓的监控指标。

### D3 自动窄化复核清单

每次机械扫描给出或更新 D3 初选后，必须立即自动执行一轮窄化，保证输出的 `MMDDD3观察区` 与最新规则一致。窄化不受时间段限制，也不等用户下一轮确认才执行；后续人工复核只负责修正自动窄化结果，不再作为唯一窄化步骤。

1. **先查重**：读取已确认/已落盘的 HOLD 持仓；同一只票默认保留在 HOLD，不重复放入 D3，除非用户明确要求双标签。
2. **点位有效**：检查 `zone_low <= zone_high`，且观察区不能过度贴近失效线；若安全垫过薄或观察区倒挂，剔除/降为备选。
3. **AND 口径**：必须同时具备“低吸可执行性”和“强势潜质”，不能只因 D2 符合冲高回落就入池。
4. **D2 形态**：优先收盘近十字/分歧平衡、量比健康、回落充分但未破位；D2 缩量过弱、上影过长、收盘离高点太远、高开低走出货倾向都要纳入保留或剔除判断。
5. **D1 封板结构**：早盘/上午封板优于尾盘；炸板但快速回封可接受；反复烂板、长时间封不住、封板资金弱都要纳入保留或剔除判断。
6. **拥挤度**：成交额过大或过热时不要只当备注，应正式纳入保留或剔除判断；对 D3 低吸观察，成交适中且可跟踪更优。
7. **人工分时校正**：若用户根据分时图纠正接口字段（如“实际没有明显炸板”），应修正判断并在落盘 note 中保留校正原因。

输出时直接给出自动窄化后的观察名单，并在报告里列出未输出原因。若用户之后确认人工修正名单，再落成 `MMDDD3_watch_manual_review_YYYYMMDD_HHMMSS.csv`。

### D3 两层输出：低吸观察池 + 强势延续雷达

连续复盘 0601D3 与 0602D3 后确认：D3 不能只维护一个 watch 池。当前规则应显式分成两条线：

1. **低吸观察池 / watch**
  - 继续坚持 `低吸可执行性 AND 强势潜质`；
  - 用于买点区、观察价/回收价、失效线、微信单股事件提醒；
  - 入池重点是“有舒服参与点，且进区后有回收观察价的可能”；
  - 不因盘中一时活跃而把前面 D1/D2 结构差的票抬高。
2. **强势延续雷达 / radar**
  - 从 D1 filtered 全量底池中单独发现，不直接并入低吸 watch；
  - 记录“未入 watch 但 D3 当日强势延续”的漏选样本，例如 D3 涨停、涨幅 >= 5%、盘中高点接近涨停且收盘未明显回落、同板块强于已入 watch 标的；
  - 用途是复盘规则、板块强弱排序和漏选分析，不输出追高买点，也不触发低吸提醒。

两条线解决不同问题：低吸观察池负责“能不能舒服参与”，强势延续雷达负责“有没有漏掉真正强的”。不要为了捕捉强势延续而无边界扩大 watch 池；这会增加提醒噪音并稀释可执行性。


处理纪律：

1. **先核验基础 D3 条件**：确认 D1 首板、D2 冲高回落/未破 D1 支撑、D2 量能不超过 3 倍且 2–3 倍时其他条件足够补强、主板 10cm、无 ST/退市风险；若只是板块热门但没有 D3 结构，要明确标为“非标准人工观察”。
2. **尊重用户明确观察口径**：若用户明确说“作为强提醒追高票”，可以写入 `stage=MMDDD3`、`pool_type=watch`，但 `note` 必须写清 `manual_add_strong_chase`，并在回复中说明这是强提醒追高观察，不是低吸买点。
3. **点位不要沿用低吸模板**：
  - `trigger_price` 优先用 D2 高点/前高/盘中高点等强势确认位；
  - `zone_low/zone_high` 用接近突破/回收区，例如前高下方一段到前高；
  - `invalid_price` 不宜贴着当前价或昨收，否则脚本会立刻报“跌破止损”；应使用当日关键承接位、D2 收盘下方的确认失效位或用户认可的更紧失败线，并在 `note` 写明“跌回某价下方降级”。
4. **必须同步两个文件**：同时更新人工源文件（如 `MMDDD3_watch_manual_review_YYYYMMDD_HHMMSS.csv`）和实际 active 池 `data/watchlists/tulong_active_watchlist.csv`；只改 active 会导致次日/新会话丢失，只改源文件会导致当前 watchdog 不生效。
5. **清理状态避免误判**：清除该代码在 `last_prices` 中的旧状态，避免上一轮价格导致穿越类事件判断失真；如果刚用错误点位触发过合成验证提醒，修正点位后重新验证用户可见文本。
6. **验证用户可见文本**：运行脚本级验证或生成一次 `FORCE_RUN=1` 输出，确认单股行显示正确 `stage`、行业、状态、买点/强提醒区、失效线；如果立即显示“跌破止损”，优先复核 `invalid_price` 是否设置过紧。

推荐 `note` 示例：

```text
MMDDD3｜watch｜manual_add_strong_chase｜用户指定强提醒追高票｜D1=xxxx首板｜D2=xxxx冲高回落未破位、量能未超3倍且其他条件补强｜强提醒口径：只看放量进入xx–xx或突破xx；跌破xx放弃，跌回xx下方降级，不按低吸票处理
```

## D3 提醒指标与格式

D3 单股提醒围绕“能不能动手”和“错了怎么办”，不要堆指标。

字段优先级：

1. 状态：`买点区` / `水下观察` / `回收观察价` / `接近失效` / `跌破失效` / `强势不追`；
2. 点位：现价、涨跌幅、买点区、观察价/回收价、止损/失效位；
3. 动作：等、可小仓观察、放弃、不追；若已买入则转为 HOLD 持仓管理；
4. 参考：行业/板块、距止损、成交额、时间。

D3 单股提醒 4 行模板：

```text
0527D3｜代码 名称｜行业｜水下观察/买点区/回收观察价/接近失效/跌破失效/强势不追
现价 xx（+x.xx%）｜买点 low–high｜止损 invalid
动作：只等回到买点区/回收trigger；跌破invalid放弃
参考：距止损+x.x%｜成交额x.xx亿｜HH:MM
```

示例：

```text
0527D3｜600530 交大昂立｜食品加工｜水下观察
现价 7.15（-2.19%）｜买点 7.20–7.33｜止损 6.85
动作：只等回到买点区/回收7.31；跌破6.85放弃
参考：距止损+4.4%｜成交额1.52亿｜14:40
```

字段取舍：

- 涨跌幅保留：放在现价后括号里，用于快速感知行情温度。
- 成交额保留，命名为成交额，不叫量能；量比等量能指标在筛选阶段使用，不在提醒里重复展示。
- 行业/板块保留：放在第一行股票名后，用于判断板块共振；取不到时用 D1 涨停池所属行业兜底。
- 去掉或降级展示：昨收、今开、最高、最低、安全垫等原始行情字段，除非直接影响动作。

D3 快照与单股触发提醒使用同一套指标，只是时间用完整 `YYYY-MM-DD HH:MM:SS`。

## 买入后持仓管理（验证期：策略已移除）

验证期内不预设买入后的退出/加仓策略。原“持仓决策规则”（止损/止盈/减仓/加仓/留仓的触发原则与提醒模板）已整体移除，避免约束后续策略制定。

当前仅保留**事实层**：

- 持仓身份：`pool_type=position`（已买入），与 `watch`（未买入观察）区分；
- T+1 可卖性：买入当天 `sellable_quantity=0` 不可卖，次日起解禁可卖（由 `entry_date` 派生）；
- 事实指标：成本、现价、相对盈亏、距失效位、可卖数量、当日强弱——只呈现，不给“该卖/该加/止损止盈”的硬结论。

待积累足够持仓生命周期数据、并通过回测/复盘验证出稳定规则后，再在此回填具体的退出/加仓提醒口径。

## 盘中提醒频率与发送规则

- 事件检测：每 5 分钟；
- 快照生成/提醒：每 15 分钟；
- 收盘复盘：15:10 左右；
- 有单股事件时立即发，不等快照点；
- 同一轮既有事件又到 15 分钟快照点时，**事件优先**，先发事件，不叠加快照；
- 被事件挤掉的快照不能丢，保存为待发送快照，约 3 分钟后补发；若 3 分钟后又有新事件，继续事件优先，但待发送快照可合并/替换为最新 15 分钟快照；
- 非 15 分钟整点且无事件时静默，避免微信/iLink 限流；
- 每次事件检测只要条件满足就允许提醒；不做“同一股票 + 同一事件 + 同一天最多一次”的去重。

- 盘中推送应优先采用 Weixin/iLink 防限流模式：只推送单股事件，15 分钟全量快照只写本地文件；多只股票同轮触发时不合并摘要，按单股告警块分别输出。若用户反馈 10:45 后等时间点微信侧不再收到，先查 cron output 与 gateway/agent 日志中的 `iLink sendmessage rate limited`，不要只看 `last_status=ok` 就断定投递正常。具体排查与降噪实现见 `references/a-share-intraday-watchdog.md`。

### 监控池组成：watch + OPEN HOLD

日内“实际监控池”不能只看当天 `MMDDD3_watch_*` 观察票。必须同时合并：

- 当天最新 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv`：未买入观察票；
- 最新 `HOLD_position_*_YYYYMMDD_HHMMSS.csv` 中 **`position_status=open`** 的持仓：已买入且仍持有；
- **`position_status=closed` 的 HOLD 行不进入当前监控池**，只能作为历史复盘/已完成持仓记录。

判断“今天有哪些股票进监控池”时，默认口径是 **watch + open HOLD**，不是只有 watch。若 active CSV 里只剩 watch，必须检查是否漏合并了 open HOLD；若 HOLD 源里只剩 closed，则不要误把它们算进监控池。

工程硬要求：

- `preopen_rotate_watchlist.py` 合并 `HOLD_position_*` 时必须逐行过滤 `position_status != open`，将 closed/空状态写入 `filtered_out`，不得写入 `tulong_active_watchlist.csv`；
- `tulong_d3_monitor_state.json` 的 `stages` / `pool_types` 必须按**实际入池行**重算，不要因为读取了 HOLD 源文件就保留 `HOLD/position`；
- `preopen_guard_check.py` 必须把 active 池中任何 `pool_type=position && position_status!=open` 视为错误；
- `watchdog.load_watchlist()` 也应防御性跳过 closed HOLD，避免切池脚本漏过滤时继续提醒；
- 当用户质疑“已清仓为什么还提醒”，优先检查 active CSV 是否混入 closed HOLD、state 的 last_prices 是否包含该代码、以及切池/守门是否只看 source 文件而没看实际入池行。




今天暴露的问题：开盘前实际监控池仍是前一交易日 D3，导致开盘后旧池继续触发提醒。这个问题必须作为固定流程处理，不能依赖盘中人工发现后再替换。

推荐解决方案：

1. **T-1 收盘后生成次日池**
  - 收盘复盘后，根据当天 D3 表现生成次日流转结果：
    - D3 已买入持仓 → `HOLD` 持仓（无日期前缀，按 `entry_date` 续期）；
    - D3 未买入观察票 → 次日删除，不进入 `HOLD`；
  - 同时生成次日新 D3 观察区。
2. **T 日开盘前切换实际监控池**
  - 最晚在 09:00 前完成监控池替换；更稳妥是 08:50–08:55 执行；
  - 实际监控池统一写入 `data/watchlists/tulong_active_watchlist.csv`，不要再用 `tulong_d3.csv` 表达 active 池；
  - active CSV 必须包含 `stage`、`pool_type`、`source_file` 字段，用于区分 `0528D3/watch`（观察）与 `HOLD/position`（持仓）等来源；
  - 因当前盘中 watchdog 的 cron 会在 09:00 后开始运行，脚本内交易窗口 09:25 生效，所以 09:00 前替换可以避免旧池在集合竞价/开盘后继续生效。
3. **开盘前守门校验**
  - 09:05–09:15 做一次自动校验：读取实际 active watchlist 的 `watchlist_source`、日期+D几、股票列表和代码前缀；
  - 若仍是昨日池、混入 20cm、缺少今日 `0527D3` 观察或 `HOLD` 持仓来源，必须发错误提醒或暂停监控，不应静默继续。
4. **切池时同步清状态**
  - 清空或隔离旧 `sent`、`last_prices`、`pending_snapshot`；
  - 记录 `watchlist_source`、`watch_date`、`stage`（如 `0527D3` / `HOLD`）和 `updated_at`；
  - 强制运行一次脚本级验证，确认 `load_watchlist()` 实际读到新池。

执行时间建议：

```text
15:10–15:30  收盘复盘：生成 D3 表现、HOLD 持仓续期、次日新 D3 观察
08:50        开盘前切换实际监控池：写入今日 MMDDD3 watch 与最新 HOLD position，重置状态
09:05        守门校验：确认实际监控池日期、阶段、列表、20cm过滤、来源字段
09:25–15:00  盘中监控：只使用已校验的今日池
```

如果 08:50 切池失败，09:05 守门校验必须提醒“监控池未更新/疑似昨日池”，而不是继续使用旧池。

### 开盘前切池/守门工程落地要点

当需要把上述规则落成 Hermes cron/watchdog 时，优先采用两个独立 `no_agent=True` cron：

```text
preopen_rotate_watchlist    08:50 每交易日执行，成功静默，失败 stdout 投递
preopen_guard_check         09:05 每交易日执行，成功静默，失败 stdout 投递
```

推荐实现职责：

1. `preopen_rotate_watchlist`
  - 查找今日 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv` 与全局最新 `HOLD_position_*_YYYYMMDD_HHMMSS.csv`：watch 类按当日显式 `YYYYMMDD_HHMMSS` 取最新，HOLD 持仓取全局最新（不按日期前缀，持仓自然滚动续期）；中间 `<原因>` 只作为改动来源，不参与优先级；自 0528 起不再兜底无时间戳旧名，找不到任何新格式文件就失败提醒；
  - 合并写入实际监控池 `data/watchlists/tulong_active_watchlist.csv`；
  - active CSV 字段至少包含：`code`、`name`、`industry`、`stage`、`pool_type`、`source_file`、`trigger_price`、`invalid_price`、`zone_low`、`zone_high`、`rank`、`score`、`note`；持仓行还必须包含 `entry_date`、`entry_stage`、`entry_price`、`quantity`、`sellable_quantity`、`cost_amount`、`position_status`；
  - 过滤用户无权限的 20cm / 非沪深主板：`300/301/688/689`、北交所等；
  - 保留 `industry`、`trigger_price`、`invalid_price`、`zone_low`、`zone_high`、`rank`、`score`、`note`；
  - 切池前备份旧 active CSV；
  - 重置状态：`last_prices={}`、`pending_snapshot=null`；
  - 写入状态元数据：`watchlist_source`、`watch_date`、`stage=MMDDD3`、`updated_at`、`filtered_out`；
  - 调用监控脚本的 `load_watchlist()` 做脚本级验证，确保不是只改了文件但运行时仍读旧硬编码池。
2. `preopen_guard_check`
  - 读取实际 active CSV 与状态文件，而不是观察源文件；
  - 校验 `watch_date` 为今天、`stage` 为今日 `MMDDD3`、`watchlist_source` 包含今日 D3 且不包含昨日 D3；
  - 校验 active CSV 非空、无 20cm、关键字段齐全；
  - 再次调用 `load_watchlist()`，确认脚本读取结果与 CSV 代码列表一致；
  - 正常时静默，只写日志；异常时 stdout 输出清晰错误，让 cron 投递到微信，必要时提示“监控池未确认，需暂停旧池风险”。

实践注意：

- `no_agent=True` cron 的 stdout 非空会直接投递；因此成功路径应保持空输出，避免每天固定刷屏；失败/异常路径再输出用户可读消息。
- 如果当日没有 HOLD 持仓来源文件，守门任务可记录 warning，但不要因此阻断 D3 切池；只有存在真实持仓时才需要补 HOLD 持仓续期。
- 调度顺序应早于盘中 watchdog：08:50 切池、09:05 守门、09:25 后盘中有效。

## 观察区/持仓区确认后的即时落盘纪律

当用户确认次日 `MMDDD3` 观察或 `HOLD` 持仓名单时，不能只在聊天中复述“已确认”。如果用户明确说“新会话还要继承/明天监控/是否落盘”，必须立即核对或生成对应源文件：

1. 每个分区都要有独立源文件：
  - D3观察区：`MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv`；
  - HOLD 持仓：`HOLD_position_*_YYYYMMDD_HHMMSS.csv`。
2. 不要把“实际 active 池里已有持仓”误判为“持仓源文件也已落盘”。必须分别检查 D3 watch 与 HOLD position。
3. 不要再生成或依赖 `HOLD_watch_*` / `D4_strong_radar_*` / `MMDDD4_*` 文件；HOLD 只接受 `HOLD_position_*`。
4. 如果聊天里已经确认了名单但文件不存在，应直接说明“未完全落盘”，列出已落盘/未落盘分区，并请求或执行落盘；不要告诉用户新会话可以可靠继承。
5. 落盘后要读回校验：代码列表、`stage`、`pool_type`、`source_file`、关键点位字段、20cm 过滤，以及是否误包含已剔除票。

## 监控池替换与验证

更新监控池文件后，必须验证脚本实际读取的是新池，而不是旧硬编码池：

0. **先确认运行目录**：屠龙运行时当前在本 skill 根目录内（`~/.hermes/skills/finance/stock-strategy-assistant`），不要沿用历史独立仓库路径；若聊天或旧日志出现 `/Documents/ai-project/a-share-stock-assistant` 等旧路径，必须先检查该目录是否存在，并以 skill 根目录的数据为准。
1. `cronjob(action='list')`：确认当前启用任务、脚本名、workdir、最近运行状态、投递错误；
2. 读取监控脚本实际 watchlist 来源，例如 `WATCHLIST_CSV_PATH` / `load_watchlist()`；当前 active 文件应为 `data/watchlists/tulong_active_watchlist.csv`；
3. 读取实际生效 CSV，并与 `MMDDD3_watch_*_HHMMSS.csv`、`HOLD_position_*_HHMMSS.csv` 等源文件分开列；
4. 检查 active CSV 的 `stage`、`pool_type`、`source_file` 字段，确认每只票来自 `D3观察区(watch)` 或 `HOLD持仓(position)`；
5. 按代码前缀过滤并标注 20cm；用户无创/科权限时过滤 `300/301/688/689`；
6. 替换时保留 `industry`、`zone_low`、`zone_high`、`score`、`rank`、`note`；
7. 替换后重置或隔离状态文件：`sent`、`last_prices`、`pending_snapshot`、`watchlist_source`；
8. 强制运行一次验证 `load_watchlist()`、`entry_zone()`、快照标题、事件 JSONL/快照 CSV 最新行。

### D3 watch 与 HOLD 的查询纪律

当用户问“今天监控池有哪些 / 是否能正常监控 / 先忽略 HOLD”时，必须把 **D3 watch** 与 **HOLD position** 分开回答：

- 只问 `MMDDD3监控池` 且用户明确“先忽略 HOLD”时，只读取最新 `MMDDD3_watch_*_YYYYMMDD_HHMMSS.csv` 与 active 中 `stage=MMDDD3,pool_type=watch` 的行，不要混入 `HOLD`。
- 只有在存在**当天或明确滚动续期后的** `HOLD_position_*_YYYYMMDD_HHMMSS.csv`，并且 `position_status=open` 时，才把 HOLD 作为当前应监控持仓；不要把几天前的手工/rollover 文件直接推断为今日 HOLD。
- 若 active 池混入 `position_status=closed` 的 HOLD 行，应明确标为污染项并清理；清理 active 后必须同步修正 `tulong_d3_monitor_state.json` 里的 `watchlist_source`、`stages`、`pool_types`，避免状态仍显示包含 HOLD。
- 回答“能否正常监控”至少核对三层：cron 任务启用且最近 `last_status=ok`，active CSV 已是今日 `MMDDD3`，state 的 `watch_date/watchlist_source/stages/pool_types` 与 active 一致。三者不一致时，不要直接说正常。

### 告警/快照展示不得硬编码日期+D几

如果用户指出“为什么还是 0527D3 / 日期不对 / 持仓显示成观察区”，优先检查展示模板，而不只检查 active CSV。实际监控池可能已经正确，但脚本里的标题、单股提醒、快照头仍残留硬编码 `0527D3`、`D3主板` 或旧池名。

固定处理步骤：

1. 先读 `data/watchlists/tulong_active_watchlist.csv`，确认每行真实 `stage`、`pool_type`、`source_file`；持仓票如华能蒙电这类应显示为 `HOLD / position`，而不是沿用买入当天的 D3 标签。
2. 在 `scripts/tulong/runtime/watchdog.py` 或对应脚本中搜索旧标签（如 `0527D3`、`D3主板`、旧四股标题），把单股提醒和快照标题改为从 `item['stage']` 动态读取；缺失时才 fallback 到 `f'{now:%m%d}D3'`。
3. 混合 D3 观察 / HOLD 持仓池的快照标题应汇总实际 stages，例如 `0528D3/HOLD主板11股盘中快照`；单股行则用该股票自身 stage。
4. 修复后必须验证：搜索脚本无旧硬编码残留，并用 `FORCE_RUN=1` 或脚本级函数生成一次告警/快照，确认用户可见文本与 active CSV 一致。
5. 回答用户时明确区分“数据源/监控池正确”与“展示模板残留错误”，不要把展示问题误报成切池失败。

