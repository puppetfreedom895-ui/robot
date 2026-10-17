"""大脑与执行器：真实模型做决定、DSH 去执行。"""

from __future__ import annotations

import sys

from robot.life.brain import LLMBrain, parse_decision
from robot.life.runner import DshRunner, parse_command
from robot.life.state import LifeState
from robot.llm.base import ChatMessage, LLMError, Provider


class ScriptedProvider(Provider):
    """按脚本返回文本的假模型。"""

    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, messages) -> str:
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self._replies) - 1)
        return self._replies[index]


class BrokenProvider(Provider):
    """总是失败的假模型。"""

    async def complete(self, messages) -> str:
        raise LLMError("模型挂了")


async def test_llm_brain_parses_decision() -> None:
    provider = ScriptedProvider(['{"act": true, "intent": "看会儿剧", "say": "有点无聊"}'])
    decision = await LLMBrain(provider).decide("你想干嘛", LifeState())

    assert decision.act is True
    assert decision.intent == "看会儿剧"
    assert decision.say == "有点无聊"
    assert provider.calls[0][0].role == "system"


async def test_llm_brain_rests_when_model_fails() -> None:
    decision = await LLMBrain(BrokenProvider()).decide("你想干嘛", LifeState())
    assert decision.act is False


async def test_llm_brain_tolerates_chatty_output() -> None:
    provider = ScriptedProvider(['好的\n{"act": false}\n就这样'])
    assert (await LLMBrain(provider).decide("", LifeState())).act is False


async def test_dsh_runner_returns_last_line() -> None:
    command = [sys.executable, "-c", "print('我正在打开B站'); print('我刷了一会儿视频')"]
    narration = await DshRunner(command, timeout=30).run("刷会儿手机")
    assert narration == "我刷了一会儿视频"


async def test_dsh_runner_reports_failure() -> None:
    command = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    narration = await DshRunner(command, timeout=30).run("刷会儿手机")
    assert "没做成" in narration
    assert "boom" in narration


async def test_dsh_runner_reports_missing_command() -> None:
    narration = await DshRunner(["这个命令肯定不存在"], timeout=5).run("刷会儿手机")
    assert "起不来" in narration


async def test_dsh_runner_times_out() -> None:
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    narration = await DshRunner(command, timeout=0.3).run("慢慢来")
    assert "超时" in narration


async def test_dsh_runner_passes_action_prompt() -> None:
    command = [sys.executable, "-c", "import sys; print(sys.argv[1].replace(chr(10), ' ')[:200])"]
    narration = await DshRunner(command, timeout=30).run("看看天气")
    assert "看看天气" in narration


def test_parse_command_handles_windows_style() -> None:
    assert parse_command("dsh --profile headless") == ["dsh", "--profile", "headless"]
    assert parse_command("   ") == []
    assert parse_command(r"C:\tools\dsh.exe run") == [r"C:\tools\dsh.exe", "run"]


def test_parse_command_keeps_quoted_arguments_together() -> None:
    tokens = parse_command('python -c "import sys; print(sys.argv)"')
    assert tokens == ["python", "-c", "import sys; print(sys.argv)"]

    single = parse_command("run '两个 词'")
    assert single == ["run", "两个 词"]


def test_parse_decision_still_works_after_refactor() -> None:
    assert parse_decision('{"act": true, "intent": "散步"}').intent == "散步"
