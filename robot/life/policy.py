"""自主性护栏：L0 看、L1 动、L2 说、L3 花。

L3 不靠提示词约束——长对话里提示词迟早被绕过——而是在执行前直接拒绝。
关键词宁可多拦一点：误拦只是它跑来找你确认，漏拦是真花钱。
"""

from __future__ import annotations

import re
from typing import Literal

Level = Literal["L1", "L2", "L3"]

# 碰钱、碰别人的东西、不可逆的操作
L3_KEYWORDS: tuple[str, ...] = (
    # 花钱
    "付款",
    "支付",
    "转账",
    "转钱",
    "汇款",
    "下单",
    "购买",
    "买",
    "充值",
    "提现",
    "打赏",
    "红包",
    "还款",
    "借钱",
    "贷款",
    # 不可逆
    "删除",
    "删",
    "清空",
    "卸载",
    "注销",
    "解绑",
    "格式化",
    "改密码",
    "重置",
    # 身份与关系
    "注册",
    "验证码",
    "绑定",
    "授权",
    "加好友",
    "删好友",
    "拉黑",
    "举报",
)

# 对外说话：可以做，但要说一声
L2_KEYWORDS: tuple[str, ...] = (
    "发消息",
    "私聊",
    "私信",
    "群里说",
    "回复他",
    "回他",
    "评论",
    "发动态",
    "转发",
)

# 「转 50 块」「买 3 元的」这类带金额的，一律按花钱处理
_MONEY = re.compile(r"\d+\s*(?:块钱|块|元|万|千)")


class PolicyBlocked(RuntimeError):
    """意图触碰了必须由人点头的边界。"""


def classify(intent: str) -> Level:
    """判断一个意图属于哪一级。

    @param intent: 它想做的一件事。
    @returns: "L1"、"L2" 或 "L3"。
    """
    text = intent or ""
    if any(keyword in text for keyword in L3_KEYWORDS) or _MONEY.search(text):
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
