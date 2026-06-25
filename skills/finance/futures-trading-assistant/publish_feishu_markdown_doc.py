#!/usr/bin/env python3
"""Publish a local Markdown report as a Feishu docx document.

Creates a bot-owned Feishu online document using the official Markdown-to-docx
block converter, inserts converted blocks via the descendant API, sets company
link readability, verifies metadata, and patches the local Markdown report with
the final URL.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

FEISHU_BASE_URL = "https://open.feishu.cn"
DEFAULT_ENV_PATH = Path.home() / ".hermes" / ".env"


class PublishError(RuntimeError):
    pass


def load_env(path: Path = DEFAULT_ENV_PATH) -> None:
    if not path.exists():
        raise PublishError(f"Env file not found: {path}")
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_request(method: str, path: str, token: str | None = None, **kwargs: Any) -> dict[str, Any]:
    headers = kwargs.pop("headers", {})
    if token:
        headers = {**headers, "Authorization": f"Bearer {token}"}
    if "json" in kwargs:
        headers = {"Content-Type": "application/json; charset=utf-8", **headers}
    response = requests.request(
        method,
        f"{FEISHU_BASE_URL}{path}",
        headers=headers,
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PublishError(f"{method} {path} returned non-JSON HTTP {response.status_code}: {response.text[:300]}") from exc
    if response.status_code >= 400 or payload.get("code") != 0:
        raise PublishError(f"{method} {path} failed HTTP {response.status_code}: {json.dumps(payload, ensure_ascii=False)[:1000]}")
    return payload


def get_tenant_token() -> str:
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise PublishError("Missing FEISHU_APP_ID or FEISHU_APP_SECRET in environment")
    payload = api_request(
        "POST",
        "/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    token = payload.get("tenant_access_token")
    if not token:
        raise PublishError("Feishu token response did not contain tenant_access_token")
    return token


def strip_readonly_fields(value: Any) -> Any:
    if isinstance(value, dict):
        value.pop("merge_info", None)
        for child in value.values():
            strip_readonly_fields(child)
    elif isinstance(value, list):
        for child in value:
            strip_readonly_fields(child)
    return value


def extract_title(markdown: str, fallback: str, suffix: str | None) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
    else:
        title = fallback
    if suffix:
        title = f"{title}{suffix}"
    return title


def patch_markdown_link(markdown_path: Path, url: str) -> None:
    text = markdown_path.read_text()
    line = f"> 飞书在线文档：{url}  "
    if re.search(r"^> 飞书在线文档：.*$", text, flags=re.MULTILINE):
        text = re.sub(r"^> 飞书在线文档：.*$", line, text, count=1, flags=re.MULTILINE)
    else:
        text = re.sub(
            r"(^> 生成时间：.*$)",
            rf"\1\n{line}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    markdown_path.write_text(text)


def publish(markdown_path: Path, title: str | None, title_suffix: str | None, no_patch: bool) -> dict[str, Any]:
    markdown_path = markdown_path.expanduser().resolve()
    if not markdown_path.exists():
        raise PublishError(f"Markdown file not found: {markdown_path}")
    markdown = markdown_path.read_text()
    token = get_tenant_token()
    final_title = title or extract_title(markdown, markdown_path.stem, title_suffix)

    created = api_request("POST", "/open-apis/docx/v1/documents", token, json={"title": final_title})
    document_id = created["data"]["document"]["document_id"]

    converted = api_request(
        "POST",
        "/open-apis/docx/v1/documents/blocks/convert",
        token,
        json={"content_type": "markdown", "content": markdown},
    )
    convert_data = converted["data"]
    first_level_ids = convert_data.get("first_level_block_ids") or []
    blocks = strip_readonly_fields(convert_data.get("blocks") or [])
    if not first_level_ids or not blocks:
        raise PublishError("Converter returned empty first_level_block_ids or blocks")

    # Chunk descendants to avoid "max len is 1000" Feishu API limit
    CHUNK_SIZE = 800
    if len(blocks) <= CHUNK_SIZE:
        api_request(
            "POST",
            f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1",
            token,
            json={"children_id": first_level_ids, "descendants": blocks},
            timeout=60,
        )
    else:
        # First batch: include children_id to set document structure
        api_request(
            "POST",
            f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1",
            token,
            json={"children_id": first_level_ids, "descendants": blocks[:CHUNK_SIZE]},
            timeout=60,
        )
        # Remaining batches: use empty children_id (top-level already established)
        for i in range(CHUNK_SIZE, len(blocks), CHUNK_SIZE):
            chunk = blocks[i:i + CHUNK_SIZE]
            api_request(
                "POST",
                f"/open-apis/docx/v1/documents/{document_id}/blocks/{document_id}/descendant?document_revision_id=-1",
                token,
                json={"children_id": [], "descendants": chunk},
                timeout=60,
            )

    permission = api_request(
        "PATCH",
        f"/open-apis/drive/v1/permissions/{document_id}/public?type=docx",
        token,
        json={"external_access": False, "link_share_entity": "tenant_readable"},
    )

    metadata = api_request(
        "POST",
        "/open-apis/drive/v1/metas/batch_query?user_id_type=open_id",
        token,
        json={"request_docs": [{"doc_token": document_id, "doc_type": "docx"}], "with_url": True},
    )
    meta = metadata["data"]["metas"][0]
    url = meta.get("url")
    if not url:
        raise PublishError("Metadata verification returned no URL")

    if not no_patch:
        patch_markdown_link(markdown_path, url)

    return {
        "document_id": document_id,
        "url": url,
        "title": meta.get("title") or final_title,
        "markdown_path": str(markdown_path),
        "patched_local_report": not no_patch,
        "top_level_blocks": len(first_level_ids),
        "total_blocks": len(blocks),
        "permission": permission.get("data", {}).get("permission_public", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish a Markdown report as a Feishu docx document.")
    parser.add_argument("markdown_path", help="Path to the local Markdown report")
    parser.add_argument("--title", help="Override Feishu document title")
    parser.add_argument("--title-suffix", default="", help="Append suffix to the first Markdown heading when --title is omitted")
    parser.add_argument("--no-patch", action="store_true", help="Do not patch the local Markdown report with the generated URL")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="Path to Hermes .env file")
    args = parser.parse_args()

    try:
        load_env(Path(args.env).expanduser())
        result = publish(Path(args.markdown_path), args.title, args.title_suffix, args.no_patch)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
