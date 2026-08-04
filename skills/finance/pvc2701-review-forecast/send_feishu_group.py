#!/usr/bin/env python3
"""Send a prepared PVC2701 document message to the one approved Feishu group."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests


SKILL_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SKILL_DIR / "configs" / "pvc2701_feishu.json"
ENV_PATH = Path.home() / ".hermes" / ".env"
OPEN_API = "https://open.feishu.cn"


def load_env() -> None:
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request_json(method: str, path: str, **kwargs):
    response = requests.request(method, f"{OPEN_API}{path}", timeout=30, **kwargs)
    payload = response.json()
    if response.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(f"飞书 API 失败 HTTP {response.status_code}: {json.dumps(payload, ensure_ascii=False)[:800]}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a PVC2701 report link to the fixed pvc2701 Feishu group.")
    parser.add_argument("--message-file", required=True, type=Path)
    args = parser.parse_args()

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    group = config["report_group"]
    if group != {
        "name": "pvc2701",
        "chat_id": "oc_d5aa041b453e9b6f8a38fba75fa94b37",
        "deliver": "feishu:oc_d5aa041b453e9b6f8a38fba75fa94b37",
    }:
        raise RuntimeError("PVC2701 飞书目标配置不符合固定安全边界，拒绝发送")
    message = args.message_file.read_text(encoding="utf-8").strip()
    if "PVC2701" not in message or "飞书文档：http" not in message:
        raise RuntimeError("消息缺少 PVC2701 标题或有效飞书文档链接，拒绝发送")

    load_env()
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
    token_payload = request_json(
        "POST",
        "/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    token = token_payload["tenant_access_token"]
    result = request_json(
        "POST",
        f"/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        json={
            "receive_id": group["chat_id"],
            "msg_type": "text",
            "content": json.dumps({"text": message}, ensure_ascii=False),
        },
    )
    print(json.dumps({"ok": True, "group": group["name"], "chat_id": group["chat_id"], "message_id": result["data"]["message_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

