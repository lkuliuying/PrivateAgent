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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # === MySQL ===
    db_url: str = (
        "mysql+aiomysql://root:@127.0.0.1:3306/personal_assistant?charset=utf8mb4"
    )

    # === Ollama ===
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:14b-instruct-q4_K_M"
    embed_model: str = "bge-m3"
    llm_temperature: float = 0.7
    llm_context_length: int = 8192

    # === 知识库 ===
    kb_enabled_by_default: bool = False

    # === 日志 ===
    log_level: str = "INFO"

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
