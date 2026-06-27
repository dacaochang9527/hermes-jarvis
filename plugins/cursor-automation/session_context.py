"""Session persistence and follow-up context for cursor-automation."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .nl_parser import ParsedIntent, looks_like_cursor_model_request, parse_natural_language

CURSOR_SLASH_RE = re.compile(r"^/(cursor-model|cursor-run|cursor-ask)\b", re.IGNORECASE)
CURSOR_REPLY_MARKER = "✅ 已向 Cursor 提交操作"
FOLLOW_UP_HINT = (
    "【本对话最近的 Cursor 自动化记录 — 用户若在追问此操作，请优先基于以下记录回答；"
    "不要调用 session_search 去检索其他会话里的 startell / gpt 等旧记录。】"
)


@dataclass
class PendingSessionContext:
    original_text: str
    session_store: Any
    source: Any
    intent: Optional[ParsedIntent] = None


_pending_session: Optional[PendingSessionContext] = None


def set_pending_session_context(
    *,
    original_text: str,
    session_store: Any,
    source: Any,
    intent: Optional[ParsedIntent] = None,
) -> None:
    global _pending_session
    _pending_session = PendingSessionContext(
        original_text=original_text,
        session_store=session_store,
        source=source,
        intent=intent,
    )


def consume_pending_session_context() -> Optional[PendingSessionContext]:
    global _pending_session
    ctx = _pending_session
    _pending_session = None
    return ctx


def describe_intent(intent: Optional[ParsedIntent]) -> list[str]:
    if intent is None:
        return []
    lines: list[str] = []
    if intent.workspace:
        lines.append(f"- 工作区：`{intent.workspace}`")
    lines.append(f"- 模型：`{intent.model}`")
    if intent.prompt:
        target = "Cursor Chat" if intent.ask_mode else "Composer"
        lines.append(
            f"- 已向 {target} **原样**提交（{len(intent.prompt)} 字）：「{intent.prompt}」"
        )
    elif intent.ask_mode:
        lines.append("- 模式：Cursor Chat 提问")
    return lines


def persist_cursor_exchange(
    *,
    assistant_text: str,
    pending: Optional[PendingSessionContext] = None,
) -> None:
    ctx = pending or consume_pending_session_context()
    if ctx is None or ctx.session_store is None or ctx.source is None:
        return

    try:
        entry = ctx.session_store.get_or_create_session(ctx.source)
        ts = datetime.now().isoformat()
        user_msg: dict[str, Any] = {
            "role": "user",
            "content": ctx.original_text,
            "timestamp": ts,
            "cursor_automation": True,
        }
        if ctx.intent and ctx.intent.prompt:
            user_msg["cursor_prompt"] = ctx.intent.prompt

        ctx.session_store.append_to_transcript(entry.session_id, user_msg)
        ctx.session_store.append_to_transcript(
            entry.session_id,
            {
                "role": "assistant",
                "content": assistant_text,
                "timestamp": ts,
                "cursor_automation": True,
            },
        )
    except Exception:
        # Best-effort: automation should still work if transcript write fails.
        return


def _is_cursor_automation_message(message: dict[str, Any]) -> bool:
    if message.get("cursor_automation"):
        return True
    role = message.get("role")
    content = str(message.get("content") or "")
    if role == "assistant" and content.startswith(CURSOR_REPLY_MARKER):
        return True
    if role == "user" and looks_like_cursor_model_request(content):
        return True
    if role == "user" and CURSOR_SLASH_RE.match(content.strip()):
        return True
    return False


def find_recent_cursor_exchange(
    conversation_history: list[dict[str, Any]],
) -> Optional[tuple[str, str]]:
    """Return (user_text, assistant_text) for the latest cursor automation turn."""
    history = conversation_history or []
    for idx in range(len(history) - 1, -1, -1):
        msg = history[idx]
        if msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        if not (msg.get("cursor_automation") or content.startswith(CURSOR_REPLY_MARKER)):
            continue

        user_text = ""
        for prev in range(idx - 1, -1, -1):
            prev_msg = history[prev]
            if prev_msg.get("role") != "user":
                continue
            user_text = str(prev_msg.get("content") or "").strip()
            if user_text:
                break
        if user_text:
            return user_text, content.strip()
    return None


def build_follow_up_context(
    user_message: str,
    conversation_history: list[dict[str, Any]],
) -> Optional[str]:
    raw = (user_message or "").strip()
    if not raw or raw.startswith("/"):
        return None
    if looks_like_cursor_model_request(raw):
        return None
    if parse_natural_language(raw) is not None:
        return None

    exchange = find_recent_cursor_exchange(conversation_history)
    if not exchange:
        return None

    user_prev, assistant_prev = exchange
    return (
        f"{FOLLOW_UP_HINT}\n\n"
        f"用户上一条 Cursor 指令：\n{user_prev}\n\n"
        f"当时机器人回复：\n{assistant_prev}\n\n"
        f"当前用户追问：\n{raw}"
    )


def parse_slash_args(command: str, raw_args: str) -> Optional[ParsedIntent]:
    """Build ParsedIntent from `/cursor-*` args for reply formatting."""
    parts = shlex.split((raw_args or "").strip())
    if not parts:
        return None

    workspace: Optional[str] = None
    model: Optional[str] = None
    prompt_parts: list[str] = []
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        if token in {"--window", "-w", "-W", "--workspace"}:
            if idx + 1 >= len(parts):
                return None
            workspace = parts[idx + 1]
            idx += 2
            continue
        if token.startswith("--window="):
            workspace = token.split("=", 1)[1]
            idx += 1
            continue
        if token.startswith("--workspace="):
            workspace = token.split("=", 1)[1]
            idx += 1
            continue
        if model is None:
            model = token
            idx += 1
            continue
        prompt_parts.append(token)
        idx += 1

    if not model:
        return None

    prompt = " ".join(prompt_parts).strip() or None
    ask_mode = command.replace("_", "-") == "cursor-ask"
    return ParsedIntent(
        model=model,
        workspace=workspace,
        prompt=prompt,
        ask_mode=ask_mode,
    )


def prepare_pre_gateway(event, session_store) -> Optional[dict[str, str]]:
    """Set pending session context; return rewrite action when NL matches."""
    text = (event.text or "").strip()
    if not text:
        return None

    if CURSOR_SLASH_RE.match(text):
        set_pending_session_context(
            original_text=text,
            session_store=session_store,
            source=getattr(event, "source", None),
        )
        return None

    if text.startswith("/"):
        return None

    intent = parse_natural_language(text)
    if intent is None:
        return None

    set_pending_session_context(
        original_text=text,
        session_store=session_store,
        source=getattr(event, "source", None),
        intent=intent,
    )
    return {"action": "rewrite", "text": intent.to_slash()}
