"""本地演示：看它自己过一天。

    python -m robot.life --ticks 12 --step 10

三种组合：
- 默认：规则版大脑 + 占位执行，零成本，验证链路；
- --model：真实模型做决定（需要 config.toml 里的密钥）；
- --dsh "dsh --profile headless"：决定之后交给 DSH 真的去操作手机。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from robot.life.brain import Brain, LLMBrain, OfflineBrain
from robot.life.loop import LifeLoop, Runner, TickResult
from robot.life.runner import DemoRunner, DshRunner, parse_command
from robot.life.store import LifeStore


class ManualClock:
    """可以手动拨动的时钟，方便快进演示。"""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now.timestamp()

    def advance(self, minutes: float) -> None:
        """把时间往前拨。

        @param minutes: 分钟数。
        """
        self._now += timedelta(minutes=minutes)

    @property
    def now(self) -> datetime:
        """当前演示时间。

        @returns: datetime。
        """
        return self._now


class ConsoleNotifier:
    """把「它想说的话」打到终端。之后换成 QQ。"""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def notify(self, text: str) -> None:
        """打印一句话。

        @param text: 内容。
        """
        self.messages.append(text)
        print(f"      ［说］{text}")


def _build_brain(args: argparse.Namespace) -> tuple[Brain, Any]:
    """按参数选大脑。

    @param args: 命令行参数。
    @returns: (大脑, 需要关闭的资源或 None)。
    """
    if not args.model:
        return OfflineBrain(), None

    from robot.config import load_settings
    from robot.llm.openai_compat import OpenAICompatProvider

    settings = load_settings(args.config)
    # 心跳只要一个 JSON，把输出压到最小
    llm = settings.llm.model_copy(update={"max_tokens": 200})
    provider = OpenAICompatProvider(llm)
    return LLMBrain(provider), provider


def _build_runner(args: argparse.Namespace) -> Runner:
    """按参数选执行器。

    @param args: 命令行参数。
    @returns: 执行器。
    """
    command = parse_command(args.dsh)
    if command:
        return DshRunner(command, timeout=args.dsh_timeout)
    return DemoRunner()


def _format_tick(now: datetime, result: TickResult) -> str:
    """把一次心跳格式化成几行。

    @param now: 本轮时间。
    @param result: 结果。
    @returns: 展示文本。
    """
    stamp = f"{now:%H:%M}"
    if result.slept:
        return f"{stamp}  😴 睡觉"
    if result.blocked:
        return f"{stamp}  🛑 想做「{result.intent}」，被护栏拦住"
    if result.acted:
        return f"{stamp}  🎬 做事：{result.intent}\n         └ {result.narration}"
    return f"{stamp}  💤 {result.narration or '待着'}"


async def _demo(args: argparse.Namespace) -> int:
    start = datetime.combine(datetime.today(), datetime.strptime(args.start, "%H:%M").time())
    clock = ManualClock(start)
    store = LifeStore(Path(args.db))
    brain, resource = _build_brain(args)
    runner = _build_runner(args)

    if args.add_goal:
        for goal in args.add_goal:
            await store.add_goal(goal)

    loop = LifeLoop(
        store=store,
        brain=brain,
        runner=runner,
        notifier=ConsoleNotifier(),
        clock=clock,
        quiet_hours=(args.quiet_start, args.quiet_end),
        daily_budget_tokens=args.budget,
    )

    print(f"从 {start:%H:%M} 开始，每 {args.step} 分钟醒一次：")
    print(f"大脑={type(brain).__name__} 执行={type(runner).__name__}\n")
    last_day = clock.now.strftime("%Y-%m-%d")
    try:
        for _ in range(args.ticks):
            result = await loop.tick()
            last_day = clock.now.strftime("%Y-%m-%d")
            print(_format_tick(clock.now, result))
            clock.advance(args.step)
    finally:
        state = await store.load_state()
        used = await store.tokens_on(last_day)
        print(f"\n结束时状态：{state.describe()}")
        print(f"{last_day} 用了约 {used} token")
        print("最近的日记：")
        for line in await store.recent_diary(2):
            print(f"  {line}")
        if resource is not None:
            await resource.close()
        store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    @param argv: 参数列表。
    @returns: 退出码。
    """
    parser = argparse.ArgumentParser(prog="life", description="生命内核演示")
    parser.add_argument("--ticks", type=int, default=12, help="醒几次")
    parser.add_argument("--step", type=float, default=10.0, help="每次间隔几分钟")
    parser.add_argument("--start", default="09:00", help="演示起始时间 HH:MM")
    parser.add_argument("--db", default="data/life.db", help="数据库路径")
    parser.add_argument("--budget", type=int, default=0, help="当天 token 额度，0 表示不限")
    parser.add_argument("--quiet-start", type=int, default=1, help="免打扰开始小时")
    parser.add_argument("--quiet-end", type=int, default=7, help="免打扰结束小时")
    parser.add_argument("--add-goal", action="append", help="给它一个自己惦记的事，可多次指定")
    parser.add_argument("--model", action="store_true", help="用真实模型做决定（需配置密钥）")
    parser.add_argument("--config", default="config.toml", help="配置文件路径")
    parser.add_argument("--dsh", default="", help='交给 DSH 执行，如 "dsh --profile headless"')
    parser.add_argument("--dsh-timeout", type=float, default=180.0, help="DSH 单次执行超时秒数")
    args = parser.parse_args(argv)
    return asyncio.run(_demo(args))


if __name__ == "__main__":
    raise SystemExit(main())
