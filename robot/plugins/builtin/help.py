"""帮助：列出机器人会做什么。"""

from __future__ import annotations

from typing import Any

from robot.core.bus import PRIORITY_COMMAND, on_message
from robot.core.context import Context
from robot.plugins.base import Plugin
from robot.plugins.builtin.common import match_command

HELP_TEXT = "我会聊天，也能记住一些事。发「/help」随时看这页。"


async def handle(ctx: Context) -> bool:
    """响应 /help。

    @param ctx: 处理上下文。
    @returns: 命中命令返回 True。
    """
    matched = match_command(ctx.event.text)
    if matched is None:
        return False
    command, _ = matched
    if command not in ("help", "帮助", "菜单"):
        return False

    lines = [HELP_TEXT, ""]
    plugins: list[Any] = ctx.runtime.state.get("plugins", [])
    for plugin in plugins:
        commands = getattr(plugin, "commands", None)
        if not commands:
            continue
        for word, description in commands.items():
            lines.append(f"{word} - {description}")
    lines.append("")
    lines.append("在群里 @我 或者喊「机器人」就能让我接话。")
    await ctx.reply("\n".join(lines))
    return True


PLUGIN = Plugin(
    name="help",
    description="列出可用功能",
    setup=lambda registry: on_message(
        registry, name="help.command", priority=PRIORITY_COMMAND, plugin="help"
    )(handle),
    commands={"help": "查看功能列表"},
)
