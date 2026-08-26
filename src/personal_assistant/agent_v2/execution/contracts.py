"""Exec Host JSONL 协议契约（专项计划 §11.2 P0 方法/事件，CT6-01）。

传输形态：stdin/stdout 上的 JSONL；每行一个 JSON-RPC 风格消息
（method/params 或 result/error），单消息上限与 ADR-002 一致（1 MiB，
超限内容转 artifact ref）。

红线（AD-T02）：``execution/start`` 不携带用户审批 token；Exec Host
不得写数据库、不得调用模型、不得把任何执行标记为完成。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 协议版本（破坏性变更必须递增并在握手时失败关闭）。
PROTOCOL_VERSION = "1.0"

MAX_MESSAGE_BYTES = 1024 * 1024


class ExecMethod(StrEnum):
    """P0 请求方法（§11.2）。"""

    INITIALIZE = "initialize"
    HEALTH_READ = "health/read"
    EXECUTION_START = "execution/start"
    EXECUTION_STDIN_WRITE = "execution/stdin/write"
    EXECUTION_OUTPUT_READ = "execution/output/read"
    EXECUTION_CANCEL = "execution/cancel"
    EXECUTION_STATUS_READ = "execution/status/read"
    SHUTDOWN = "shutdown"


class ExecNotification(StrEnum):
    """P0 服务端事件（§11.2）。"""

    EXECUTION_STARTED = "execution/started"
    STDOUT_DELTA = "execution/stdout/delta"
    STDERR_DELTA = "execution/stderr/delta"
    OUTPUT_TRUNCATED = "execution/output/truncated"
    EXITED = "execution/exited"
    CANCELLED = "execution/cancelled"
    FAILED = "execution/failed"


class ExecError(BaseModel):
    """错误信封（固定五字段，对齐上位协议 §8.4-6）。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2_000)
    retryable: bool = False
    details: str | None = Field(default=None, max_length=2_000)
    trace_id: str | None = Field(default=None, max_length=128)


class ExecInitializeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: str = Field(default=PROTOCOL_VERSION, max_length=16)


class ExecStartParams(BaseModel):
    """规范化执行请求。

    环境变量采用 allowlist + explicit diff（§22.3）；不传审批 token；
    sandbox/network policy 由 Python 策略决议后下发 hash 与档位。
    """

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=8, max_length=64)
    mode: Literal["argv", "pty"] = "argv"  # shell 字符串模式按 §11.3 延期
    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = Field(min_length=1, max_length=2048)
    env_diff: dict[str, str] = Field(default_factory=dict, max_length=64)
    timeout_ms: int = Field(default=120_000, ge=1, le=600_000)
    output_limit_bytes: int = Field(default=512 * 1024, ge=1024, le=32 * 1024 * 1024)
    sandbox_policy_hash: str = Field(min_length=8, max_length=128)
    network_policy: Literal["none", "allowlist", "approved"] = "none"
    stdin_mode: Literal["closed", "pipe"] = "closed"
    # CT-6：MIC 完整性级别——low 经 restricted token 降级启动，
    # 对默认 Medium IL 标签的用户目录写入默认拒绝（workspace 外写入拦截）。
    # workspace 放行属策略层显式授权，不由 host 自行扩大。
    integrity_level: Literal["inherit", "low"] = "inherit"
    # §11.4：stdin_mode=pipe 时必须携带 session_nonce，host 对
    # execution/stdin/write 逐次校验；缺失/不匹配即结构化拒绝。
    session_nonce: str | None = Field(default=None, max_length=128)
    # CT6-N3：AppContainer 零能力启动——network_policy=none 时内核级默认
    # 拒绝全部 outbound（含 loopback）。非 none 一律失败关闭（能力授予未开放）。
    appcontainer: bool = False
    # N1b：AC 运行时根（解释器/依赖目录），host 为 AC SID 追加 RX(继承) ACE，
    # 执行结束撤销。仅受信调用方可用；上限 16 条。
    ac_grant_paths: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("argv")
    @classmethod
    def _argv_entries_bounded(cls, value: list[str]) -> list[str]:
        if any(not entry or len(entry) > 4096 for entry in value):
            raise ValueError("argv 每项长度必须为 1..4096")
        return value


class ExecCancelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=8, max_length=64)


class ExecStdinParams(BaseModel):
    """write_stdin 绑定 execution id + session nonce + 当前状态（§11.4）。"""

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=8, max_length=64)
    session_nonce: str = Field(min_length=8, max_length=128)
    data: str = Field(default="", max_length=262_144)
    close: bool = False


class ExecEvent(BaseModel):
    """服务端事件的统一信封（低敏感字段；输出正文走 delta 分帧）。"""

    model_config = ConfigDict(extra="forbid")

    notification: ExecNotification
    execution_id: str = Field(min_length=8, max_length=64)
    sequence: int = Field(ge=0)
    # delta 事件专用；exited/cancelled/failed 携带终态事实。
    stream: Literal["stdout", "stderr"] | None = None
    data: str | None = Field(default=None, max_length=262_144)
    truncated: bool | None = None
    exit_code: int | None = None
    cancelled_by_timeout: bool | None = None
    processes_remaining: int | None = Field(default=None, ge=0)
    error: ExecError | None = None


class ExecHealth(BaseModel):
    """health/read 响应：Exec Host 自报能力与沙箱可用性。"""

    model_config = ConfigDict(extra="forbid")

    protocol_version: str = Field(max_length=16)
    sandbox_available: bool
    modes: tuple[Literal["argv", "pty"], ...] = ("argv",)
    active_sessions: int = Field(default=0, ge=0)
