"""界面树解析：把几万字符的 XML 压成几十行可读元素。

这是省 token 的核心。一段真实界面的无障碍树通常 2 万到 10 万字符，
其中绝大多数是布局容器、不可见节点和空属性。这里只留「能看懂的」和「能点的」，
再编号，让模型用编号操作而不是坐标。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

# class 名 → 中文类型，给模型看的
_CLASS_KINDS: tuple[tuple[str, str], ...] = (
    ("EditText", "输入框"),
    ("Button", "按钮"),
    ("ImageButton", "按钮"),
    ("CheckBox", "勾选框"),
    ("RadioButton", "单选框"),
    ("Switch", "开关"),
    ("SeekBar", "滑块"),
    ("Spinner", "下拉框"),
    ("Tab", "标签页"),
    ("ImageView", "图片"),
    ("TextView", "文本"),
)

DEFAULT_MAX_NODES = 40
DEFAULT_MAX_CHARS = 2000


@dataclass(frozen=True, slots=True)
class UiNode:
    """一个值得让模型看见的界面元素。"""

    index: int
    kind: str
    label: str
    bounds: tuple[int, int, int, int]
    node_id: str = ""
    checked: bool | None = None

    @property
    def center(self) -> tuple[int, int]:
        """元素中心点，点击时用。

        @returns: (x, y)。
        """
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def key(self) -> tuple[str, str]:
        """用于判断界面变化的稳定标识。

        @returns: (类型, 标签)。
        """
        return self.kind, self.label


def _parse_bounds(raw: str) -> tuple[int, int, int, int] | None:
    match = _BOUNDS.search(raw or "")
    if match is None:
        return None
    x1, y1, x2, y2 = (int(value) for value in match.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _kind_of(node: ET.Element) -> str:
    cls = node.get("class", "")
    for needle, kind in _CLASS_KINDS:
        if needle in cls:
            return kind
    if node.get("scrollable") == "true":
        return "可滑动"
    if node.get("clickable") == "true":
        return "可点"
    return "元素"


def _is_visible(node: ET.Element) -> bool:
    return node.get("visible-to-user", "true") != "false"


def _is_actionable(node: ET.Element) -> bool:
    if node.get("clickable") == "true" or node.get("long-clickable") == "true":
        return True
    if node.get("checkable") == "true" or node.get("scrollable") == "true":
        return True
    return "EditText" in node.get("class", "")


def _label_of(node: ET.Element) -> str:
    label = (node.get("text") or "").strip()
    if label:
        return label
    return (node.get("content-desc") or "").strip()


def parse_hierarchy(
    xml: str,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> list[UiNode]:
    """从无障碍树 XML 里挑出值得展示的元素。

    @param xml: uiautomator2 dump 出来的 XML。
    @param max_nodes: 最多保留多少个元素。
    @returns: 按屏幕顺序排列的元素列表，编号从 1 开始。
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []

    actionable: list[UiNode] = []
    textual: list[UiNode] = []
    seen_bounds: set[tuple[int, int, int, int]] = set()

    for node in root.iter("node"):
        if not _is_visible(node):
            continue
        bounds = _parse_bounds(node.get("bounds", ""))
        if bounds is None:
            continue
        label = _label_of(node)
        actionable_node = _is_actionable(node)
        if not label and not actionable_node:
            continue

        kind = _kind_of(node)
        if not label and kind in ("图片", "文本", "元素"):
            continue

        # 同一位置的多层包装只留一层，避免重复刷屏
        if bounds in seen_bounds and not label:
            continue
        seen_bounds.add(bounds)

        checked: bool | None = None
        if node.get("checkable") == "true":
            checked = node.get("checked") == "true"

        candidate = UiNode(
            index=0,
            kind=kind,
            label=label,
            bounds=bounds,
            node_id=_short_id(node.get("resource-id", "")),
            checked=checked,
        )
        (
            actionable
            if actionable_node or kind in ("输入框", "按钮", "开关", "勾选框")
            else textual
        ).append(candidate)

    chosen = actionable[:max_nodes]
    remaining = max_nodes - len(chosen)
    if remaining > 0:
        chosen = chosen + textual[:remaining]
    chosen.sort(key=lambda item: (item.bounds[1], item.bounds[0]))

    return [
        UiNode(
            index=position,
            kind=item.kind,
            label=item.label,
            bounds=item.bounds,
            node_id=item.node_id,
            checked=item.checked,
        )
        for position, item in enumerate(chosen, start=1)
    ]


def _short_id(resource_id: str) -> str:
    """resource-id 只留冒号后的短名，省 token。

    @param resource_id: 完整 id，如 com.android.settings:id/search。
    @returns: 短名，如 search。
    """
    return resource_id.split("/")[-1] if resource_id else ""


def format_node(node: UiNode) -> str:
    """把元素格式化成一行。

    @param node: 元素。
    @returns: 形如 ``#3 输入框「搜索」``。
    """
    suffix = ""
    if node.label:
        suffix = f"「{node.label}」"
    elif node.node_id:
        suffix = f"({node.node_id})"
    if node.checked is not None:
        suffix += " 已勾选" if node.checked else " 未勾选"
    return f"#{node.index} {node.kind}{suffix}"


def format_screen(
    nodes: list[UiNode],
    *,
    header: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
    total: int | None = None,
) -> str:
    """把元素列表拼成给模型看的文本，并强制长度上限。

    @param nodes: 元素列表。
    @param header: 首行信息，如当前应用与时间。
    @param max_chars: 总长度上限。
    @param total: 原始元素总数，用于提示被截断。
    @returns: 可直接进上下文的文本。
    """
    if not nodes:
        return header or "这个界面没有可读的元素，可能需要看截图"

    total_count = total if total is not None else len(nodes)
    reserve = len(f"…还有 {total_count} 个元素没列出") + 1

    # 空间太窄时宁可不显示首行，也要把元素和截断说明放下
    if header and max_chars - len(header) - reserve < 20:
        header = ""

    budget = max_chars - (len(header) + 1 if header else 0) - reserve
    lines: list[str] = [header] if header else []
    used = 0
    shown = 0
    for node in nodes:
        line = format_node(node)
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1

    hidden = total_count - shown
    if hidden > 0:
        lines.append(f"…还有 {hidden} 个元素没列出")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


def diff_nodes(old: list[UiNode], new: list[UiNode]) -> str:
    """比较两次界面，只描述变化。

    动作之后的回执越小越好：没有变化时一句话，有变化时只列增删。

    @param old: 上一次的元素列表。
    @param new: 这一次的元素列表。
    @returns: 变化描述。
    """
    old_keys = [node.key for node in old]
    new_keys = [node.key for node in new]
    added = [node for node in new if node.key not in old_keys]
    removed = [node for node in old if node.key not in new_keys]

    if not added and not removed:
        return "界面没有变化"

    lines = ["界面已变化"]
    if added:
        lines.extend(format_node(node) for node in added[:10])
        if len(added) > 10:
            lines.append(f"…新增 {len(added)} 个，只列前 10 个")
    if removed:
        lines.append("消失：" + "、".join(node.label or node.kind for node in removed[:6]))
    return "\n".join(lines)
