"""把「它想说的话」发到 QQ。

它主动找人说话走这里：私聊主人。发不出去只记日志，不影响心跳继续跑。
"""

from __future__ import annotations

from robot.core.bot import Bot
from robot.log import get_logger

logger = get_logger(__name__)


class QQNotifier:
    """通过 OneBot 私聊把话发给主人。"""

    def __init__(self, bot: Bot, owner: int) -> None:
        self._bot = bot
        self._owner = owner
        self.sent: list[str] = []

    @property
    def owner(self) -> int:
        """当前配置的收件人。

        @returns: QQ 号，未配置时为 0。
        """
        return self._owner

    async def notify(self, text: str) -> None:
        """发一条私聊。

        @param text: 要说的内容，空内容会被忽略。
        """
        content = text.strip()
        if not content:
            return
        if not self._owner:
            logger.warning("没配置 [life] owner，这句话发不出去：%s", content[:40])
            return

        try:
            await self._bot.call_api(
                "send_private_msg",
                {
                    "user_id": self._owner,
                    "message": [{"type": "text", "data": {"text": content}}],
                },
            )
        except Exception as exc:  # 通道断了不该让心跳崩掉
            logger.warning("主动说话失败：%s", exc)
            return

        self.sent.append(content)
