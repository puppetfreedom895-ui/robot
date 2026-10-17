"""插件加载：内置插件 + 用户插件目录。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from robot.core.bus import Registry
from robot.log import get_logger
from robot.plugins.base import Plugin

logger = get_logger(__name__)

# 内置插件按顺序加载，先命令后闲聊。
_BUILTIN_MODULES = (
    "robot.plugins.builtin.help",
    "robot.plugins.builtin.admin",
    "robot.plugins.builtin.memory",
    "robot.plugins.builtin.chat",
)


def _import_plugin(module_name: str) -> Plugin | None:
    """导入模块并取出其中的 PLUGIN 对象。

    @param module_name: 模块路径。
    @returns: 插件对象；不符合约定时返回 None。
    """
    try:
        module = importlib.import_module(module_name)
    except Exception:  # 插件自身导入失败不应带崩整个进程
        logger.exception("加载插件 %s 失败", module_name)
        return None

    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, Plugin):
        logger.warning("插件 %s 没有定义合法的 PLUGIN，已跳过", module_name)
        return None
    return plugin


def _load_file_plugin(path: Path) -> Plugin | None:
    """从用户目录里的单个 .py 文件加载插件。

    @param path: 插件文件路径。
    @returns: 插件对象；加载失败返回 None。
    """
    module_name = f"robot_user_plugin_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("无法为 %s 构建模块规格，已跳过", path)
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        logger.exception("加载用户插件 %s 失败", path)
        return None

    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, Plugin):
        logger.warning("用户插件 %s 没有定义合法的 PLUGIN，已跳过", path)
        return None
    return plugin


def load_plugins(registry: Registry, plugins_dir: Path | None = None) -> list[Plugin]:
    """加载全部插件并完成注册。

    @param registry: 处理函数注册表。
    @param plugins_dir: 用户插件目录，不存在则跳过。
    @returns: 成功加载的插件列表。
    """
    loaded: list[Plugin] = []

    for module_name in _BUILTIN_MODULES:
        plugin = _import_plugin(module_name)
        if plugin is None:
            continue
        try:
            plugin.setup(registry)
        except Exception:
            logger.exception("插件 %s 注册失败", plugin.name)
            continue
        loaded.append(plugin)

    if plugins_dir and plugins_dir.is_dir():
        for path in sorted(plugins_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            plugin = _load_file_plugin(path)
            if plugin is None:
                continue
            try:
                plugin.setup(registry)
            except Exception:
                logger.exception("用户插件 %s 注册失败", plugin.name)
                continue
            loaded.append(plugin)

    logger.info("已加载 %d 个插件：%s", len(loaded), ", ".join(p.name for p in loaded))
    return loaded
