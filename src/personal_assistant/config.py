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


def _default_env_files() -> tuple[str, str]:
    """依次读取主配置和独立 SMTP 配置；后者仅承载邮件服务参数。"""
    if getattr(sys, "frozen", False):
        data_dir = _default_data_dir()
        return str(data_dir / ".env"), str(data_dir / "smtp.env")
    return ".env", "smtp.env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PA_",
        env_file=_default_env_files(),
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
    # 多用户认证：注册端点可按部署策略关闭；首个成功注册账号成为管理员。
    allow_public_registration: bool = True
    auth_session_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    # 升级后的旧本地数据默认不归属任何新账号；仅在可信首次迁移时显式开启。
    claim_legacy_data_on_first_user: bool = False
    audit_log_retention_days: int = Field(default=90, ge=1, le=3650)
    log_retention_days: int = Field(default=30, ge=1, le=3650)
    security_cleanup_interval_seconds: int = Field(
        default=3600, ge=60, le=86_400
    )

    # === 注册邮箱验证码（smtp.env / PA_SMTP_*） ===
    smtp_host: str = ""
    smtp_port: int = Field(default=465, ge=1, le=65_535)
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_from_email: str = ""
    smtp_from_name: str = "PrivateAgent"
    smtp_use_ssl: bool = True
    smtp_starttls: bool = False
    smtp_timeout_seconds: int = Field(default=15, ge=3, le=60)
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
    mcp_enabled: bool = True

    # === v0.5.0 可信工作流独立开关（B0 冻结，全部默认关闭） ===
    # 四类高风险工作流各有独立 flag；不存在同时开启多类工作流的总开关。
    # 开启规则见 docs/releases/v0.5.0/v0.5.0-b0-contracts-20260809.md §3：
    # - 未配置授权项目/endpoint profile/只读 SQL profile 时，对应工具不注册；
    # - 单开关关闭不需要数据库 downgrade。
    agent_patch_workflow_enabled: bool = False
    agent_command_workflow_enabled: bool = False
    agent_http_workflow_enabled: bool = False
    agent_sql_readonly_workflow_enabled: bool = False

    # === 兼容遥测持久化（R3 §6.4 跨版本观察窗口） ===
    # 开启后 CompatibilityTelemetry 的窗口计数定期落库（compatibility_telemetry 表，
    # schema 0021+），进程退出标记 ended_at；跨窗口聚合用于 legacy 归零观察。
    # 0.3.0 M1：下次启动时 reconcile 早于宽限期仍未 ended_at 的陈旧窗口
    # （异常退出），满足 M0 门槛"异常退出在下次启动被 reconcile"。
    compatibility_telemetry_persist_enabled: bool = False
    compatibility_telemetry_flush_seconds: int = Field(default=60, ge=10, le=3_600)
    compatibility_telemetry_reconcile_grace_seconds: int = Field(
        default=7_200,
        ge=60,
        le=86_400,
    )

    # === v0.6.0 Coding Agent（全部默认关闭） ===
    # 开启后 AgentRun 支持 project/workspace 绑定、幂等创建和真实计划持久化。
    # 关闭时全部旧行为不变；关闭不需要 schema downgrade。
    # 开启顺序固定为 project-bound → plan → stream；关闭顺序相反。
    project_bound_runs_enabled: bool = False
    agent_run_plan_enabled: bool = False
    agent_run_event_stream_enabled: bool = False

    # === v0.7.0 可信编码执行（全部默认关闭，每类新工具独立 flag） ===
    # 开启顺序：project-bound → 各编码 flag；关闭顺序相反。
    # 关闭任一 flag 只隐藏对应工具/API，不需要 schema downgrade（E0 契约 §8）。
    coding_patchset_enabled: bool = False
    coding_command_profiles_enabled: bool = False
    coding_artifacts_enabled: bool = False
    coding_permission_models_enabled: bool = False

    # === v0.9.0 Coding Agent 默认切换与可靠性（全部默认关闭） ===
    # H0 契约：docs/releases/v0.9.0/v0.9.0-h0-contracts-20260823.md §2。
    # coding_agent_ui_enabled：capabilities 声明位，前端默认切换依据；
    # 安装版经发布门禁后可置 true，显式回退保持短期可用（计划 §3.3）。
    coding_agent_ui_enabled: bool = False
    # workspace 档真实自动批准能力位（依赖 project-bound + 命令 profile）。
    coding_workspace_auto_approve_enabled: bool = False
    # 独立 full_access capability：授予/撤销/到期/审计（不是 workspace 别名）。
    coding_full_access_enabled: bool = False
    # full_access 授予有效期（分钟）；到期/退出应用/切换项目自动失效。
    coding_full_access_ttl_minutes: int = Field(default=240, ge=60, le=1440)
    # 上下文 budget/compaction 公开端点与事件。
    coding_context_budget_enabled: bool = False
    # 自动压缩阈值（usage_percent）；达到后下一轮执行前压缩旧上下文。
    coding_context_compaction_threshold: int = Field(default=80, ge=50, le=99)
    # 保留输出预算（tokens）：上下文窗口中为模型输出预留的额度（H0 §7.1）。
    coding_context_reserved_output_tokens: int = Field(
        default=1024, ge=128, le=131_072
    )
    # 压缩时保留的最近消息条数（最新用户请求与近期事实不被丢弃）。
    coding_context_keep_recent_messages: int = Field(default=8, ge=2, le=200)
    # execution 视图聚合端点与 decision.summary 公开决策摘要事件。
    coding_execution_detail_enabled: bool = False
    # v1.0 CT-3（专项计划 §8.2）：模型配置保存后自动执行工具能力探测并持久化
    # 快照；用于能力诊断与设置页反馈，不授予或撤销内建工具执行权限。
    agent_v2_model_probe_enabled: bool = True
    # v1.0 CT-9（专项计划 §14.2/§20）：工具快照诊断 API（observe-only，
    # 脱敏视图；不改变任何执行语义）。默认关闭，灰度按专项计划 §20 顺序。
    agent_v2_tool_snapshot_enabled: bool = False
    # ---- v1.0 专项计划 §20 Feature Flags（owner：Agent 架构；退出/删除：
    # RC 冻结默认值，v1.1 评估移除；灰度顺序见 §20）----
    # v2 Tool Engine 主链接入（CT-4 交付物在应用层，接入主链的灰度开关）；
    # 关闭时执行面维持 v0.9 dispatcher（§24 回退：同一 Turn 不切换执行器）。
    agent_v2_tool_engine_enabled: bool = False
    # 写入预检门禁（CT1-04/F-002）。当前阶段=enforce（默认开）；关闭回落
    # v0.9 无预检形态（§24 按 Thread/source 回退），不得用于绕过完成门禁。
    agent_v2_tool_preflight_enabled: bool = True
    # 副作用完成证据门禁（CT1-05/ADR-007）。当前阶段=enforce（默认开）；
    # 关闭时回落 v0.9 条件族求值（同样非 fail-open）；一旦进入 enforce，
    # 不得对副作用任务 fail-open（§20 规则）。
    agent_v2_completion_evidence_enabled: bool = True
    # Rust Exec Host 接入（CT-6）。默认关闭；开启仅意味着允许 Python Core
    # 拉起 exec-host，通用命令能力仍受沙箱门禁（ADR-004）失败关闭约束。
    agent_v2_exec_host_enabled: bool = False
    # Deferred Tool Search 接入模型面（CT-7，P1）；应用层实现已就绪，
    # 接入 Runtime 前保持关闭（§20：不阻断 P0）。
    agent_v2_deferred_tool_search_enabled: bool = False
    # 只读工具安全并发（AD-T07）；默认关闭（恒串行），开启需 §19.3 延迟/
    # replay 一致性基准通过。
    agent_v2_safe_parallel_tools_enabled: bool = False
    # native apply-patch 自由格式适配器（§20 明确默认关闭，不进普通用户设置）；
    # 仅当模型 probe 证明稳定后由 ADR 重新决策（adoption manifest §3.1.1 Defer）。
    agent_v2_native_apply_patch_enabled: bool = False
    # Codex App Server 隔离 Spike（CT-8，dev-only；§20 明确默认关闭，
    # 不进普通用户设置；当前结论 Defer，见 adr/evidence/ct8-*）。
    codex_app_server_spike_enabled: bool = False
    # 可选 Git worktree（H3）：显式创建/清理，模型无 Git 管理权限。
    coding_worktree_enabled: bool = False

    @model_validator(mode="after")
    def validate_v060_flag_order(self) -> Settings:
        """C0 §10：flag 开启顺序固定 project-bound → plan → stream。"""
        if self.agent_run_plan_enabled and not self.project_bound_runs_enabled:
            raise ValueError(
                "PA_AGENT_RUN_PLAN_ENABLED requires "
                "PA_PROJECT_BOUND_RUNS_ENABLED"
            )
        if (
            self.agent_run_event_stream_enabled
            and not self.agent_run_plan_enabled
        ):
            raise ValueError(
                "PA_AGENT_RUN_EVENT_STREAM_ENABLED requires "
                "PA_AGENT_RUN_PLAN_ENABLED"
            )
        return self

    @model_validator(mode="after")
    def validate_v070_coding_flag_order(self) -> Settings:
        """E0 §8：v0.7.0 编码 flag 依赖 project-bound；关闭顺序相反。"""
        coding_flags = (
            ("PA_CODING_PATCHSET_ENABLED", self.coding_patchset_enabled),
            ("PA_CODING_COMMAND_PROFILES_ENABLED", self.coding_command_profiles_enabled),
            ("PA_CODING_ARTIFACTS_ENABLED", self.coding_artifacts_enabled),
        )
        for env_name, enabled in coding_flags:
            if enabled and not self.project_bound_runs_enabled:
                raise ValueError(
                    f"{env_name} requires PA_PROJECT_BOUND_RUNS_ENABLED"
                )
        return self

    @model_validator(mode="after")
    def validate_v090_coding_flag_order(self) -> Settings:
        """H0 §2.3：v0.9.0 flag 依赖 project-bound；auto_approve 额外要求命令 profile。"""
        v090_flags = (
            ("PA_CODING_FULL_ACCESS_ENABLED", self.coding_full_access_enabled),
            ("PA_CODING_CONTEXT_BUDGET_ENABLED", self.coding_context_budget_enabled),
            (
                "PA_CODING_EXECUTION_DETAIL_ENABLED",
                self.coding_execution_detail_enabled,
            ),
            ("PA_CODING_WORKTREE_ENABLED", self.coding_worktree_enabled),
        )
        for env_name, enabled in v090_flags:
            if enabled and not self.project_bound_runs_enabled:
                raise ValueError(
                    f"{env_name} requires PA_PROJECT_BOUND_RUNS_ENABLED"
                )
        if (
            self.coding_workspace_auto_approve_enabled
            and not self.project_bound_runs_enabled
        ):
            raise ValueError(
                "PA_CODING_WORKSPACE_AUTO_APPROVE_ENABLED requires "
                "PA_PROJECT_BOUND_RUNS_ENABLED"
            )
        if (
            self.coding_workspace_auto_approve_enabled
            and not self.coding_command_profiles_enabled
        ):
            raise ValueError(
                "PA_CODING_WORKSPACE_AUTO_APPROVE_ENABLED requires "
                "PA_CODING_COMMAND_PROFILES_ENABLED"
            )
        return self

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
    # R3：token 估算安全系数（保守上界）。与真实 provider usage 对比校准见
    # data/rehearsals/r3-tokenizer-20260806/report.json——纯字符公式会低估，
    # 默认 2.0 保证抽样文本估算 ≥ 真实值；预算语义是保守上界而非精确计数。
    token_estimate_safety_factor: float = Field(default=2.0, ge=1.0, le=10.0)

    # === 知识库 ===
    kb_enabled_by_default: bool = False
    versioned_rag_indexing_enabled: bool = False
    versioned_rag_retrieval_enabled: bool = False
    versioned_rag_retention_days: int = Field(default=14, ge=1, le=3650)
    versioned_rag_min_retired_versions: int = Field(default=1, ge=0, le=100)

    # === RAG 证据充分性（R2.1 无答案拒答） ===
    # 开启后检索层对重排后的最终分数做"证据不足"判断，证据不足时返回空来源
    # 与结构化原因，由回答层明确说明资料不足，不生成弱引用。
    # 默认值经 2026-08-06 真实语料校准（data/rehearsals/rag-evidence-r2-20260806/）：
    # 已知答案 case 最高命中 0.906–0.954（双渠道）；无答案 case 0.761–0.848（单渠道）。
    # 分数策略无法拒答的语义反转干扰（>0.88 双渠道命中）记录为已知局限，需语义级验证。
    rag_evidence_enabled: bool = False
    rag_evidence_min_final_score: float = Field(default=0.80, ge=0.0, le=1.0)
    rag_evidence_min_single_channel_score: float = Field(default=0.85, ge=0.0, le=1.0)

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
        if self.smtp_use_ssl and self.smtp_starttls:
            raise ValueError(
                "configure only one of PA_SMTP_USE_SSL or PA_SMTP_STARTTLS"
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
