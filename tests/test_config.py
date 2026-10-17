"""配置加载：.env 支持与环境变量优先级。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from robot.config import load_dotenv, load_settings

ENV_KEYS = (
    "ROBOT_API_KEY",
    "ROBOT_BASE_URL",
    "ROBOT_MODEL",
    "ROBOT_ONEBOT_TOKEN",
    "ROBOT_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """每个用例开始前把这些变量清干净，结束后自动还原。"""
    for name in ENV_KEYS:
        monkeypatch.delenv(name, raising=False)


def write_config(tmp_path: Path, body: str = '[llm]\napi_key = "from-file"\n') -> Path:
    """写一份最小配置。

    @param tmp_path: 临时目录。
    @param body: TOML 内容。
    @returns: 配置文件路径。
    """
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_dotenv_supplies_api_key(tmp_path) -> None:
    config = write_config(tmp_path)
    (tmp_path / ".env").write_text("ROBOT_API_KEY=from-dotenv\n", encoding="utf-8")

    settings = load_settings(config)
    assert settings.llm.api_key == "from-dotenv"


def test_shell_env_wins_over_dotenv(tmp_path, monkeypatch) -> None:
    config = write_config(tmp_path)
    (tmp_path / ".env").write_text("ROBOT_API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("ROBOT_API_KEY", "from-shell")

    assert load_settings(config).llm.api_key == "from-shell"


def test_dotenv_handles_quotes_comments_and_export(tmp_path) -> None:
    config = write_config(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "# 注释行",
                "",
                'ROBOT_API_KEY="带 空格"',
                "export ROBOT_MODEL=deepseek-flash",
                "ROBOT_ONEBOT_TOKEN='quoted-token'",
                "看起来不像键值对",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(config)
    assert settings.llm.api_key == "带 空格"
    assert settings.llm.model == "deepseek-flash"
    assert settings.onebot.token == "quoted-token"


def test_missing_dotenv_is_fine(tmp_path) -> None:
    config = write_config(tmp_path)
    assert load_dotenv(tmp_path / ".env") == 0
    assert load_settings(config).llm.api_key == "from-file"


def test_dotenv_does_not_override_process_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOT_MODEL", "already-set")
    (tmp_path / ".env").write_text("ROBOT_MODEL=from-file\n", encoding="utf-8")

    assert load_dotenv(tmp_path / ".env") == 0
    assert os.environ["ROBOT_MODEL"] == "already-set"
