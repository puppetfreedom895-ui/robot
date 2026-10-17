"""运行期依赖容器：插件通过 context.runtime 拿到它们。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from robot.config import Settings
from robot.core.memory import MemoryManager
from robot.llm.base import Provider


@dataclass
class Runtime:
    """一次进程运行共享的依赖与状态。"""

    settings: Settings
    memory: MemoryManager
    llm: Provider
    bot_name: str = ""
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def state_ns(self) -> dict[str, Any]:
        """插件可用的可变状态字典（冷却时间、计数等）。

        @returns: 共享状态字典。
        """
        return self.state
