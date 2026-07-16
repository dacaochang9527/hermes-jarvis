# 飞书文档盘点与本机导出

## 适用场景

当用户问“你创建的飞书文档有多少”“能否全部下载到本机”“把历史飞书在线文档备份下来”时，优先使用这个流程。

目标不是重新生成报告，而是从 Hermes 本机历史记录中找出曾创建/发送过的飞书 `docx` 链接，校验仍可访问的文档，并导出为本机 Markdown/纯文本备份。

## 推荐流程

1. 从 `~/.hermes/state.db` 的 `messages` + `sessions` 表检索历史消息与工具调用中的 `/docx/` 链接。
2. 用正则抽取唯一文档 token：
   - URL 形态：`https://<tenant>.feishu.cn/docx/<doc_token>`
   - `doc_token` 通常是 20+ 位字母数字串。
3. 读取 `~/.hermes/.env` 中的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET`，调用：
   - `POST /open-apis/auth/v3/tenant_access_token/internal` 获取 tenant access token。
4. 对每个 token 调用元数据接口：
   - `POST /open-apis/drive/v1/metas/batch_query?user_id_type=open_id`
   - payload: `{"request_docs":[{"doc_token": token, "doc_type":"docx"}], "with_url": true}`
   - 用返回的 title/url 作为 manifest 信息。
5. 对每个 token 调用正文接口导出：
   - `GET /open-apis/docx/v1/documents/{token}/raw_content`
   - 将 `data.content` 保存为 `.md` 文件。
6. 在导出目录写入：
   - `manifest.json`
   - `manifest.csv`
   - 每个可读取文档一个 `{安全标题}__{doc_token}.md`。
7. 汇总给用户：发现多少唯一 token、元数据可访问多少、成功下载多少、失败多少、失败原因与导出目录。

## 输出目录建议

使用时间戳目录，避免覆盖旧备份：

```text
~/.hermes/exports/feishu_docs_YYYYMMDD_HHMMSS/
```

## 关键注意事项

- `metas/batch_query` 能成功不代表 `raw_content` 一定能读取；被删除的文档可能元数据仍可返回，但正文接口返回 `1770003 resource deleted`。
- 不要把历史消息中同一个文档的多次出现当作多个文档；按 `doc_token` 去重。
- 历史会话中可能包含不同租户域名或旧域名。最终以元数据接口返回的 URL 为准；没有返回 URL 时再回退到历史 URL。
- 这个流程导出的是 `raw_content` 文本/Markdown 备份，不是 Word/PDF 二进制。如果用户明确要 `.docx`/PDF，需要再走 Drive 导出任务接口。
- 不要把 `resource deleted` 固化为“飞书下载不可用”；它只表示该 token 对应资源已删除或正文不可读。

## 最小 Python 骨架

```python
import csv, json, os, pathlib, re, sqlite3, urllib.request
from datetime import datetime

home = pathlib.Path.home() / ".hermes"
out = home / "exports" / f"feishu_docs_{datetime.now():%Y%m%d_%H%M%S}"
out.mkdir(parents=True, exist_ok=True)

# 1) load env: FEISHU_APP_ID / FEISHU_APP_SECRET
# 2) get tenant token
# 3) select messages containing '/docx/' from state.db
# 4) regex: r'https://([A-Za-z0-9.-]+\.feishu\.cn)/docx/([A-Za-z0-9]{20,})'
# 5) batch_query metadata and GET raw_content per token
# 6) write .md files + manifest.json/csv
```
