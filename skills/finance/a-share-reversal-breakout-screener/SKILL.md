---
name: a-share-reversal-breakout-screener
description: "独立筛选和复核 A 股长期下跌后低位企稳、均线拐头并接近或完成平台突破的反转启动形态，并用行业相对强度、MA60/120、基本面和公告风险做二次精选。用户提到超跌反转、低位筑底、均线拐头、平台突破、类似赤天化/金牛化工的走势、上传日 K 截图询问是否符合、要求全市场筛选、候选太多需要二次过滤，或要打开四组候选的本地交互式日 K 看板时，应使用本 skill。涨停、市值和绝对股价不作为核心形态硬门槛，而是记录为状态或风格标签。"
license: MIT
compatibility: "需要 Python 3.9+、requests、curl，以及可只读访问新浪、腾讯或东方财富公开行情接口。"
metadata:
  hermes:
    tags: [a-share, stocks, reversal, breakout, screening, technical-analysis]
    category: finance
---

# A股超跌反转突破筛选

## 独立边界

本 skill 是“长期下跌—低位企稳—均线拐头—平台突破”形态的独立事实源，不属于屠龙、尾盘隔夜、打板或其他股票策略，也不修改、引用或共享它们的规则、脚本、观察池和绩效口径。

目标是生成可复核的观察信号，不输出确定性买卖指令。筛选结果不等于投资建议；每只候选都要同时展示过热、乖离、量价、上影和基本面提示。

## 使用路由

遇到以下任务，先完整读取：

```text
references/rules.md
```

- 判断用户上传的日 K 截图是否符合；
- 比较多只股票与该形态的相似度；
- 调整筛选阈值、评分或分层；
- 运行沪深主板全市场筛选；
- 解释候选为什么入选、为什么只进入过热层或观察层。
- 启动或维护四组候选的本地交互式日 K 看板。

## 核心原则

1. 把“技术形态”与“股票风格”分开。市值、股价和换手的绝对值用于风格标签或同类比较，不替代核心形态。
2. 涨停不是必要条件，也不参与核心评分；涨停只记录为当日状态，并提高对次日波动和接力风险的关注。
3. 完整多头排列不是唯一入口。`收盘价 > MA5`、`MA5 > MA10 且 MA5 > MA20`、中期均线开始上行，可识别金牛化工一类尚未完成 `MA10 > MA20` 的早期过渡结构。
4. RSI 高不是趋势失效，但表示发现位置偏晚。RSI6、距 MA20 乖离、近5日涨幅任一过高时，候选进入“过热”层，不与早期层混排。
5. 量能图缺失时明确写“无法确认”，不根据涨幅或换手臆测放量倍数。
6. 截图判定只使用图中可见数据；全市场筛选使用前复权日线，并注明数据日期和失败数量。

## 全市场筛选

脚本完全位于本 skill 内：

```bash
python3 scripts/screen.py --top 20
```

默认行为：

- 沪深主板代码范围 `000/001/002/003/600/601/603/605`；
- 排除 ST、退市风险、无有效价格和当日成交额不足2亿元的股票；
- 从新浪行情中心读取快照、从腾讯读取前复权日线，东方财富作为日线兜底；
- 从沪深300计算20/60日相对强度，从流动性股票样本计算行业强度和行业宽度；
- 对技术候选补充东方财富最近一期财务指标和近60日公告风险，失败时保留候选并标记数据缺失；
- 核心形态不限制是否涨停，不硬限制价格和市值；
- 输出 `早期 / 确认 / 观察 / 过热` 四层 CSV 与 Markdown；
- 报告默认写入本 skill 的 `reports/`，日线缓存写入 `cache/`。

指定股票复核：

```bash
python3 scripts/screen.py \
  --symbols 600227,600722,600028,600938,600536 \
  --top 50
```

常用参数：

```text
--min-amount 200000000    快照成交额下限，默认2亿元
--min-score 65            输出最低综合分，默认65
--workers 16              并发读取日线的线程数
--scan-limit N            只扫描预筛后的前N只，用于冒烟验证
--no-cache                不复用当日缓存
--skip-enrichment          跳过财务和公告补充，只用于快速冒烟
--metadata-workers 12      财务与公告补充并发数
--metadata-dir PATH        指定财务与公告缓存目录
--output-dir PATH         指定报告目录
```

## 输出纪律

先报告数据完整性，再给分层结果。每只至少显示：

- 代码、名称、数据日期、收盘价、涨跌幅；
- 最大回撤、前20日平台振幅、突破比；
- MA5/MA10/MA20及其方向、趋势结构；
- RSI6、距MA20乖离、近5日涨幅、热度；
- 量能倍数、换手率、相对换手、成交额；
- 市值风格、高弹性标签、是否涨停；
- 行业、行业强度分位、行业宽度、RS20/RS60和超行业收益；
- MA60/MA120方向、60日突破比、平台缩量和量价持续性；
- 最近一期财务状态、近60日公告风险、二次评分和核心/重点/一般层级；
- 入选理由、降级原因和后续确认点。

