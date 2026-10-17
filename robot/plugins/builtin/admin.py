"""管理员命令：状态、重置记忆、查自己的号。"""

from __future__ import annotations

import time

from robot.core.bus import PRIORITY_COMMAND, on_message
from robot.core.context import Context
from robot.plugins.base import Plugin
from robot.plugins.builtin.common import humanize_uptime, is_owner, match_command


async def handle(ctx: Context) -> bool:
    """响应 /status、/reset、/id。

    @param ctx: 处理上下文。
    @returns: 命中命令返回 True。
    """
    matched = match_command(ctx.event.text)
    if matched is None:
        return False
    command, _args = matched

    if command in ("id", "whoami"):
        await ctx.reply(f"你的 QQ 号是 {ctx.event.user_id}")
        return True

    if command in ("status", "状态"):
        started = ctx.runtime.state.get("started_at", time.time())
        stats = ctx.runtime.state.setdefault("stats", {})
        await ctx.reply(
            "\n".join(
                [
                    f"运行时长：{humanize_uptime(time.time() - started)}",
                    f"模型：{ctx.settings.llm.model}",
                    f"收到消息：{stats.get('seen', 0)} 条",
                    f"回复消息：{stats.get('replied', 0)} 条",
                    f"插件：{len(ctx.runtime.state.get('plugins', []))} 个",
                ]
            )
        )
        return True

    if command in ("reset", "清空记忆"):
        if not is_owner(ctx):
            await ctx.reply("这个命令只有管理员能用。")
            return True
        await ctx.memory.reset(ctx.session_key)
        await ctx.reply("这个会话的记忆已经清空了。")
        return True

    if command in ("persona", "人设"):
        await ctx.reply(
            f"当前人设来自 {ctx.settings.chat.persona_file}，直接改那个文件就能换性格。"
        )
        return True

    return False


PLUGIN = Plugin(
    name="admin",
    description="状态查询与会话重置",
    setup=lambda registry: on_message(
        registry, name="admin.command", priority=PRIORITY_COMMAND, plugin="admin"
    )(handle),
    commands={
        "status": "查看运行状态",
        "reset": "清空当前会话记忆（管理员）",
        "id": "查看自己的 QQ 号",
    },
)
