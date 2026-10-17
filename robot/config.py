"""配置模型与加载：TOML 文件 + 环境变量覆盖。

加载顺序：内置默认值 → config.toml → 环境变量。环境变量优先级最高，
便于在 Docker / 服务器上用环境变量注入密钥而不改文件。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_ENV_DEFAULTS = {
    "api_key": ("ROBOT_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY"),
}


class LLMSettings(BaseModel):
    """OpenAI 兼容接口的调用参数，默认指向 DeepSeek。"""

    base_url: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    model: str = "deepseek-chat"
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1)
    timeout: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


class OneBotSettings(BaseModel):
    """与 NapCat 的 OneBot v11 连接方式。

    mode="client"：本程序连到 NapCat 的 WebSocket 服务端（NapCat 里配「WebSocket服务器」）。
    mode="server"：本程序监听端口，NapCat 主动连进来（NapCat 里配「WebSocket客户端」）。
    """

    mode: Literal["client", "server"] = "client"
    url: str = "ws://127.0.0.1:3001"
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/onebot"
    token: str = ""
    reconnect_min: float = 1.0
    reconnect_max: float = 30.0


class TriggerSettings(BaseModel):
    """什么时候该回话。群聊默认只在被 @ 或喊唤醒词时开口，避免刷屏扰民。"""

    private: bool = True
    group_at: bool = True
    group_prefixes: list[str] = Field(default_factory=lambda: ["机器人"])
    group_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    cooldown: float = Field(default=1.0, ge=0.0)
    group_whitelist: list[int] = Field(default_factory=list)
    group_blacklist: list[int] = Field(default_factory=list)


class ReplySettings(BaseModel):
    """回复的分段与长度控制，用来模拟真人一句一句打字的节奏。"""

    split: bool = True
    split_len: int = Field(default=80, ge=10)
    split_delay: float = Field(default=0.6, ge=0.0)
    max_len: int = Field(default=500, ge=20)
    quote_reply: bool = False


class ChatSettings(BaseModel):
    """对话与人设。"""

    persona_file: str = "persona.md"
    history_limit: int = Field(default=20, ge=2)
    summary_enabled: bool = True
    disclose_ai: bool = True


class AdminSettings(BaseModel):
    """管理员 QQ 号，可执行清空记忆、切换人设等命令。"""

    owners: list[int] = Field(default_factory=list)


class LifeSettings(BaseModel):
    """生命内核：心跳频率、免打扰、额度与执行方式。"""

    enabled: bool = False
    owner: int = 0
    heartbeat_minutes: float = Field(default=10.0, gt=0)
    quiet_start: int = 1
    quiet_end: int = 7
    daily_budget_tokens: int = 0
    brain: Literal["offline", "model"] = "offline"
    dsh_command: str = ""
    dsh_timeout: float = Field(default=180.0, gt=0)
    database: str = "data/life.db"


class WebSettings(BaseModel):
    """只读管理台。默认关闭、只绑本机；放公网必须配 token。"""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    token: str = ""
    screens_dir: str = "data/screens"


class Settings(BaseModel):
    """全部配置。base_dir 由加载时注入，用于解析相对路径。"""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    onebot: OneBotSettings = Field(default_factory=OneBotSettings)
    trigger: TriggerSettings = Field(default_factory=TriggerSettings)
    reply: ReplySettings = Field(default_factory=ReplySettings)
    chat: ChatSettings = Field(default_factory=ChatSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)
    life: LifeSettings = Field(default_factory=LifeSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    database: str = "data/robot.db"
    plugins_dir: str = "plugins"
    log_level: str = "INFO"
    base_dir: Path = Field(default=Path("."), exclude=True)

    def path_of(self, relative: str) -> Path:
        """把配置里的相对路径解析成基于配置文件目录的绝对路径。

        @param relative: 配置中写的路径，绝对路径原样返回。
        @returns: 解析后的路径。
        """
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else (self.base_dir / candidate).resolve()


def _apply_env(settings: Settings) -> Settings:
    """用环境变量覆盖其中的密钥与连接令牌。

    @param settings: 从文件读到的配置。
    @returns: 覆盖后的配置对象。
    """
    for name in _ENV_DEFAULTS["api_key"]:
        value = os.environ.get(name)
        if value:
            settings.llm.api_key = value.strip()
            break

    base_url = os.environ.get("ROBOT_BASE_URL")
    if base_url:
        settings.llm.base_url = base_url.strip()

    model = os.environ.get("ROBOT_MODEL")
    if model:
        settings.llm.model = model.strip()

    token = os.environ.get("ROBOT_ONEBOT_TOKEN")
    if token:
        settings.onebot.token = token.strip()

    log_level = os.environ.get("ROBOT_LOG_LEVEL")
    if log_level:
        settings.log_level = log_level.strip().upper()

    return settings


def load_settings(config_path: str | Path = "config.toml") -> Settings:
    """读取配置文件并合并环境变量。

    @param config_path: TOML 配置文件路径；不存在时抛出 FileNotFoundError，避免静默用默认值启动。
    @returns: 完成校验的配置对象，base_dir 指向配置文件所在目录。
    @raises FileNotFoundError: 配置文件不存在。
    @raises pydantic.ValidationError: 配置项类型或取值非法。
    """
    path = Path(config_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(
            f"找不到配置文件 {path}。先复制 config.example.toml 为 config.toml 再改。"
        )

    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    settings = Settings.model_validate(raw)
    settings.base_dir = path.parent
    return _apply_env(settings)
