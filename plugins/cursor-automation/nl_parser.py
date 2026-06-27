"""Parse natural-language Feishu/gateway messages into cursor slash commands."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Optional

# Folder names from Cursor Window menu (extend as needed).
WORKSPACE_ALIASES: dict[str, str] = {
    "hermes": ".hermes",
    ".hermes": ".hermes",
    "startell": "startell",
}

ACTION_RE = re.compile(
    r"(切换模型|切模型|换模型|改模型|模型切换|"
    r"切到|换成|改成|改为|换到|切换到|"
    r"switch(?:ing)?\s+model|change\s+model|model\s+switch)",
    re.IGNORECASE,
)

CURSOR_CTX_RE = re.compile(
    r"(cursor|composer|agent|cursor\s*的|cursor里|cursor\s*中)",
    re.IGNORECASE,
)

WINDOW_CTX_RE = re.compile(r"(窗口|工作区|workspace|项目窗口)", re.IGNORECASE)

TASK_RE = re.compile(
    r"(帮我|请|然后|并|接着|提交|写|跑|review|fix|整理|查|分析|看看|执行|处理|修复|优化)",
    re.IGNORECASE,
)

MODEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:模型(?:到|为|成|用)?|切到|换成|改成|改为|换到|用|using|to)\s*"
        r"(?P<model>gpt[-\w.]*|composer(?:\s*[\d.]+\s*(?:fast|high|low)?)?|"
        r"claude[-\w]*|opus|sonnet|deepseek[-\w]*|kimi[-\w]*|gemini[-\w]*|codex[-\w]*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<model>gpt[-\w.]+|composer\s*[\d.]+\s*(?:fast|high|low)?|"
        r"claude[-\w]+|deepseek[-\w]+|kimi[-\w]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?P<model>gpt|composer|opus|sonnet|codex)\b", re.IGNORECASE),
)

WORKSPACE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?P<ws>[\w.-]+)\s*(?:的)?\s*(?:窗口|工作区)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:在|到)\s*(?P<ws>[\w.-]+)\s*(?:窗口|工作区|里|中|项目)",
        re.IGNORECASE,
    ),
    re.compile(r"cursor\s*的\s*(?P<ws>[\w.-]+)", re.IGNORECASE),
    re.compile(
        r"(?:窗口|工作区|workspace|项目)\s*[:：]\s*(?P<ws>[\w.-]+)",
        re.IGNORECASE,
    ),
)

ASK_RE = re.compile(r"问(?:它|他|她|cursor|Cursor|一下)?")

ASK_TRIGGER_RE = re.compile(
    r"(?:然后|并|接着|再)?问(?:它|他|她|cursor|Cursor|一下)?[:：]?\s*",
    re.IGNORECASE,
)

FEISHU_RELAY_RE = re.compile(r"通过飞书(?:机器人)?(?:回复|告诉|发回)?我\s*$")

QUOTE_DELIMS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("\u201c", "\u201d"),  # “ ”
    ("「", "」"),
    ("'", "'"),
)


@dataclass(frozen=True)
class ParsedIntent:
    model: str
    workspace: Optional[str] = None
    prompt: Optional[str] = None
    wants_feishu_reply: bool = False
    ask_mode: bool = False

    def to_slash(self) -> str:
        if self.prompt and self.ask_mode:
            cmd = "cursor-ask"
        else:
            cmd = "cursor-run" if self.prompt else "cursor-model"
        parts: list[str] = [f"/{cmd}"]
        if self.workspace:
            parts.extend(["--window", self.workspace])
        parts.append(self.model)
        # Prompt is passed via CURSOR_AUTOMATION_PROMPT env — omit from slash rewrite
        # to avoid shell quoting round-trips truncating or altering the text.
        rendered: list[str] = []
        for token in parts:
            if any(ch.isspace() for ch in token):
                rendered.append(shlex.quote(token))
            else:
                rendered.append(token)
        return " ".join(rendered)


def _normalize_workspace(raw: str) -> Optional[str]:
    token = raw.strip().strip("「」\"'，,。！!？?")
    if not token:
        return None
    key = token.lower().lstrip("./")
    if key in WORKSPACE_ALIASES:
        return WORKSPACE_ALIASES[key]
    if token.startswith("."):
        return token
    if re.fullmatch(r"[\w.-]+", token):
        return token
    return None


def _extract_workspace(text: str) -> Optional[str]:
    for pattern in WORKSPACE_PATTERNS:
        match = pattern.search(text)
        if match:
            ws = _normalize_workspace(match.group("ws"))
            if ws:
                return ws
    lowered = text.lower()
    for alias, canonical in WORKSPACE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return canonical
    return None


def _extract_model(text: str) -> Optional[str]:
    for pattern in MODEL_PATTERNS:
        match = pattern.search(text)
        if match:
            model = re.sub(r"\s+", " ", match.group("model").strip())
            model = re.sub(r"[，,。！!？?]+$", "", model)
            if model:
                return model
    return None


def _extract_quoted_segment(text: str, start: int = 0) -> Optional[str]:
    """Return verbatim quoted content starting at or after ``start``."""
    segment = text[start:]
    stripped = segment.lstrip()
    offset = len(segment) - len(stripped)

    for open_q, close_q in QUOTE_DELIMS:
        if not stripped.startswith(open_q):
            continue
        close_idx = stripped.find(close_q, len(open_q))
        if close_idx == -1:
            continue
        return stripped[len(open_q):close_idx]

    # Fallback: first quoted span anywhere after start (e.g. quote before ask trigger).
    for open_q, close_q in QUOTE_DELIMS:
        open_idx = segment.find(open_q)
        if open_idx == -1:
            continue
        close_idx = segment.find(close_q, open_idx + len(open_q))
        if close_idx == -1:
            continue
        return segment[open_idx + len(open_q):close_idx]
    return None


def _strip_trailing_feishu_meta(text: str) -> str:
    """Remove only trailing Hermes-delivery instructions, never in-body text."""
    cleaned = (text or "").rstrip()
    while True:
        new = FEISHU_RELAY_RE.sub("", cleaned).rstrip(" ，,。！!？?")
        if new == cleaned:
            break
        cleaned = new
    return cleaned


def _extract_ask_prompt(text: str) -> Optional[str]:
    """Extract the question for Cursor Chat without altering its body."""
    match = ASK_TRIGGER_RE.search(text)
    if match:
        quoted = _extract_quoted_segment(text, match.end())
        if quoted is not None:
            return quoted
        tail = text[match.end():].lstrip()
        if tail:
            return tail

    if ASK_RE.search(text):
        quoted = _extract_quoted_segment(text)
        if quoted is not None:
            return quoted
    return None


def _extract_task_prompt(text: str) -> Optional[str]:
    """Extract Composer task text; prefer quoted spans verbatim."""
    task_split = re.split(
        r"(?:然后|并|接着|再|，|,)\s*",
        text,
        maxsplit=1,
    )
    if len(task_split) == 2 and TASK_RE.search(task_split[1]):
        clause = task_split[1].strip()
        quoted = _extract_quoted_segment(clause)
        if quoted is not None:
            return quoted
        cleaned = _strip_trailing_feishu_meta(clause)
        if cleaned and not ASK_TRIGGER_RE.match(cleaned):
            return cleaned
    return None


def validate_prompt_integrity(original: str, prompt: str) -> Optional[str]:
    """Return an error message when the extracted prompt is not faithful to ``original``."""
    if not original or not prompt:
        return None
    if prompt in original:
        return None
    for open_q, close_q in QUOTE_DELIMS:
        needle = f"{open_q}{prompt}{close_q}"
        if needle in original:
            return None
    return (
        "解析出的提问内容与原消息不一致，已拒绝提交以防截断或改写。\n"
        f"原消息长度 {len(original)} 字，解析结果长度 {len(prompt)} 字。\n"
        "建议把要问 Cursor 的内容用引号包起来，例如：然后问它「你的问题」"
    )


def _extract_prompt(text: str, *, ask_mode: bool) -> Optional[str]:
    if ask_mode:
        return _extract_ask_prompt(text)
    task = _extract_task_prompt(text)
    if task:
        return task
    quoted = _extract_quoted_segment(text)
    if quoted and len(quoted) >= 4:
        return quoted
    return None


def looks_like_cursor_model_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw or raw.startswith("/"):
        return False

    has_cursor = bool(CURSOR_CTX_RE.search(raw))
    has_window = bool(WINDOW_CTX_RE.search(raw))
    has_action = bool(ACTION_RE.search(raw))
    has_model = _extract_model(raw) is not None

    if has_cursor and (has_action or has_model):
        return True
    if has_window and has_model and (has_action or "模型" in raw or "用" in raw):
        return True
    if has_action and has_model:
        return True
    if has_cursor and has_window and has_model:
        return True
    return False


def parse_natural_language(text: str) -> Optional[ParsedIntent]:
    raw = (text or "").strip()
    if not looks_like_cursor_model_request(raw):
        return None

    model = _extract_model(raw)
    if not model:
        return None

    workspace = _extract_workspace(raw)
    ask_mode = bool(ASK_RE.search(raw))
    prompt = _extract_prompt(raw, ask_mode=ask_mode)
    wants_feishu_reply = bool(
        re.search(r"通过飞书(?:机器人)?(?:回复|告诉|发回)?我", raw)
    )
    return ParsedIntent(
        model=model,
        workspace=workspace,
        prompt=prompt,
        wants_feishu_reply=wants_feishu_reply,
        ask_mode=ask_mode,
    )
