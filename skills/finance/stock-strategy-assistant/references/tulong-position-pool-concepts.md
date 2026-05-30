# 屠龙 D3 观察区与持仓概念模型

> 验证期调整（2026-05-30）：屠龙战法处于验证阶段，**买入后的 D4/D5 决策策略（卖出、加仓、止盈、止损、留仓等）已暂时移除，不再预设**，以免约束后续策略制定。
> 本文保留的内容仅限**事实层**：观察 vs 持仓的身份区分、T+1 可卖性、active watchlist 字段、持仓换日搬运。凡“D4 持有区/D5 应如何卖、如何加、如何止损止盈”的动作规则均已中性化为占位，待数据验证后另定。

## 状态

讨论稿沉淀，适用于后续 A 股屠龙选股监控、持仓事实管理、active watchlist 字段设计。后续会话若继续修订本概念，应更新本文件，并在 `tulong-d3-d4-monitoring.md` 保持摘要同步。

## 核心定稿

### 1. D3 统一使用“观察”，不再使用“候选”

用户确认：候选和观察含义接近，统一为“观察”。后续用户可见概念不再出现“候选区”。

推荐命名：

```text
0528D3观察区
```

工程字段：

```text
pool_type = watch
```

不再使用：

```text
candidate
候选区
```

如果历史文件名或旧文本里出现 `candidate`，只视为旧遗留/生成原因，不作为新概念继续使用。

### 2. D3 需要分区

D3 买入动作会改变提醒目标，因此 D3 也需要分区：

```text
D3观察区：未买入，寻找买点/回收/失效
D3持仓区：已买入，管理当天持仓风险
```

这不是“候选 vs 买入”，而是：

```text
观察 vs 持仓
```

### 3. 买入后只保留持仓事实，不预设 D4/D5 策略

买入后不再设未买入观察区；持仓的退出/加仓策略（原 D4 持有区/D5 强制退出口径）验证期已移除，不再预设。未买入的 D3 观察票次日不转为持仓。

## 持仓的事实层差异：可卖性（验证期口径）

唯一保留的事实差异是 **T+1 可卖性**，由 `entry_date` 客观决定，与具体策略无关：

```text
买入当天：T+1 限制下不能卖（sellable_quantity=0）
次日及以后：已解禁可卖（sellable_quantity=quantity）
```

### 对比表

| 维度 | 买入当天持仓 | 次日及以后持仓 |
|---|---|---|
| pool_type | position | position |
| 能否卖（事实） | 否（T+1 锁定） | 是 |

> 验证期移除：原“D3持仓区/D4持有区提醒指标、动作语言（止盈/止损/减仓/加仓/留仓/隔夜风险等）”属于尚未验证的决策策略，已整体移除。当前仅呈现成本、现价、相对盈亏、距失效位、可卖数量等事实指标，判断权交由人工与复盘。

## 工程字段建议

`stage` 表示阶段：

```text
0527D3
0528D4
```

`pool_type` 表示身份：

```text
watch      # D3观察区，未买入；D4 不使用 watch
position   # 持仓区，已买入
```

可选字段：

```text
entry_date
entry_stage
entry_price
quantity
sellable_quantity   # D3当天买入为0，D4起通常等于可卖持仓
cost_amount
position_status     # open / reduced / closed
source_file
```

## 0527D3 买入后的状态示例

0527 当天买入后：

```text
600863 华能蒙电
stage = 0527D3
pool_type = position
entry_price = 6.170
quantity = 600
sellable_quantity = 0
```

```text
603303 得邦照明
stage = 0527D3
pool_type = position
entry_price = 25.440
quantity = 200
sellable_quantity = 0
```

它们仍然是 `0527D3`，但不再属于 `0527D3观察区`，而是进入 `0527D3持仓区`。

次日 0528（已解禁可卖）：

```text
pool_type = position
sellable_quantity = quantity
```

可卖性从锁定变为解禁（事实）。原先此处会进入“0528D4持有区”并套用固定的卖出/加仓策略，验证期已移除该预设；持仓的退出/加仓动作待验证后另定。`stage` 仅作入场溯源（如 `0527D3`），不再每日滚动改写为 D4/D5。

## 待继续讨论

1. 真实持仓是否单独维护一个 `positions` 文件，还是直接写入 active watchlist？当前倾向：active watchlist 用于提醒，positions 用于持仓事实。
2. D3观察区、D3持仓区和 D4持有区是否都进入同一个 active watchlist，由 `pool_type` 区分？当前倾向：是。
3. D3持仓区的“可加仓区”是否沿用 D3买点区，还是需要更严格的二次确认条件？待定。
