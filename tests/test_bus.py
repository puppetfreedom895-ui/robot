"""事件总线：优先级、阻断与异常隔离。"""

from __future__ import annotations

import pytest

from robot.core.bus import Bus, Registry, on_message
from robot.core.context import Context
from robot.core.runtime import Runtime
from tests.conftest import FakeBot, build_event


def make_context(settings, bot: FakeBot | None = None) -> Context:
    runtime = Runtime(settings=settings, memory=None, llm=None)  # type: ignore[arg-type]
    return Context(event=build_event(), bot=bot or FakeBot(), runtime=runtime)


async def test_handlers_run_in_priority_order(settings) -> None:
    registry = Registry()
    order: list[str] = []

    @on_message(registry, name="late", priority=200)
    async def late(ctx: Context) -> bool:
        order.append("late")
        return False

    @on_message(registry, name="early", priority=10)
    async def early(ctx: Context) -> bool:
        order.append("early")
        return False

    await Bus(registry).dispatch(make_context(settings))
    assert order == ["early", "late"]


async def test_returning_true_stops_chain(settings) -> None:
    registry = Registry()
    order: list[str] = []

    @on_message(registry, name="stopper", priority=10)
    async def stopper(ctx: Context) -> bool:
        order.append("stopper")
        return True

    @on_message(registry, name="never", priority=20)
    async def never(ctx: Context) -> bool:
        order.append("never")
        return False

    handled = await Bus(registry).dispatch(make_context(settings))
    assert handled is True
    assert order == ["stopper"]


async def test_handler_exception_does_not_break_others(settings) -> None:
    registry = Registry()
    order: list[str] = []

    @on_message(registry, name="boom", priority=10)
    async def boom(ctx: Context) -> bool:
        raise RuntimeError("炸了")

    @on_message(registry, name="after", priority=20)
    async def after(ctx: Context) -> bool:
        order.append("after")
        return True

    assert await Bus(registry).dispatch(make_context(settings)) is True
    assert order == ["after"]


async def test_duplicate_handler_name_rejected() -> None:
    registry = Registry()

    @on_message(registry, name="same")
    async def one(ctx: Context) -> bool:
        return False

    with pytest.raises(ValueError, match="重名"):

        @on_message(registry, name="same")
        async def two(ctx: Context) -> bool:
            return False