优先展示“早期”和“确认”，把“过热”单独列出。没有早期候选时应明确说明，不从过热层强行补位。

## 本地交互式日K看板

启动命令：

    python3 scripts/server.py --host 127.0.0.1 --port 8765 --open

看板自动读取 reports/ 中最新 CSV，并从 cache/ 按需加载日线。它只提供本机只读 GET 接口，不提供修改候选、触发交易或执行筛选的写接口。

必须保留以下交互能力：

- “早期 / 确认 / 观察 / 过热”四组标签页，并允许查看全部；
- 展示每组所有股票，不把前25只等报告展示上限误当成完整结果；
- 支持代码/名称搜索、排序和高弹性过滤；
- 支持组合筛选 heat、trend、style、涨停状态、风险状态、最低综合分、RSI上限、MA20乖离上限、突破比下限和量能倍数下限；
- 提供“技术精选”和“二次精选”快速方案；二次精选默认打开，但四个原始分组和全部候选仍可随时查看；
- 支持行业、二次层级、长周期结构、量价结构、基本面状态、公告风险、行业强度、RS20、超行业收益、60日突破和MA60斜率组合筛选；
- 清晰显示已启用条件数量和条件摘要，并提供一键重置，避免隐藏条件造成误判；
- 每只股票显示可交互的日 K、成交量和 MA5/MA10/MA20/MA60/MA120；
- 鼠标移动到日柱时吸附到该交易日，显示日期、开高低收、涨跌幅、振幅、成交量和三条均线；
- 绘制横纵十字光标；点击小图打开大图；
- 大图支持滚轮缩放、拖动平移和双击复位；
- 新筛选 CSV 生成后，刷新网页自动读取最新报告。

日 K 必须是浏览器中的交互图形，不能预渲染成 PNG/JPG 等静态图片。

## cpaus 部署

cpaus 上的标准部署路径：

    /root/.hermes/skills/finance/a-share-reversal-breakout-screener

systemd 模板位于 `deploy/a-share-reversal-dashboard.service`。远端应用服务固定监听 `127.0.0.1:8765`，不把 Python 服务端口直接暴露到公网；本机通过 SSH 隧道映射到 `127.0.0.1:18765`。

本机 ~/.bashrc 中的 cpaus 别名负责建立隧道。连接后打开：

    http://127.0.0.1:18765/

常用管理命令：

    systemctl status a-share-reversal-dashboard --no-pager
    systemctl restart a-share-reversal-dashboard
    journalctl -u a-share-reversal-dashboard -n 100 --no-pager

部署更新时同步 SKILL.md、references/、scripts/、web/、deploy/、最新 reports/ 和当日日线 cache/；不要把其他股票 skill 或观察池复制进来。更新 unit 后执行 daemon-reload，更新普通代码和数据后只需重启服务。

### 公网入口

需要让朋友访问时，用 Caddy 反向代理本机回环地址上的应用服务，并同时启用自动 HTTPS 与 Basic Auth。参考模板位于 `deploy/Caddyfile.cpaus.example`，当前标准域名为：

    https://a-share.192-255-128-222.sslip.io/

部署要点：

- 只开放 Caddy 使用的 80/443，继续让应用服务监听 `127.0.0.1:8765`；
- 使用 `caddy hash-password` 生成 bcrypt 哈希，把模板中的 `<bcrypt-hash>` 替换后再部署；
- 不把访问明文密码写入 skill、仓库、systemd unit 或 Caddyfile；
- 修改 Caddyfile 后先运行 `caddy validate --config /etc/caddy/Caddyfile`，验证通过后再 reload；
- 公网验收至少检查 HTTP 跳转 HTTPS、未登录返回 401、登录后 `/healthz` 正常，以及页面筛选和 K 线悬停可用。

常用管理命令：

    systemctl status caddy --no-pager
    journalctl -u caddy -n 100 --no-pager
    caddy validate --config /etc/caddy/Caddyfile

## 维护与验证

- 当前规则只维护在 `references/rules.md`；脚本阈值必须与该文件同步。
- 确定性计算逻辑维护在 `scripts/screen.py`，不要把公式散落到其他股票 skill。
- 修改规则或计算逻辑后，运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/screen.py --symbols 600227,600722,600028,600938,600536 --top 50
python3 scripts/server.py --port 8765
```

- 任一公开行情接口失败属于当次数据状态；脚本应尝试已配置的只读兜底源并报告失败数量，不把临时网络问题写成长期规则。
