"""uiautomator2 实现的真实设备。

uiautomator2 是可选依赖（``pip install -e ".[phone]"``），没装也能跑测试和假设备。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from robot.phone.device import DeviceError

# 常见应用的中文名 → 包名，省得模型去猜
APP_ALIASES: dict[str, str] = {
    "微信": "com.tencent.mm",
    "qq": "com.tencent.mobileqq",
    "TIM": "com.tencent.tim",
    "支付宝": "com.eg.android.AlipayGphone",
    "淘宝": "com.taobao.taobao",
    "京东": "com.jingdong.app.mall",
    "美团": "com.sankuai.meituan",
    "饿了么": "me.ele",
    "抖音": "com.ss.android.ugc.aweme",
    "快手": "com.smile.gifmaker",
    "哔哩哔哩": "tv.danmaku.bili",
    "b站": "tv.danmaku.bili",
    "小红书": "com.xingin.xhs",
    "微博": "com.sina.weibo",
    "知乎": "com.zhihu.android",
    "网易云音乐": "com.netease.cloudmusic",
    "qq音乐": "com.tencent.qqmusic",
    "高德地图": "com.autonavi.minimap",
    "百度地图": "com.baidu.BaiduMap",
    "设置": "com.android.settings",
    "相机": "com.android.camera",
    "相册": "com.android.gallery3d",
    "浏览器": "com.android.browser",
    "计算器": "com.android.calculator2",
    "时钟": "com.android.deskclock",
    "日历": "com.android.calendar",
    "邮件": "com.android.email",
    "备忘录": "com.android.notes",
}

# OneBot 风格按键名 → uiautomator2 键名
KEY_ALIASES: dict[str, str] = {
    "back": "back",
    "home": "home",
    "recent": "recent",
    "enter": "enter",
    "power": "power",
    "wakeup": "wakeup",
    "sleep": "sleep",
    "volume_up": "volume_up",
    "volume_down": "volume_down",
    "menu": "menu",
}


class UiautomatorDevice:
    """通过 uiautomator2 驱动一部真实安卓机。"""

    def __init__(self, serial: str | None = None) -> None:
        try:
            import uiautomator2 as u2
        except ImportError as exc:
            raise DeviceError("没装 uiautomator2。运行 pip install -e '.[phone]' 后再试。") from exc

        self.serial = serial or ""
        try:
            # 传 ip:port 时会自动 adb connect，适合 Tailscale 组网后的远程调试
            self._d = u2.connect(serial) if serial else u2.connect()
        except Exception as exc:
            raise DeviceError(f"连不上手机 {serial or '(默认设备)'}：{exc}") from exc

    def info(self) -> dict[str, Any]:
        try:
            raw = self._d.info or {}
            current = self._d.app_current()
            width, height = self._d.window_size()
        except Exception as exc:
            raise DeviceError(f"读取设备信息失败：{exc}") from exc

        return {
            "serial": self.serial or raw.get("serial", ""),
            "brand": raw.get("brand", ""),
            "model": raw.get("model", ""),
            "android": str(raw.get("version", {}).get("release", ""))
            if isinstance(raw.get("version"), dict)
            else "",
            "package": current.get("package", "") if isinstance(current, dict) else "",
            "activity": current.get("activity", "") if isinstance(current, dict) else "",
            "battery": raw.get("battery", {}).get("level", "")
            if isinstance(raw.get("battery"), dict)
            else "",
            "width": width,
            "height": height,
        }

    def dump(self) -> str:
        try:
            return self._d.dump_hierarchy()
        except Exception as exc:
            raise DeviceError(f"读取界面失败：{exc}") from exc

    def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._d.screenshot(str(path))
        except Exception as exc:
            raise DeviceError(f"截图失败：{exc}") from exc
        return path

    def tap(self, x: int, y: int) -> None:
        try:
            self._d.click(x, y)
        except Exception as exc:
            raise DeviceError(f"点击 ({x},{y}) 失败：{exc}") from exc

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: float) -> None:
        try:
            self._d.swipe(x1, y1, x2, y2, duration=duration)
        except Exception as exc:
            raise DeviceError(f"滑动失败：{exc}") from exc

    def type_text(self, text: str, *, enter: bool = False, clear: bool = False) -> None:
        try:
            if clear:
                self._d.clear_text()
            self._d.send_keys(text)
            if enter:
                self._d.press("enter")
        except Exception as exc:
            raise DeviceError(f"输入失败：{exc}") from exc

    def press(self, key: str) -> None:
        target = KEY_ALIASES.get(key.lower())
        if target is None:
            raise DeviceError(f"不认识的按键：{key}")
        try:
            self._d.press(target)
        except Exception as exc:
            raise DeviceError(f"按键 {key} 失败：{exc}") from exc

    def open_app(self, name: str) -> None:
        package = APP_ALIASES.get(name.strip().lower(), APP_ALIASES.get(name.strip(), name.strip()))
        try:
            started = self._d.app_start(package, stop=False)
        except Exception as exc:
            raise DeviceError(f"启动 {name} 失败：{exc}") from exc
        if not started:
            raise DeviceError(f"没找到应用「{name}」，可以试试直接给包名")
