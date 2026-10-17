"""会话记忆：把「人设 + 长期事实 + 摘要 + 最近对话」拼成模型上下文。

这也是机器人「记得住人」的关键：
- 短期：最近 N 条消息原样带上；
- 中期：超出窗口的旧消息压成一段摘要，避免上下文无限膨胀；
- 长期：/记住 写入的事实永久保留，每次对话都带上。
"""

from __future__ import annotations

from dataclasses import dataclass

from robot.config import Settings
from robot.core.event import MessageEvent
from robot.core.persona import build_system_prompt
from robot.llm.base import ChatMessage, Provider
from robot.log import get_logger
from robot.store.db import Database

logger = get_logger(__name__)

SUMMARY_PROMPT = (
    "下面是一段群聊记录。请用不超过 150 字的中文摘要，保留参与者名字、"
    "讨论的话题、结论和还没解决的问题。只输出摘要本身，不要加任何前缀。"
)


@dataclass
class MemoryManager:
    """读写会话记忆并组装模型输入。"""

    db: Database
    provider: Provider
    settings: Settings
    persona: str
    bot_name: str = ""

    async def system_prompt(self, session_key: str) -> str:
        """构造带长期事实的 system prompt。

        @param session_key: 会话键。
        @returns: system 文本。
        """
        base = build_system_prompt(
            self.persona,
            bot_name=self.bot_name,
            disclose_ai=self.settings.chat.disclose_ai,
        )
        parts = [base]

        summary = await self.db.get_summary(session_key)
        if summary:
            parts.append(f"之前聊过这些内容，供你参考（不要直接复述）：{summary}")

        facts = await self.db.facts(session_key)
        if facts:
            bullet = "\n".join(f"- {fact}" for fact in facts)
            parts.append(f"你记住的关于他们的事：\n{bullet}")

        return "\n\n".join(parts)

    async def build_messages(self, session_key: str) -> list[ChatMessage]:
        """组装一次请求的完整消息列表。

        调用前应先把本轮用户输入落库，这样历史里的最后一条就是本次输入。

        @param session_key: 会话键。
        @returns: system + 最近历史。
        """
        messages = [ChatMessage("system", await self.system_prompt(session_key))]
        history = await self.db.recent(session_key, self.settings.chat.history_limit)
        for item in history:
            if item.role == "assistant":
                messages.append(ChatMessage("assistant", item.content))
            else:
                speaker = item.name or "有人"
                messages.append(ChatMessage("user", f"{speaker}：{item.content}"))
        return messages

    async def record_user(self, event: MessageEvent, user_text: str) -> None:
        """记录一条用户消息。

        @param event: 消息事件。
        @param user_text: 展示文本。
        """
        await self.db.append(event.session_key, "user", event.sender_name, user_text)

    async def record_assistant(self, event: MessageEvent, reply: str) -> None:
        """记录机器人自己发出的回复。

        @param event: 触发回复的事件。
        @param reply: 回复文本。
        """
        await self.db.append(event.session_key, "assistant", self.bot_name, reply)

    async def maybe_summarize(self, session_key: str) -> str | None:
        """会话过长时把旧消息压成摘要。

        @param session_key: 会话键。
        @returns: 更新后的摘要；未触发或失败时为 None。
        """
        if not self.settings.chat.summary_enabled:
            return None

        limit = self.settings.chat.history_limit
        total = await self.db.count(session_key)
        if total <= limit * 2:
            return None

        olds = await self.db.oldest(session_key, total - limit)
        if not olds:
            return None

        transcript = "\n".join(
            f"{item.name or ('机器人' if item.role == 'assistant' else '有人')}：{item.content}"
            for item in olds
        )
        try:
            summary = await self.provider.complete(
                [
                    ChatMessage("system", SUMMARY_PROMPT),
                    ChatMessage("user", transcript[-6000:]),
                ]
            )
        except Exception as exc:  # 摘要失败不能影响正常回复
            logger.warning("生成摘要失败，跳过本次压缩：%s", exc)
            return None

        await self.db.set_summary(session_key, summary)
        await self.db.delete_through(session_key, olds[-1].id)
        logger.info("会话 %s 已压缩 %d 条历史", session_key, len(olds))
        return summary

    async def remember(self, session_key: str, content: str) -> bool:
        """写入一条长期事实。

        @param session_key: 会话键（作为作用域）。
        @param content: 事实内容。
        @returns: 是否新增成功。
        """
        return await self.db.add_fact(session_key, content)

    async def recall(self, session_key: str) -> list[str]:
        """读取长期事实。

        @param session_key: 会话键。
        @returns: 事实列表。
        """
        return await self.db.facts(session_key)

    async def reset(self, session_key: str) -> None:
        """清空某会话的全部记忆（含长期事实）。

        @param session_key: 会话键。
        """
        await self.db.clear(session_key)
        await self.db.clear_facts(session_key)
