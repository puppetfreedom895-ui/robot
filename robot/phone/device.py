"""设备抽象。

真实设备用 uiautomator2，测试用 FakeDevice。上层（MCP 工具）只认这个接口，
所以没有手机也能把整条链路跑通、写完测试。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DeviceError(RuntimeError):
    """设备不可用或操作失败。消息面向使用者，可直接展示。"""


class Device(Protocol):
    """一部安卓手机需要提供的最小能力集。"""

    serial: str

    def info(self) -> dict[str, Any]:
        """设备与前台应用信息。"""
        ...

    def dump(self) -> str:
        """当前界面的无障碍树 XML。"""
        ...

    def screenshot(self, path: Path) -> Path:
        """截屏并写到指定路径。"""
        ...

    def tap(self, x: int, y: int) -> None:
        """点击屏幕坐标。"""
        ...

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float) -> None:
        """滑动。"""
        ...

    def type_text(self, text: str, *, enter: bool = False, clear: bool = False) -> None:
        """往当前焦点输入框里打字。"""
        ...

    def press(self, key: str) -> None:
        """按物理/导航键。"""
        ...

    def open_app(self, name: str) -> None:
        """启动应用，name 可以是包名或常见中文名。"""
        ...


class FakeDevice:
    """离线假设备：按脚本切换界面，记录所有操作。

    用于单元测试和无手机时验证 MCP 链路。
    """

    def __init__(self, screens: list[str] | None = None, *, serial: str = "fake-0") -> None:
        self.serial = serial
        self._screens = screens or ['<hierarchy rotation="0"></hierarchy>']
        self._cursor = 0
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _advance(self) -> None:
        if self._cursor < len(self._screens) - 1:
            self._cursor += 1

    def info(self) -> dict[str, Any]:
        return {
            "serial": self.serial,
            "brand": "Fake",
            "model": "TestPhone",
            "android": "14",
            "package": "com.example.app",
            "activity": ".MainActivity",
            "battery": 88,
            "width": 1080,
            "height": 2400,
        }

    def dump(self) -> str:
        xml = self._screens[self._cursor]
        self._advance()
        return xml

    def screenshot(self, path: Path) -> Path:
        self.calls.append(("screenshot", {"path": str(path)}))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return path

    def tap(self, x: int, y: int) -> None:
        self.calls.append(("tap", {"x": x, "y": y}))
        self._advance()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float) -> None:
        self.calls.append(("swipe", {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration}))
        self._advance()

    def type_text(self, text: str, *, enter: bool = False, clear: bool = False) -> None:
        self.calls.append(("type_text", {"text": text, "enter": enter, "clear": clear}))
        self._advance()

    def press(self, key: str) -> None:
        self.calls.append(("press", {"key": key}))
        self._advance()

    def open_app(self, name: str) -> None:
        self.calls.append(("open_app", {"name": name}))
        self._advance()
