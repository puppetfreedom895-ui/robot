"""日志初始化：统一格式，减少第三方库噪音。"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """配置根日志器。

    @param level: 日志级别名，如 "DEBUG"、"INFO"。
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=_FORMAT,
        datefmt="%H:%M:%S",
        force=True,
    )
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """取一个带命名空间的日志器。

    @param name: 通常是 __name__。
    @returns: 日志器对象。
    """
    return logging.getLogger(name)
