# 期货报告发布到飞书文档

用于期货复盘/操作计划需要同时落盘本地 Markdown、生成飞书在线文档并把链接发到群里的场景。

## 目标闭环

1. 先把规范版报告保存到 `~/.hermes/skills/finance/futures-trading-assistant/reports/`。
2. 用飞书 bot 凭证创建 docx 文档，并写入报告内容。
3. 生成最终文档 URL 后，回写到本地 Markdown 头部元信息。
4. 用 SDK 或 API 读取 raw content 验证在线文档内容非空。
5. 将最终 URL 发到期货飞书群。

## 本地报告格式

Markdown 顶部建议保留：

```markdown
# PVC2609 2026-06-22 夜盘操作计划

> 生成时间：2026-06-22 日盘收盘后  
> 飞书在线文档：https://...  
> 标的：PVC2609 期货合约  
> 数据源：...
```

如果创建飞书文档后才拿到 URL，应 patch 回 `> 生成时间` 后一行，避免本地源文件和线上版本脱节。

## 首选脚本入口

优先使用 skill 内固定脚本发布，不要在会话中临场重写 API 流程：

```bash
/Users/fenomenoronaldo/.hermes/hermes-agent/venv/bin/python \
  /Users/fenomenoronaldo/.hermes/skills/finance/futures-trading-assistant/publish_feishu_markdown_doc.py \
  /Users/fenomenoronaldo/.hermes/skills/finance/futures-trading-assistant/reports/pvc2609_20260622_night_plan.md
```

脚本会自动完成：读取本地 Markdown、创建 bot-owned docx、调用官方 Markdown converter、用 descendant API 插入层级 blocks、设置公司内链接可读、验证 metadata URL，并回写本地 Markdown 的 `> 飞书在线文档：...` 行。默认不发群；群发送必须单独执行。

可选参数：

- `--title "..."`：覆盖在线文档标题。
- `--title-suffix "（格式验证版）"`：在 Markdown 一级标题后追加后缀。
- `--no-patch`：只生成在线文档，不回写本地 Markdown 链接。

## Python SDK/Raw API 创建流程

使用 Hermes venv，不要依赖系统 Python：

```bash
/Users/fenomenoronaldo/.hermes/hermes-agent/venv/bin/python publish_feishu_markdown_doc.py <report.md>
```

关键步骤：

```python
from dotenv import load_dotenv
import lark_oapi as lark
from lark_oapi.api.docx.v1 import *

load_dotenv(os.path.expanduser('~/.hermes/.env'))
client = (
    lark.Client.builder()
    .app_id(os.getenv('FEISHU_APP_ID'))
    .app_secret(os.getenv('FEISHU_APP_SECRET'))
    .domain('https://open.feishu.cn')
    .log_level(lark.LogLevel.ERROR)
    .build()
)

resp = client.docx.v1.document.create(
    CreateDocumentRequest.builder()
    .request_body(CreateDocumentRequestBody.builder().title(title).build())
    .build()
)
doc_id = resp.data.document.document_id
```

写入正文必须使用飞书官方 Markdown/HTML 内容转换接口，而不是手写 `heading/text/bullet` blocks。SDK 中对应模型为 `ConvertDocumentRequest` / `ConvertDocumentRequestBody`，字段为 `content` 与 `content_type`。转换后的结果必须按 converter 返回的层级结构写入 docx，才能保留 Markdown 标题、列表、表格等版式。

关键点：converter 返回的不是可直接扁平插入的 children 列表；对于包含表格/列表等层级结构的 Markdown，要用 descendant API 插入：

1. 调用 `client.docx.v1.document.convert(...)`，请求体为 `{"content_type":"markdown","content": markdown_text}`。
2. 使用 `convert_resp.data.first_level_block_ids` 作为顶层 `children_id`。
3. 使用 `convert_resp.data.blocks` 作为 `descendants`。
4. 插入前递归移除 converter 返回的表格 `merge_info` 字段，因为它是只读字段，直接传回 descendant API 可能导致校验失败。
5. 调用 `CreateDocumentBlockDescendantRequest`，路径块使用根 block：`document_id=doc_id`、`block_id=doc_id`、`document_revision_id=-1`。

伪代码：

```python
convert_resp = client.docx.v1.document.convert(
    ConvertDocumentRequest.builder()
    .request_body(
        ConvertDocumentRequestBody.builder()
        .content(markdown_text)
        .content_type("markdown")
        .build()
    )
    .build()
)
assert convert_resp.code == 0
children_id = convert_resp.data.first_level_block_ids
descendants = remove_readonly_merge_info(convert_resp.data.blocks)

insert_resp = client.docx.v1.document_block_descendant.create(
    CreateDocumentBlockDescendantRequest.builder()
    .document_id(doc_id)
    .block_id(doc_id)
    .document_revision_id(-1)
    .request_body(
        CreateDocumentBlockDescendantRequestBody.builder()
        .children_id(children_id)
        .descendants(descendants)
        .build()
    )
    .build()
)
assert insert_resp.code == 0
```

不要把 converter 输出的 `blocks` 直接传给 `document_block_children.create(...children=...)`。这个旧写法只适合手工构造的简单扁平 blocks；遇到 Markdown 表格/嵌套列表会丢结构或报错。

只有在官方 converter 不可用且用户接受“临时可读版”时，才允许降级为手写基础 blocks；降级版本必须明确标注表格会变成纯文本，不得称为格式已解决。

## 验证

创建后立即读取 raw content：

```python
resp = client.docx.v1.document.raw_content(
    RawContentDocumentRequest.builder().document_id(doc_id).build()
)
assert resp.code == 0
assert len(resp.data.content or '') > 0
```

验证通过后再发送群消息。

## 群发送

当前期货群目标通常是：

`feishu:oc_3b94cfb91274b70374954d7b12f12432`

发送内容保持简短：标题、链接、核心观察点即可。不要把整篇报告粘到群里。

## 注意事项

- `FEISHU_DOMAIN` 可能是 Hermes 平台标识而不是 OpenAPI URL；直接使用 SDK 时显式设置 `.domain('https://open.feishu.cn')`。
- 内置 `feishu_doc_read` 可能只在 Feishu 评论上下文有 client；非评论上下文验证在线文档时，优先用同一套 SDK 读取 raw content。
- 不要把 app secret、tenant token 或完整响应中的敏感字段写入日志/报告。
- 如果未来实现官方 Markdown-to-docx block converter，优先使用转换器保留表格和列表版式；在此之前，纯文本 block 的目标是稳定发布和可读。