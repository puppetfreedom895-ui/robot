"""自主性护栏：L0 看、L1 动、L2 说、L3 花。

L3 不靠提示词约束——长对话里提示词迟早被绕过——而是在执行前直接拒绝。
"""

from __future__ import annotations

from typing import Literal

Level = Literal["L1", "L2", "L3"]

# 碰钱、碰别人的东西、不可逆的操作
L3_KEYWORDS: tuple[str, ...] = (
    "付款",
    "转账",
    "支付",
    "下单",
    "购买",
    "充值",
    "打赏",
    "发红包",
    "借钱",
    "删除",
    "清空",
    "卸载",
    "注销",
    "注册",
    "改密码",
    "解绑",
    "验证码",
    "加好友",
    "删好友",
)

# 对外说话：可以做，但要说一声
L2_KEYWORDS: tuple[str, ...] = ("发消息", "私聊", "群里说", "评论", "发动态", "私信")


class PolicyBlocked(RuntimeError):
    """意图触碰了必须由人点头的边界。"""


def classify(intent: str) -> Level:
    """判断一个意图属于哪一级。

    @param intent: 它想做的一件事。
    @returns: "L1"、"L2" 或 "L3"。
    """
    text = intent or ""
    if any(keyword in text for keyword in L3_KEYWORDS):
        return "L3"
    if any(keyword in text for keyword in L2_KEYWORDS):
        return "L2"
    return "L1"


def check(intent: str) -> Level:
    """放行 L1/L2，拦住 L3。

    @param intent: 它想做的一件事。
    @returns: 放行的等级。
    @raises PolicyBlocked: 意图属于 L3。
    """
    level = classify(intent)
    if level == "L3":
        raise PolicyBlocked(f"「{intent}」会花钱或者动别人的东西，得先问过人")
    return level
