"""内置插件共用的小工具：命令识别与权限判断。"""

from __future__ import annotations

from robot.core.context import Context

# 允许的命令前缀，方便不同习惯的用户。
PREFIXES = ("/", "／", "!", "！")


def match_command(text: str) -> tuple[str, str] | None:
    """识别命令并拆出参数。

    @param text: 消息纯文本。
    @returns: (小写命令词, 参数)；不是命令返回 None。
    """
    stripped = text.strip()
    if not stripped or stripped[0] not in PREFIXES:
        return None
    body = stripped[1:].strip()
    if not body:
        return None
    head, _, rest = body.partition(" ")
    return head.lower(), rest.strip()


def is_owner(ctx: Context) -> bool:
    """判断发送者是不是配置里的管理员。

    @param ctx: 处理上下文。
    @returns: 是管理员为 True。
    """
    owners = ctx.settings.admin.owners
    return bool(owners) and ctx.event.user_id in owners


def humanize_uptime(seconds: float) -> str:
    """把秒数转成「x小时y分」。

    @param seconds: 运行秒数。
    @returns: 可读时长。
    """
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"
