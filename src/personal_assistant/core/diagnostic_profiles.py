"""v0.9.0 H1-B（计划 §5.6）：首批内置只读诊断命令 profile。

实机试用纠偏：可执行请求不得退化为纯问答。以 Windows 的 MySQL 安装检查为
首个固定验收样例，提供固定 argv 的安全诊断命令：

- ``where.exe mysql`` / ``where.exe mysqld``：PATH 可执行文件定位；
- ``mysql --version``：客户端版本事实；
- ``sc.exe query <service>``：typed service probe（已知 MySQL 家族服务名
  白名单，模型不能拼任意服务名）。

安全边界（与项目命令 profile 相同口径，更严格）：

- 全部 ``risk_level=safe`` 且 ``allow_network=False``（零网络语义）；
- 未知工具精确 argv 规则（command_workflow ``_resolve_command``）保证
  前缀之后不得追加任何参数，模型不能拼接 shell/参数；
- 内置 profile 是代码事实，不可被 API 修改，不参与策略遮蔽排序之外的
  任何用户可控变更；
- confirm 模式下命令工具仍按契约 CONFIRM 逐次审批（内置 profile 不
  扩大默认权限）；workspace 自动批准按 §5.3 真实契约执行时复核。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BuiltinDiagnosticProfile:
    """内置诊断 profile（duck-type 兼容项目 profile 的匹配/执行字段）。

    ``command_json`` 使用项目 profile 的 ``{"args": [...]}`` 结构，
    直接复用 ``_profile_to_args`` 解析（同一可信入口，不新增解析分支）。
    """

    name: str
    command_json: dict = field(default_factory=dict)
    risk_level: str = "safe"
    allow_network: bool = False
    cwd_rel: str | None = None
    env_allowlist: tuple[str, ...] = ()
    max_output_bytes: int | None = None
    result_parser: str | None = None
    profile_version: int = 1
    # 内置固定 argv：精确匹配，前缀后不允许追加参数（执行层统一规则）。
    builtin: bool = True


# MySQL 家族已知服务名（typed service probe 白名单；新增需代码评审）。
MYSQL_FAMILY_SERVICE_NAMES = (
    "mysql",
    "mysql57",
    "mysql80",
    "mysql84",
    "mariadb",
)


def _builtin_profiles() -> tuple[BuiltinDiagnosticProfile, ...]:
    profiles: list[BuiltinDiagnosticProfile] = [
        BuiltinDiagnosticProfile(
            name="diag_where_mysql",
            command_json={"args": ["where.exe", "mysql"]},
            result_parser="plain",
        ),
        BuiltinDiagnosticProfile(
            name="diag_mysql_version",
            command_json={"args": ["mysql", "--version"]},
            result_parser="plain",
        ),
        BuiltinDiagnosticProfile(
            name="diag_where_mysqld",
            command_json={"args": ["where.exe", "mysqld"]},
            result_parser="plain",
        ),
    ]
    for service in MYSQL_FAMILY_SERVICE_NAMES:
        profiles.append(
            BuiltinDiagnosticProfile(
                name=f"diag_service_{service}",
                command_json={"args": ["sc.exe", "query", service]},
                result_parser="windows_service_probe",
            )
        )
    return tuple(profiles)


BUILTIN_DIAGNOSTIC_PROFILES: tuple[BuiltinDiagnosticProfile, ...] = (
    _builtin_profiles()
)


def diagnostic_profiles_description() -> str:
    """命令工具描述附加段：向模型公开可用的诊断固定 argv（低基数事实）。"""
    lines = [
        "内置只读诊断命令（固定 argv，逐条可用，无需项目 profile）："
    ]
    for profile in BUILTIN_DIAGNOSTIC_PROFILES:
        argv = [str(x) for x in profile.command_json.get("args", [])]
        lines.append("  " + " ".join(argv))
    lines.append(
        "检查本机软件安装时必须使用以上诊断命令收集证据，"
        "不得只给出手工操作教程；单个 PATH 未命中不得直接判定未安装。"
    )
    return "\n".join(lines)
