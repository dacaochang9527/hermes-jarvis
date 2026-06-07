# 屠龙买卖截图入账流程

当用户发送买卖/持仓截图要求“整理到交易文档”时，按本文件流程执行。事实源统一为 `data/trades/tulong_trades.csv`。

## 识别

### 优先路径：macOS Vision OCR

系统自带 Vision 框架对中文数字混合截图效果优于仅英文 tesseract。Skill 内置脚本：

```bash
swift scripts/vision_ocr.swift <image_path>
```

如果历史会话已把脚本临时落到 `/tmp/vision_ocr.swift`，也可复用；但新会话优先使用 skill 内置脚本，避免 `/tmp` 被清理。

### 备用路径：tesseract

```bash
brew install tesseract imagemagick
# tesseract-lang 下载不稳定时，先不装语言包，用英文 eng + 数字 snum 也能读大部分代码/价格/金额。
```

### 兜底：用户补文字

如果截图确实不可读（模糊/截断/关键字段缺失），明确告知用户并请求补发文字版，不瞎填。

## 费用估算

截图未显示费用时，绝不留空。按标准佣金+印花税+过户费估算：

```text
买入：fee = 5.00 + amount * 0.00001
卖出：fee = 5.00 + amount * 0.0005 + amount * 0.00001
```

全程四舍五入到 2 位小数。`net_amount` 买入为 `-(amount+fee)`，卖出为 `amount-fee`。note 末尾写 `费用按标准估算`。

## 写入 CSV

前置检查：

1. 读取 CSV 全量行，按 `(trade_date, action, code, quantity, price, amount, note)` 去重，避免同一条重复追加。
2. `position_ref`：卖出填旧仓 D 标签（如 `0603D3`）；买入填当前 D 标签。
3. `d3_watch`：原标的是否属于屠龙 D3 watch 池；非 D3 监控/策略外标的填 `no`。
4. `session_label`：当前 D 标签，如 `0604D3`。

## T 操作口径

日内先买后卖时：

- 买入行 `action=buy`，`position_ref=当前D标签`，note 写 `T操作买入`。
- 卖出行 `action=sell`，`position_ref=旧仓来源D标签`，note 写 `T操作卖出旧仓`。

不要混用同一个 `position_ref`。

## 写入后验证

写入后运行买入-卖出数量汇总，核对所有代码的 open HOLD 是否与用户预期一致。如出现负持仓或意外清仓，立即提示用户复核。

## 示例

截图 OCR 识别到：

```text
600596 新安股份
卖出 100股 14.150 金额1415.00 10:23:32
卖出 200股 14.160 金额2832.00 10:23:18
```

写入：

```csv
2026-06-04,0604D3,sell,600596,新安股份,100,14.150,1415.00,5.72,1409.28,0603D3,0604D3卖出｜0603D3买入成本13.540｜第1笔｜成交时间10:23:32｜费用按标准估算｜毛利61.00,yes
2026-06-04,0604D3,sell,600596,新安股份,200,14.160,2832.00,6.44,2825.56,0603D3,0604D3卖出｜0603D3买入成本13.540｜第2笔｜全部清仓｜成交时间10:23:18｜费用按标准估算｜毛利124.00,yes
```
