"""长期记忆命令：/记住、/回忆、/忘记。"""

from __future__ import annotations

from robot.core.bus import PRIORITY_COMMAND, on_message
from robot.core.context import Context
from robot.plugins.base import Plugin
from robot.plugins.builtin.common import is_owner, match_command

MAX_FACT_LENGTH = 120


async def handle(ctx: Context) -> bool:
    """响应记忆相关命令。

    @param ctx: 处理上下文。
    @returns: 命中命令返回 True。
    """
    matched = match_command(ctx.event.text)
    if matched is None:
        return False
    command, args = matched

    if command in ("记住", "remember"):
        if not args:
            await ctx.reply("要记什么？写成「/记住 阿伟下周三过生日」这样。")
            return True
        fact = args[:MAX_FACT_LENGTH]
        created = await ctx.memory.remember(ctx.session_key, fact)
        await ctx.reply("记住了。" if created else "这条我本来就知道。")
        return True

    if command in ("回忆", "memory"):
        facts = await ctx.memory.recall(ctx.session_key)
        if not facts:
            await ctx.reply("这个会话我还没记住什么。")
            return True
        lines = ["我记得这些："] + [f"- {fact}" for fact in facts]
        await ctx.reply("\n".join(lines))
        return True

    if command in ("忘记", "forget"):
        if not is_owner(ctx):
            await ctx.reply("清空记忆只有管理员能做。")
            return True
        await ctx.memory.reset(ctx.session_key)
        await ctx.reply("会话记忆清空了。")
        return True

    return False


PLUGIN = Plugin(
    name="memory",
    description="手动记录与查看长期记忆",
    setup=lambda registry: on_message(
        registry, name="memory.command", priority=PRIORITY_COMMAND, plugin="memory"
    )(handle),
    commands={"记住": "让机器人记住一件事", "回忆": "查看已记住的事", "忘记": "清空记忆（管理员）"},
)
