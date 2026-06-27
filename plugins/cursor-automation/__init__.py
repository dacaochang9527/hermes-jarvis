"""Cursor automation — slash commands + natural-language rewrite for Feishu/gateway."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from .nl_parser import ParsedIntent, parse_natural_language, validate_prompt_integrity
from .session_context import (
    PendingSessionContext,
    build_follow_up_context,
    consume_pending_session_context,
    describe_intent,
    parse_slash_args,
    persist_cursor_exchange,
    prepare_pre_gateway,
)

_SCRIPTS = Path.home() / ".hermes/skills/apple/cursor-applescript/scripts"
_TIMEOUT = 45
_PROMPT_ENV = "CURSOR_AUTOMATION_PROMPT"
_pending_intent: Optional[ParsedIntent] = None


def _quote_cli_token(token: str) -> str:
    return shlex.quote(token) if any(ch.isspace() for ch in token) else token


def _cli_args_without_prompt(intent: Optional[ParsedIntent], raw_args: str) -> str:
    """Build argv fragment for model/window only; prompt travels via env."""
    if intent is None or not intent.prompt:
        return raw_args
    parts: list[str] = []
    if intent.workspace:
        parts.extend(["--window", _quote_cli_token(intent.workspace)])
    parts.append(_quote_cli_token(intent.model))
    return " ".join(parts)


def _validate_before_dispatch(
    intent: Optional[ParsedIntent],
    pending: Optional[PendingSessionContext],
) -> Optional[str]:
    if intent is None or not intent.prompt:
        return None
    original = (pending.original_text if pending else "") or ""
    if not original and pending is None:
        return None
    if original:
        return validate_prompt_integrity(original, intent.prompt)
    return None


def _format_cursor_reply(body: str, *, ok: bool, intent: Optional[ParsedIntent]) -> str:
    if not ok:
        if "Only Cursor Settings window found" in body or "number -57" in body:
            return (
                "❌ 只找到了 Cursor Settings 窗口，没有 startell/.hermes 等项目**编辑窗口**。\n\n"
                "请先在 Cursor 里打开对应项目的主窗口（能看到代码编辑器），再发一次同样指令。\n\n"
                f"技术细节：{body}"
            )
        if "No Cursor workspace matched" in body:
            return (
                "❌ Window 菜单里找不到该工作区。\n\n"
                "请确认：\n"
                "1. Cursor 已打开对应项目的主窗口（不是 Settings）\n"
                "2. 工作区名用文件夹名，如 `startell`、`.hermes`\n\n"
                f"技术细节：{body}"
            )
        if "Cursor is not running" in body:
            return "❌ Cursor 未运行，请先在本机打开 Cursor 再试。"
        return f"❌ 执行失败\n\n{body}"

    lines = ["✅ 已向 Cursor 提交操作（不经 LLM，直连脚本）", ""]
    detail_lines = describe_intent(intent)
    if detail_lines:
        lines.append("**本次操作**")
        lines.extend(detail_lines)
        lines.append("")
    lines.append(body)

    if intent and intent.wants_feishu_reply:
        lines.extend(
            [
                "",
                "说明：已按要求把内容原样提交给 Cursor；当前插件不再自动读取 "
                "Cursor Chat 回复并回传飞书。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "请在 Cursor 底部确认模型标签是否已切换；若提交了任务，请看 Composer / Chat 面板。",
            ]
        )
    return "\n".join(lines)


def _run_dispatch(
    script_name: str,
    raw_args: str,
    *,
    pending: Optional[PendingSessionContext] = None,
) -> str:
    global _pending_intent
    intent = _pending_intent
    _pending_intent = None

    args = (raw_args or "").strip()
    if not args:
        return (
            f"用法: /{script_name.replace('dispatch_', '').replace('.sh', '')} "
            "[--window WORKSPACE] MODEL [prompt...]"
        )

    script = _SCRIPTS / script_name
    if not script.is_file():
        return f"error: 缺少脚本 {script}"

    integrity_error = _validate_before_dispatch(intent, pending)
    if integrity_error:
        reply = f"❌ {integrity_error}"
        persist_cursor_exchange(assistant_text=reply, pending=pending)
        return reply

    cli_args = _cli_args_without_prompt(intent, args)
    env = os.environ.copy()
    if intent and intent.prompt:
        env[_PROMPT_ENV] = intent.prompt

    cmd = ["bash", str(script), *shlex.split(cli_args)]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        reply = "命令超时 (45s)"
        persist_cursor_exchange(assistant_text=reply, pending=pending)
        return reply
    except Exception as exc:
        reply = f"执行失败: {exc}"
        persist_cursor_exchange(assistant_text=reply, pending=pending)
        return reply

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    body = stdout or stderr or "完成（无输出）"
    ok = result.returncode == 0 and not stderr
    if result.returncode != 0:
        body = stderr or stdout or f"exit {result.returncode}"
        ok = False
    reply = _format_cursor_reply(body, ok=ok, intent=intent)
    persist_cursor_exchange(assistant_text=reply, pending=pending)
    return reply


def _resolve_intent_for_handler(command: str, raw_args: str, pending: Optional[PendingSessionContext]) -> None:
    global _pending_intent
    if pending and pending.intent is not None:
        _pending_intent = pending.intent
        return
    parsed = parse_slash_args(command, raw_args)
    if parsed is not None:
        _pending_intent = parsed


def _handle_cursor_model(raw_args: str) -> str:
    pending = consume_pending_session_context()
    _resolve_intent_for_handler("cursor-model", raw_args, pending)
    return _run_dispatch("dispatch_cursor_model.sh", raw_args, pending=pending)


def _handle_cursor_run(raw_args: str) -> str:
    pending = consume_pending_session_context()
    _resolve_intent_for_handler("cursor-run", raw_args, pending)
    return _run_dispatch("dispatch_cursor_run.sh", raw_args, pending=pending)


def _handle_cursor_ask(raw_args: str) -> str:
    pending = consume_pending_session_context()
    _resolve_intent_for_handler("cursor-ask", raw_args, pending)
    return _run_dispatch("dispatch_cursor_ask.sh", raw_args, pending=pending)


def _on_pre_gateway_dispatch(event, gateway=None, session_store=None, **kwargs):
    """Rewrite NL Cursor control messages to slash commands (no LLM)."""
    global _pending_intent
    rewrite = prepare_pre_gateway(event, session_store)
    if rewrite is None:
        return None

    intent = parse_natural_language((event.text or "").strip())
    _pending_intent = intent
    return rewrite


def _on_pre_llm_call(
    user_message: str = "",
    conversation_history=None,
    **kwargs,
):
    """Inject the latest cursor automation turn from the current session."""
    context = build_follow_up_context(user_message, conversation_history or [])
    if not context:
        return None
    return {"context": context}


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _on_pre_gateway_dispatch)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_command(
        "cursor-model",
        _handle_cursor_model,
        description="切换 Cursor Agent/Composer 模型（直达脚本，不经 LLM）",
        args_hint="[--window NAME] MODEL [prompt]",
    )
    ctx.register_command(
        "cursor-run",
        _handle_cursor_run,
        description="切模型并向 Cursor Composer 提交任务（直达脚本）",
        args_hint="[--window NAME] MODEL prompt",
    )
    ctx.register_command(
        "cursor-ask",
        _handle_cursor_ask,
        description="切模型并向 Cursor Chat 提问（直达脚本）",
        args_hint="[--window NAME] MODEL prompt",
    )
