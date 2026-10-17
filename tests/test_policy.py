"""L0–L3 护栏：宁可多拦，不能漏拦。"""

from __future__ import annotations

import pytest

from robot.life.policy import PolicyBlocked, check, classify


@pytest.mark.parametrize(
    "intent",
    [
        "给她转账五十块",
        "帮他付款",
        "下单买杯奶茶",
        "买杯咖啡",
        "往游戏里充值",
        "给群里发个红包",
        "把聊天记录删了",
        "卸载这个应用",
        "重新注册一个账号",
        "把验证码填进去",
        "加好友问问他",
        "把他的消息举报了",
        # 带金额的，不管动词认不认识
        "转 50 块给她",
        "打赏 5 元",
    ],
)
def test_spending_and_destructive_actions_are_l3(intent: str) -> None:
    assert classify(intent) == "L3"
    with pytest.raises(PolicyBlocked):
        check(intent)


@pytest.mark.parametrize(
    "intent",
    [
        "刷会儿手机",
        "看看微博热搜",
        "打开设置关掉通知",
        "看看购物车里有什么",
        "听会儿歌",
        "拍张照",
    ],
)
def test_harmless_actions_stay_l1(intent: str) -> None:
    assert classify(intent) == "L1"
    assert check(intent) == "L1"


@pytest.mark.parametrize(
    "intent",
    ["发消息问问他", "私聊一下老同学", "在群里说一声", "评论一下", "回复他"],
)
def test_talking_is_l2_and_allowed(intent: str) -> None:
    assert classify(intent) == "L2"
    assert check(intent) == "L2"


def test_empty_intent_is_l1() -> None:
    assert classify("") == "L1"


def test_money_pattern_needs_a_number() -> None:
    assert classify("随便转一圈") == "L1"
    assert classify("转 3 块") == "L3"
