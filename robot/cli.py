"""命令行入口：run / chat / doctor / version。"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import socket
import subprocess
import sys
from urllib.parse import urlparse

from robot import __version__
from robot.app import RobotApp
from robot.config import Settings, load_settings
from robot.core.event import MessageEvent
from robot.life.runner import parse_command
from robot.llm.base import LLMError
from robot.log import get_logger, setup_logging
from robot.service import LifeService

logger = get_logger(__name__)

CONSOLE_SESSION = "private:1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robot", description="QQ 大模型聊天机器人")
    parser.add_argument("--config", default="config.toml", help="配置文件路径（默认 config.toml）")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="连接 QQ 并开始聊天")
    run.add_argument("--config", default=argparse.SUPPRESS)

    live = sub.add_parser("live", help="常驻运行：QQ 聊天 + 自己心跳 + 操作手机")
    live.add_argument("--config", default=argparse.SUPPRESS)

    chat = sub.add_parser("chat", help="在终端里和机器人对话，不连 QQ")
    chat.add_argument("--config", default=argparse.SUPPRESS)

    doctor = sub.add_parser("doctor", help="检查配置与连通性")
    doctor.add_argument("--config", default=argparse.SUPPRESS)
    doctor.add_argument("--online", action="store_true", help="额外发一次真实模型请求验证密钥")

    sub.add_parser("version", help="显示版本")
    return parser


def _load(args: argparse.Namespace) -> Settings:
    settings = load_settings(args.config)
    setup_logging(settings.log_level)
    return settings


async def _run(settings: Settings) -> None:
    app = RobotApp(settings)
    try:
        await app.run()
    except KeyboardInterrupt:
        logger.info("已退出")


async def _live(settings: Settings) -> int:
    """常驻模式：聊天 + 心跳 + 手机操作。

    @param settings: 已加载的配置。
    @returns: 退出码。
    """
    if not settings.life.enabled:
        print(
            "config.toml 里的 [life] enabled 还是 false，先把它打开再跑 live。",
            file=sys.stderr,
        )
        return 2
    if not settings.life.owner:
        print("提示：[life] owner 没填，它想主动说话时发不出去。", file=sys.stderr)

    service = LifeService(settings)
    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("已退出")
    return 0


async def _chat(settings: Settings) -> None:
    """本地终端对话，用来在接 QQ 之前确认模型和记忆都正常。"""
    app = RobotApp(settings)
    print(f"已连接到 {settings.llm.model}（本地会话，输入 exit 退出）")
    try:
        while True:
            try:
                text = (await asyncio.to_thread(input, "你> ")).strip()
            except EOFError:
                break
            if not text:
                continue
            if text in ("exit", "quit", "退出"):
                break

            event = _console_event(text)
            await app.memory.record_user(event, text)
            try:
                messages = await app.memory.build_messages(CONSOLE_SESSION)
                reply = await app.provider.complete(messages)
            except LLMError as exc:
                print(f"[模型出错] {exc}")
                continue
            await app.memory.record_assistant(event, reply)
            print(f"机器人> {reply}")
    finally:
        await app.provider.close()
        app.db.close()


def _console_event(text: str) -> MessageEvent:
    """构造一条只在本地终端使用的事件。

    @param text: 用户输入。
    @returns: 会话键固定为 private:1 的事件。
    """
    return MessageEvent(
        self_id=0,
        message_type="private",
        user_id=1,
        message_id=0,
        segments=(),
        raw={"console": True},
        sender_name="你",
    )


def _check(ok: bool, label: str, detail: str = "") -> bool:
    """打印一行检查结果。

    @param ok: 是否通过。
    @param label: 检查项。
    @param detail: 补充说明。
    @returns: 原样返回 ok，方便串联。
    """
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f"：{detail}" if detail else ""))
    return ok


async def _doctor(settings: Settings, online: bool) -> int:
    """逐项体检：配置、密钥、NapCat 端口、模型连通性。

    @param settings: 已加载的配置。
    @param online: 是否发真实请求验证模型。
    @returns: 进程退出码，0 表示全部通过。
    """
    print(f"配置目录：{settings.base_dir}")
    passed = True

    passed &= _check(
        bool(settings.llm.api_key),
        "模型密钥",
        "已配置" if settings.llm.api_key else "缺失，填 ROBOT_API_KEY",
    )

    persona_path = settings.path_of(settings.chat.persona_file)
    passed &= _check(
        persona_path.is_file(),
        "人设文件",
        str(persona_path) if persona_path.is_file() else "缺失，将使用内置人设",
    )

    onebot = settings.onebot
    if onebot.mode == "client":
        parsed = urlparse(onebot.url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3001
        reachable = _tcp_check(host, port)
        detail = f"{host}:{port} " + (
            "可连接" if reachable else "连不上，确认 NapCat 已启动并开了 WebSocket 服务端"
        )
        print(f"  {'✓' if reachable else '!'} NapCat 端口：{detail}")
    else:
        print(f"  ✓ 监听模式：ws://{onebot.host}:{onebot.port}{onebot.path}")

    life = settings.life
    if life.enabled:
        passed &= _check(
            bool(life.owner),
            "生命内核",
            f"心跳 {life.heartbeat_minutes:g} 分钟，主人 {life.owner}"
            if life.owner
            else "已启用但没配 owner，它想主动说话时发不出去",
        )
    else:
        print("  · 生命内核：未启用（只当聊天机器人）")

    web = settings.web
    if web.enabled:
        exposed = web.host not in ("127.0.0.1", "localhost") and not web.token
        passed &= _check(
            not exposed,
            "管理台",
            f"http://{web.host}:{web.port}"
            + ("，绑了外网却没配 token，任何人都能看到它！" if exposed else ""),
        )
    else:
        print("  · 管理台：未启用")

    serial = os.environ.get("PHONE_SERIAL", "").strip()
    if serial:
        adb = shutil.which("adb")
        passed &= _check(
            bool(adb),
            "手机",
            f"序列 {serial}" + ("" if adb else "，但 PATH 里没有 adb，连不上"),
        )
    else:
        print("  · 手机：未设 PHONE_SERIAL，不会操作手机")

    command = parse_command(settings.life.dsh_command)
    if command:
        ok, detail = _probe_command([command[0], "--version"])
        passed &= _check(
            ok,
            "DSH 执行器",
            detail if ok else f"{detail}；服务器上要装 npm 版（桌面版封装不能用）",
        )
    else:
        print("  · DSH 执行器：没配 dsh_command，动作只会占位")

    if online:
        from robot.llm.base import ChatMessage

        app_provider = RobotApp(settings).provider
        try:
            reply = await app_provider.complete([ChatMessage("user", "回复两个字：正常")])
            passed &= _check(True, "模型连通", reply[:40])
        except LLMError as exc:
            passed &= _check(False, "模型连通", str(exc))
        finally:
            await app_provider.close()

    return 0 if passed else 1


def _probe_command(argv: list[str], timeout: float = 15.0) -> tuple[bool, str]:
    """跑一次命令，确认它真的能用。

    @param argv: 命令与参数。
    @param timeout: 超时秒数。
    @returns: (是否可用, 说明文字)。
    """
    binary = argv[0]
    if shutil.which(binary) is None:
        return False, f"PATH 里找不到 {binary}"
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"跑不起来：{exc}"

    if completed.returncode != 0:
        raw = completed.stderr or completed.stdout
        lines = raw.decode("utf-8", errors="replace").strip().splitlines()
        detail = f"：{lines[-1][:80]}" if lines else ""
        return False, f"退出码 {completed.returncode}{detail}"
    return True, "可执行"


def _tcp_check(host: str, port: int, timeout: float = 2.0) -> bool:
    """探测 TCP 端口是否可连。

    @param host: 主机。
    @param port: 端口。
    @param timeout: 超时秒数。
    @returns: 可连为 True。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    """命令行主函数。

    @param argv: 参数列表，默认取 sys.argv[1:]。
    @returns: 进程退出码。
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "version"):
        print(f"robot {__version__}")
        return 0

    try:
        settings = _load(args)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:  # 配置校验失败也要给人看得懂的提示
        print(f"配置有误：{exc}", file=sys.stderr)
        return 2

    if args.command == "doctor":
        return asyncio.run(_doctor(settings, online=args.online))
    if args.command == "chat":
        asyncio.run(_chat(settings))
        return 0
    if args.command == "live":
        return asyncio.run(_live(settings))
    if args.command == "run":
        asyncio.run(_run(settings))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
