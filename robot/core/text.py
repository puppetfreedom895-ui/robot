"""文本处理：清理模型爱输出的 Markdown 残留，并把长回复切成几条短消息。"""

from __future__ import annotations

import re

_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_EMOJI_SHORTCODE = re.compile(r":[a-z_+-]+:")


def sanitize_for_chat(text: str) -> str:
    """去掉聊天里很出戏的 Markdown 痕迹。

    @param text: 模型原始输出。
    @returns: 适合直接发到 QQ 的纯文本。
    """
    cleaned = _FENCE.sub(lambda m: m.group(0).strip("`").strip(), text)
    cleaned = _INLINE_CODE.sub(r"\1", cleaned)
    cleaned = _BOLD.sub(r"\1", cleaned)
    cleaned = _ITALIC.sub(r"\1", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _BULLET.sub("", cleaned)
    cleaned = _EMOJI_SHORTCODE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def split_text(text: str, limit: int) -> list[str]:
    """把长文本切成若干条，尽量在句末断开。

    @param text: 已清理的文本。
    @param limit: 单条最大长度。
    @returns: 至少一条文本片段。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    pieces = re.split(r"(?<=[。！？!?…\n])", text)
    chunks: list[str] = []
    buffer = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if buffer and len(buffer) + len(piece) > limit:
            chunks.append(buffer.strip())
            buffer = piece
        else:
            buffer = buffer + piece
        while len(buffer) > limit:
            chunks.append(buffer[:limit])
            buffer = buffer[limit:]
    if buffer.strip():
        chunks.append(buffer.strip())
    return chunks or [text[:limit]]
