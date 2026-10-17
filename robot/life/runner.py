"""执行器：把「想做的事」变成真的动作。

分两种：
- DemoRunner：占位，只回显，用来跑演示和测试；
- DshRunner：交给 DSH（带手机 MCP 工具），由它真的去点手机。

只有它决定要做事时才启动 DSH——心跳本身绝不带工具，这是省 token 的关键。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from robot.log import get_logger

logger = get_logger(__name__)

ACTION_PROMPT = (
    "你现在是一个普通网友，正自己拿着手机。请去做这件事：{intent}\n"
    "用手机工具真的做完，然后只用一句话说你做了什么，不要解释过程。"
)


class Runner(Protocol):
    """把「想做的事」变成真的动作。"""

    async def run(self, intent: str) -> str:
        """执行一个意图，返回一句叙述。"""
        ...


class DemoRunner:
    """占位执行器：不碰手机，只把意图记下来。"""

    def __init__(self) -> None:
        self.intents: list[str] = []

    async def run(self, intent: str) -> str:
        """记录意图。

        @param intent: 要做的事。
        @returns: 一句叙述。
        """
        self.intents.append(intent)
        return f"（占位执行）{intent}"


class DshRunner:
    """调 DSH 执行意图。

    命令通常形如 ``dsh --profile headless``，DSH 会带着手机 MCP 工具跑完一轮。
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout: float = 180.0,
        cwd: Path | None = None,
    ) -> None:
        if not command:
            raise ValueError("DSH 命令不能为空")
        self._command = list(command)
        self._timeout = timeout
        self._cwd = cwd

    @property
    def command(self) -> list[str]:
        """当前使用的命令。

        @returns: 命令列表。
        """
        return list(self._command)

    async def run(self, intent: str) -> str:
        """让 DSH 去完成这个意图。

        @param intent: 要做的事。
        @returns: 一句话结果；失败时返回失败原因。
        """
        prompt = ACTION_PROMPT.format(intent=intent)
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._cwd) if self._cwd else None,
            )
        except OSError as exc:
            logger.warning("启动 DSH 失败：%s", exc)
            return f"没做成，DSH 起不来：{exc}"

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self._timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            logger.warning("DSH 执行超时：%s", intent)
            return "没做完，超时了"

        text = stdout.decode("utf-8", errors="replace").strip()
        if process.returncode not in (0, None):
            detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
            logger.warning("DSH 退出码 %s：%s", process.returncode, detail[-1] if detail else "")
            return f"没做成，DSH 报错：{detail[-1] if detail else process.returncode}"

        return self._last_meaningful_line(text) or "做完了，但没说什么"

    @staticmethod
    def _last_meaningful_line(text: str) -> str:
        """取输出里最后一句像话的结果。

        @param text: DSH 的标准输出。
        @returns: 结果句，可能为空。
        """
        for line in reversed(text.splitlines()):
            stripped = line.strip()
            if stripped and not stripped.startswith(("[", "·", "-", ">", "$")):
                return stripped[:200]
        return ""


def parse_command(raw: str) -> list[str]:
    """把一行命令拆成参数列表。

    自己拆而不用 shlex：Windows 上反斜杠路径不能被当成转义，引号要能包住空格。

    @param raw: 如 ``dsh --profile headless``。
    @returns: 参数列表。
    """
    tokens: list[str] = []
    buffer: list[str] = []
    quote: str | None = None

    for char in raw.strip():
        if quote is not None:
            if char == quote:
                quote = None
            else:
                buffer.append(char)
        elif char in ("'", '"'):
            quote = char
        elif char.isspace():
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
        else:
            buffer.append(char)

    if buffer:
        tokens.append("".join(buffer))
    return tokens
