"""事件总线与处理函数注册表。

对齐 AstrBot 的行为：处理函数按优先级顺序执行，返回 True 表示「已处理」，
后续处理函数不再运行。单个处理函数抛错不影响其他处理函数。
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from robot.core.context import Context
from robot.log import get_logger

logger = get_logger(__name__)

Handler = Callable[[Context], Awaitable[bool | None]]

# 处理函数的默认优先级，数值越小越先执行。
PRIORITY_COMMAND = 10
PRIORITY_CHAT = 100
PRIORITY_FALLBACK = 1000


@dataclass(frozen=True)
class HandlerSpec:
    """一个已注册的处理函数。"""

    name: str
    priority: int
    func: Handler
    plugin: str = ""


@dataclass
class Registry:
    """收集所有插件注册的处理函数。"""

    _handlers: list[HandlerSpec] = field(default_factory=list)

    def add(self, spec: HandlerSpec) -> None:
        """注册一个处理函数。

        @param spec: 处理函数描述。
        """
        if any(existing.name == spec.name for existing in self._handlers):
            raise ValueError(f"处理函数重名：{spec.name}")
        self._handlers.append(spec)

    def sorted_handlers(self) -> list[HandlerSpec]:
        """按优先级稳定排序。

        @returns: 处理函数列表，同名优先级保持注册顺序。
        """
        return sorted(self._handlers, key=lambda spec: spec.priority)

    def __len__(self) -> int:
        return len(self._handlers)


class Bus:
    """把事件依次交给处理函数。"""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry

    async def dispatch(self, ctx: Context) -> bool:
        """分发一次事件。

        @param ctx: 处理上下文。
        @returns: 有处理函数声明已处理时为 True。
        """
        for spec in self._registry.sorted_handlers():
            try:
                result = spec.func(ctx)
                if inspect.isawaitable(result):
                    result = await result
            except Exception:  # 单个插件崩了不能拖垮整条消息链
                logger.exception("处理函数 %s 执行失败", spec.name)
                ctx.failures += 1
                continue
            if result:
                return True
        return False


def on_message(
    registry: Registry,
    *,
    name: str,
    priority: int = PRIORITY_CHAT,
    plugin: str = "",
) -> Callable[[Handler], Handler]:
    """把一个异步函数注册为消息处理函数。

    @param registry: 注册表。
    @param name: 处理函数唯一名，用于日志与排错。
    @param priority: 优先级，越小越先执行。
    @param plugin: 所属插件名，便于排查。
    @returns: 装饰器。
    """

    def decorator(func: Handler) -> Handler:
        registry.add(HandlerSpec(name=name, priority=priority, func=func, plugin=plugin))
        return func

    return decorator
