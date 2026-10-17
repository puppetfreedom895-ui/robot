"""文本清理与分段。"""

from __future__ import annotations

from robot.core.text import sanitize_for_chat, split_text


def test_sanitize_strips_markdown() -> None:
    raw = "**重点**：这件事 `很重要`\n\n```python\nprint(1)\n```\n# 标题"
    cleaned = sanitize_for_chat(raw)
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "#" not in cleaned
    assert "重点" in cleaned


def test_sanitize_removes_bullets() -> None:
    assert sanitize_for_chat("- 第一\n- 第二") == "第一\n第二"


def test_split_short_text_returns_single_chunk() -> None:
    assert split_text("短句", 80) == ["短句"]


def test_split_breaks_on_sentence_end() -> None:
    text = "第一句话很长很长。" * 10
    chunks = split_text(text, 30)
    assert len(chunks) > 1
    assert all(len(chunk) <= 30 for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def test_split_empty_returns_empty_list() -> None:
    assert split_text("   ", 10) == []
