"""插件机制。

一个插件就是一个模块，模块里定义 ``PLUGIN = Plugin(...)``，
在 setup 里往注册表挂处理函数。内置插件和用户插件走同一套接口。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from robot.core.bus import Registry

Setup = Callable[[Registry], None]


@dataclass(frozen=True)
class Plugin:
    """插件描述。

    Attributes:
        name: 唯一名。
        description: 一行说明，会出现在 /help 里。
        setup: 注册处理函数的回调。
        commands: 该插件提供的命令说明，键是命令词。
    """

    name: str
    description: str
    setup: Setup
    commands: dict[str, str] | None = None
