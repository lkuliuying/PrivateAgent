"""应用配置。

基于 pydantic-settings 从环境变量 / .env 读取，统一以 ``PA_`` 前缀。

数据目录策略（M4 打包预研）：
- 开发模式（``python -m`` / uvicorn 直接跑）：使用项目根 ``./data``，便于调试。
- 打包模式（PyInstaller，``sys.frozen`` 为真）：使用用户数据目录——
  Windows ``%APPDATA%/personal-assistant``，类 Unix ``~/.local/share/personal-assistant``。
- 任何模式都可用 ``PA_DATA_DIR`` 环境变量强制覆盖。

``chroma_dir`` / ``log_dir`` 由 ``data_dir`` 派生，不再单独配置。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def _read_secret_file(path: Path, *, label: str) -> str:
    """Read one bounded UTF-8 Docker/Podman secret without exposing its path."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} secret file is not readable") from exc
    if not raw or len(raw) > 4096:
        raise ValueError(f"{label} secret file must contain 1..4096 bytes")
    try:
        value = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} secret file must be UTF-8") from exc
    if not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{label} secret file contains invalid control characters")
    return value


def _default_data_dir() -> Path:
    """数据目录默认值：打包模式用平台用户数据目录，开发模式用项目 ``./data``。

    - Windows: ``%APPDATA%/personal-assistant``
    - macOS: ``~/Library/Application Support/personal-assistant``（第八阶段 M5 修正）
    - Linux: ``$XDG_DATA_HOME/personal-assistant`` 或 ``~/.local/share/personal-assistant``
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包模式
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or str(Path.home())
            return Path(base) / "personal-assistant"
        if sys.platform == "darwin":
            home = os.environ.get("HOME") or str(Path.home())
            return Path(home) / "Library" / "Application Support" / "personal-assistant"
        base = os.environ.get("XDG_DATA_HOME") or str(
            Path.home() / ".local" / "share"
        )
        return Path(base) / "personal-assistant"
    # 开发模式：项目根 ./data
    return Path("./data")


def _default_env_file() -> str | None:
    """env 文件路径：打包模式读用户数据目录下的 ``.env``（不存在则返回 None），开发模式读项目根 ``.env``。"""
    if getattr(sys, "frozen", False):
        p = _default_data_dir() / ".env"
        return str(p) if p.exists() else None
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PA_",
        env_file=_default_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # === 数据目录（chroma / logs 派生于此；可用 PA_DATA_DIR 覆盖） ===
    data_dir: Path = Field(default_factory=_default_data_dir)

    # === 本地后端 API ===
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_auth_enabled: bool = True
    # Container deployments bind a wildcard address inside the network
    # namespace and publish only to host loopback.  This opt-in never disables
    # authentication and remains false for desktop/source execution.
    api_allow_non_loopback_bind: bool = False
    api_token: SecretStr | None = None
    api_token_file: Path | None = None
    api_allowed_hosts: str = "127.0.0.1,localhost"
    api_allowed_origins: str = (
        "http://localhost:1420,http://127.0.0.1:1420,"
        "http://tauri.localhost,https://tauri.localhost,tauri://localhost"
    )
    agent_runs_api_enabled: bool = False
    agent_run_read_only_tools_enabled: bool = False
    agent_rag_tools_enabled: bool = False
    agent_context_builder_enabled: bool = False
    agent_context_max_tokens: int = Field(default=6_000, ge=128, le=1_000_000)
    agent_output_verification_enabled: bool = False
    agent_output_verification_max_retries: int = Field(default=1, ge=0, le=2)
    chat_agent_runtime_enabled: bool = False
    conversation_summary_worker_enabled: bool = False
    conversation_summary_allow_remote_provider: bool = False
    conversation_summary_tick_seconds: int = Field(default=60, ge=15, le=86_400)
    conversation_summary_min_source_messages: int = Field(default=12, ge=2, le=200)
    conversation_summary_keep_recent_messages: int = Field(default=8, ge=1, le=200)
    conversation_summary_max_source_messages: int = Field(default=40, ge=2, le=500)
    conversation_summary_max_source_chars: int = Field(
        default=24_000,
        ge=1_000,
        le=500_000,
    )
    mcp_enabled: bool = False

    @model_validator(mode="after")
    def validate_summary_worker_limits(self) -> Settings:
        if (
            self.conversation_summary_max_source_messages
            < self.conversation_summary_min_source_messages
        ):
            raise ValueError(
                "PA_CONVERSATION_SUMMARY_MAX_SOURCE_MESSAGES must be greater than "
                "or equal to PA_CONVERSATION_SUMMARY_MIN_SOURCE_MESSAGES"
            )
        return self

    # === MySQL ===
    db_url: str = (
        "mysql+aiomysql://root:@127.0.0.1:3306/personal_assistant?charset=utf8mb4"
    )
    db_password_file: Path | None = None

    # === Ollama ===
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:14b-instruct-q4_K_M"
    embed_model: str = "bge-m3"
    llm_temperature: float = 0.7
    llm_context_length: int = Field(default=8192, ge=128, le=10_000_000)

    # === 知识库 ===
    kb_enabled_by_default: bool = False
    versioned_rag_indexing_enabled: bool = False
    versioned_rag_retrieval_enabled: bool = False
    versioned_rag_retention_days: int = Field(default=14, ge=1, le=3650)
    versioned_rag_min_retired_versions: int = Field(default=1, ge=0, le=100)

    # === 日志 ===
    log_level: str = "INFO"

    @model_validator(mode="after")
    def load_secret_files(self) -> Settings:
        """Resolve explicit secret files and reject ambiguous dual sources."""
        if self.api_token_file is not None:
            if self.api_token is not None:
                raise ValueError("configure only one of PA_API_TOKEN or PA_API_TOKEN_FILE")
            self.api_token = SecretStr(
                _read_secret_file(self.api_token_file, label="API token")
            )

        if self.db_password_file is not None:
            parsed = make_url(self.db_url)
            if parsed.password:
                raise ValueError(
                    "PA_DB_URL must not contain a password when PA_DB_PASSWORD_FILE is set"
                )
            password = _read_secret_file(
                self.db_password_file,
                label="database password",
            )
            self.db_url = parsed.set(password=password).render_as_string(
                hide_password=False
            )
        return self

    @property
    def chroma_dir(self) -> Path:
        """向量库持久化目录。"""
        return self.data_dir / "chroma"

    @property
    def log_dir(self) -> Path:
        """日志目录。"""
        return self.data_dir / "logs"


# 单例：其他模块直接 from personal_assistant.config import settings
settings = Settings()  # type: ignore[call-arg]
