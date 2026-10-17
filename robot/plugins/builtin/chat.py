"""闲聊插件：判断该不该接话、调用模型、按真人节奏分段回。

触发规则（对应 config.toml 的 [trigger]）：
- 私聊：默认每条都回；
- 群聊：被 @、喊唤醒词，或命中设定概率时才回，避免刷屏。
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable

from robot.config import Settings
from robot.core.bus import PRIORITY_CHAT, on_message
from robot.core.context import Context
from robot.core.event import MessageEvent
from robot.core.text import sanitize_for_chat, split_text
from robot.llm.base import LLMError
from robot.log import get_logger
from robot.plugins.base import Plugin

logger = get_logger(__name__)

FALLBACK_REPLY = "我这会儿有点卡，等会儿再问我一次。"


def clean_group_text(event: MessageEvent) -> str:
    """去掉 @ 机器人的痕迹，得到真正要说的话。

    @param event: 群消息事件。
    @returns: 清理后的文本。
    """
    text = event.display_text
    for token in ("@你", f"@{event.self_id}", f"@{event.user_id}"):
        text = text.replace(token, "")
    return text.strip()


def evaluate_trigger(
    event: MessageEvent,
    settings: Settings,
    rng: Callable[[], float] = random.random,
) -> str | None:
    """判断这条消息要不要回，并返回应该喂给模型的文本。

    @param event: 消息事件。
    @param settings: 配置。
    @param rng: 随机数源，测试时可注入固定值。
    @returns: 需要回复时返回文本；不回复返回 None。
    """
    trigger = settings.trigger

    if not event.is_group:
        if not trigger.private:
            return None
        return event.display_text or None

    group_id = event.chat_id
    if group_id in trigger.group_blacklist:
        return None
    if trigger.group_whitelist and group_id not in trigger.group_whitelist:
        return None

    text = clean_group_text(event)
    if trigger.group_at and event.mentions_me():
        return text or event.display_text or None

    for prefix in trigger.group_prefixes:
        if prefix and text.startswith(prefix):
            remainder = text[len(prefix) :].strip()
            return remainder or None

    if trigger.group_probability > 0 and rng() < trigger.group_probability:
        return text or None

    return None


async def handle(ctx: Context) -> bool:
    """主回复逻辑。

    @param ctx: 处理上下文。
    @returns: 已回复返回 True，让后续处理函数不再介入。
    """
    event = ctx.event
    settings = ctx.settings
    stats = ctx.runtime.state.setdefault("stats", {})
    stats["seen"] = stats.get("seen", 0) + 1

    text = evaluate_trigger(event, settings)
    if text is None:
        return False

    cooldown = settings.trigger.cooldown
    session_key = event.session_key
    now = time.monotonic()
    cooldowns: dict[str, float] = ctx.runtime.state.setdefault("cooldowns", {})
    if cooldown and now - cooldowns.get(session_key, 0.0) < cooldown:
        return False
    cooldowns[session_key] = now

    await ctx.memory.record_user(event, text)

    try:
        messages = await ctx.memory.build_messages(session_key)
        raw = await ctx.runtime.llm.complete(messages)
    except LLMError as exc:
        logger.warning("模型调用失败：%s", exc)
        await ctx.reply(FALLBACK_REPLY)
        return True

    reply = sanitize_for_chat(raw)
    if not reply:
        logger.debug("模型返回空内容，跳过本次回复")
        return True

    max_len = settings.reply.max_len
    if len(reply) > max_len:
        reply = reply[:max_len].rstrip() + "…"

    await ctx.memory.record_assistant(event, reply)
    stats["replied"] = stats.get("replied", 0) + 1

    chunks = split_text(reply, settings.reply.split_len) if settings.reply.split else [reply]
    for index, chunk in enumerate(chunks):
        if index and settings.reply.split_delay > 0:
            await asyncio.sleep(settings.reply.split_delay)
        await ctx.reply(chunk)

    await ctx.memory.maybe_summarize(session_key)
    return True


PLUGIN = Plugin(
    name="chat",
    description="大模型闲聊（人设 + 记忆）",
    setup=lambda registry: on_message(
        registry, name="chat.reply", priority=PRIORITY_CHAT, plugin="chat"
    )(handle),
)
