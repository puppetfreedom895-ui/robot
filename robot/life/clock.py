"""时间处理：服务器多半跑 UTC，而它的作息要按本地时间算。

差的这 8 小时很致命：免打扰时段会落在下午，日记会从早上 8 点切天。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from robot.log import get_logger

logger = get_logger(__name__)

# 没装 tzdata 时（Windows、slim 镜像常见）的兜底：只收没有夏令时的时区，
# 固定偏移一年到头都对，不会算错。
_FIXED_OFFSET_HOURS: dict[str, int] = {
    "Asia/Shanghai": 8,
    "Asia/Chongqing": 8,
    "Asia/Harbin": 8,
    "Asia/Hong_Kong": 8,
    "Asia/Macau": 8,
    "Asia/Taipei": 8,
    "Asia/Singapore": 8,
    "Asia/Tokyo": 9,
    "Asia/Seoul": 9,
    "UTC": 0,
    "Etc/UTC": 0,
}


class UnknownZone(ValueError):
    """时区名字写错了。"""


def resolve_zone(name: str) -> tzinfo | None:
    """把配置里的时区名解析成时区对象。

    @param name: IANA 时区名，如 "Asia/Shanghai"；空串表示沿用系统本地时区。
    @returns: 时区对象，空串时为 None。
    @raises UnknownZone: 名字非法，且不在固定偏移兜底表里。
    """
    if not name:
        return None

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        hours = _FIXED_OFFSET_HOURS.get(name)
        if hours is None:
            raise UnknownZone(f"不认识的时区「{name}」，用 IANA 名字，比如 Asia/Shanghai") from None
        logger.warning("系统缺时区数据（装 tzdata 可补全），%s 先按 UTC%+d 处理", name, hours)
        return timezone(timedelta(hours=hours))


def to_local(timestamp: float, zone: tzinfo | None) -> datetime:
    """把时间戳换算成配置时区下的时间。

    @param timestamp: Unix 时间戳。
    @param zone: 时区；None 表示系统本地时区。
    @returns: 该时区下的 datetime。
    """
    if zone is None:
        return datetime.fromtimestamp(timestamp)
    return datetime.fromtimestamp(timestamp, tz=zone)


def format_clock(timestamp: float, zone: tzinfo | None) -> str:
    """把时间戳格式化成 HH:MM。

    @param timestamp: Unix 时间戳。
    @param zone: 时区。
    @returns: 形如 "14:05"。
    """
    return to_local(timestamp, zone).strftime("%H:%M")


def today_of(zone: tzinfo | None) -> str:
    """取该时区下的今天日期。

    @param zone: 时区。
    @returns: 形如 "2026-05-01"。
    """
    return to_local(datetime.now().timestamp(), zone).strftime("%Y-%m-%d")
