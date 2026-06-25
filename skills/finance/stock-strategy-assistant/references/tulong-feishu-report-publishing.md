# 屠龙股票报告发布到飞书文档

用于 D3 观察池、复盘、题材概率评估等股票报告需要同时落盘本地 Markdown、生成飞书在线文档并把链接发给用户的场景。

## 适用场景

当用户要求：

- “按表格形式落盘一份 md 文档”；
- “生成飞书文档，发链接给我”；
- “参考期货那边的方式”；
- D3/二进三/强势观察池分析报告需要在线分享。

## 标准闭环

1. 先在股票 skill 内保存规范 Markdown，例如：

```text
/Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant/reports/daily/<report_name>.md
```

2. Markdown 顶部必须包含 `> 生成时间：...`，并预留或允许脚本回写：

```markdown
# 0625D3 观察池/强势/二进三题材热度与上涨概率评估

> 生成时间：2026-06-25 02:16:26 CST  
> 飞书在线文档：待生成  
> 标的范围：...
> 数据来源：...
> 风险声明：...
```

3. 使用期货 skill 中已验证的固定发布脚本，不要临时重写飞书 OpenAPI 流程：

```bash
/Users/fenomenoronaldo/.hermes/hermes-agent/venv/bin/python \
  /Users/fenomenoronaldo/.hermes/skills/finance/futures-trading-assistant/publish_feishu_markdown_doc.py \
  /Users/fenomenoronaldo/.hermes/skills/finance/stock-strategy-assistant/reports/daily/<report_name>.md \
  --title "<飞书文档标题>"
```

4. 发布脚本应完成：创建 bot-owned docx、官方 Markdown converter 转 block、descendant API 插入、设置 tenant_readable、回写本地 Markdown 的 `> 飞书在线文档：...`。

5. 发布后必须验证两件事：

- 本地 Markdown 头部已回写最终飞书链接；
- 在线 docx raw content 非空，避免空文档或只创建标题。

6. 最终回复用户时只给飞书链接、本地文件路径和验证结果摘要；不要把整篇报告复制到聊天里。

## 报告内容纪律

- 股票报告里的概率必须写成“条件概率/主观分层”，不能写成确定性收益承诺。
- 对 D3 active、radar、二进三/强势接力要分层说明，不能把 radar 强势票直接混成 active 可参与池。
- 题材/产业投资逻辑只作为热度和资金叙事参考，不替代买点区、失效线、量能和盘中承接确认。
- 表格至少包含：分类、代码、名称、行业/概念线索、D2涨幅、观察价/买点区/失效、预估上行幅度、上涨概率、分析原因。

## 常见坑

- 如果 Markdown 顶部没有 `> 生成时间：...`，旧发布脚本可能无法自动插入飞书链接；应先补齐元信息区或发布后手动 patch。
- 不要把期货报告目录作为股票报告落盘目录；脚本可复用，但股票报告源文件仍放在 stock-strategy-assistant 的 `reports/` 下。
- 不要跳过 raw content 验证；飞书文档创建成功不等于正文写入成功。
