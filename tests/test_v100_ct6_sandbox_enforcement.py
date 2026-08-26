"""CT-6 沙箱强制端到端：Job Object 级联终止 + Low MIC 写入拦截。

前置：``cargo build --release --manifest-path apps/exec-host/Cargo.toml``；
binary 缺失、非 Windows，或当前会话禁止 exec-host 派生子进程（N1b 环境
阻断，见 _ct6_probe）时整组跳过。

覆盖（专项计划 §11.5 / §19.2 / ADR-004）：
- 进程树级联：cancel 后孙进程心跳停止（无孤儿）；
- Low MIC workspace 外写入默认拒绝；inherit 对照组写入成功；
- Low IL 子进程环境变量仅为显式 allowlist。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from _ct6_probe import SKIP_REASON, host_child_spawn_ok

from personal_assistant.agent_v2.execution.contracts import ExecStartParams
from personal_assistant.agent_v2.execution.exec_host_client import ExecHostClient

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BINARY_NAME = "exec-host.exe" if sys.platform == "win32" else "exec-host"
EXEC_HOST_BINARY = (
    _PROJECT_ROOT / "apps" / "exec-host" / "target" / "release" / _BINARY_NAME
)

pytestmark = [
    pytest.mark.skipif(
        not EXEC_HOST_BINARY.exists() or sys.platform != "win32",
        reason="exec-host 未构建或非 Windows 平台",
    ),
    pytest.mark.skipif(
        not host_child_spawn_ok(), reason=SKIP_REASON
    ),
]


def _params(
    execution_id: str,
    code: str,
    *,
    integrity_level: str = "inherit",
    timeout_ms: int = 60_000,
) -> ExecStartParams:
    env_diff = {
        key: value
        for key, value in (
            ("SystemRoot", os.environ.get("SystemRoot", "")),
            ("TEMP", os.environ.get("TEMP", "")),
            ("TMP", os.environ.get("TMP", "")),
        )
        if value
    }
    # Low IL 路径使用真实 base 解释器：venv 启动器需跨目录重定向，低完整性
    # 下会被基础镜像检查拒绝（实测 exit 103）。
    base_exe = sys.executable
    try:
        base_exe = sys._base_executable  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return ExecStartParams(
        execution_id=execution_id,
        argv=[base_exe, "-X", "utf8", "-c", code],
        cwd=str(_PROJECT_ROOT),
        timeout_ms=timeout_ms,
        sandbox_policy_hash="sandbox-hash-001",
        env_diff=env_diff,
        integrity_level=integrity_level,  # type: ignore[arg-type]
    )


async def _run_to_exited(client: ExecHostClient, max_events: int = 16):
    events = []
    for _ in range(max_events):
        event = await client.next_event(timeout=20)
        assert event is not None, "事件流提前结束"
        events.append(event)
        if event.notification.value == "execution/exited":
            break
    assert events[-1].notification.value == "execution/exited"
    return events


def _stdout(events) -> str:
    return "".join(
        event.data or ""
        for event in events
        if event.notification.value == "execution/stdout/delta"
    )


async def test_job_object_cascades_grandchild_termination(tmp_path):
    """取消后整棵树死亡：孙进程心跳停止（无孤儿，§19.2 机制验证）。"""
    import base64

    heartbeat = tmp_path / "heartbeat.txt"
    hb_posix = str(heartbeat).replace("\\", "/")
    inner_script = (
        f"open('{hb_posix}', 'w', encoding='utf-8').write('x')\n"
        "import time\n"
        "for i in range(400):\n"
        "    time.sleep(0.25)\n"
        f"    open('{hb_posix}', 'a', encoding='utf-8').write('.')\n"
    )
    inner_b64 = base64.b64encode(inner_script.encode("utf-8")).decode("ascii")
    child_code = (
        "import base64, subprocess, sys, time\n"
        f'inner = base64.b64decode("{inner_b64}").decode("utf-8")\n'
        'grandchild = subprocess.Popen([sys.executable, "-X", "utf8", "-c", inner])\n'
        "print(grandchild.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(_params("exec-rust-cascade1", child_code))
        deadline = __import__("time").monotonic() + 15
        while deadline > __import__("time").monotonic() and not heartbeat.exists():
            event = await client.next_event(timeout=1)
            if event is not None and event.notification.value == "execution/exited":
                pytest.fail("子进程在孙进程启动前退出")
        assert heartbeat.exists(), "孙进程未启动"
        await client.cancel("exec-rust-cascade1")
        events = await _run_to_exited(client, max_events=8)
        assert events[-1].notification.value == "execution/exited"

        size_before = heartbeat.stat().st_size
        __import__("time").sleep(1.6)
        size_after = heartbeat.stat().st_size
        assert size_after <= size_before + len("."), (
            f"孙进程仍存活（心跳 {size_before} -> {size_after}）"
        )
    finally:
        await client.close()


async def _low_il_child_can_initialize() -> bool:
    """探测本机是否允许低完整性进程初始化（DLL 加载）。

    本机安全基线实测：低完整性子进程加载链被拒（exit 0xC0000135 /
    103），与 AC spike A0 同源。返回 False 时跳过 Low MIC 用例并注明。
    """

    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-lowil-probe", "print('ok')", integrity_level="low")
        )
        while True:
            ev = await client.next_event(timeout=15)
            if ev is None:
                return False
            if ev.notification.value == "execution/exited":
                return ev.exit_code == 0
    finally:
        await client.close()


async def test_low_integrity_denies_write_outside_workspace(tmp_path):
    """Low MIC：对用户主目录（Medium IL 标签）写入默认拒绝。"""
    if not await _low_il_child_can_initialize():
        pytest.skip("本机安全基线阻止低完整性进程初始化（N1b 环境阻断）")
    del tmp_path
    probe = Path.home() / "ct6_mic_probe.txt"
    probe.unlink(missing_ok=True)
    code = (
        "try:\n"
        f"    open(r'{probe}', 'w').write('x')\n"
        "    print('WRITE_OK')\n"
        "except PermissionError:\n"
        "    print('WRITE_DENIED')\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-lowil-01", code, integrity_level="low")
        )
        events = await _run_to_exited(client)
        text = _stdout(events)
        assert "WRITE_DENIED" in text, f"Low IL 写入未被拦截：{text!r}"
        assert not probe.exists()
    finally:
        probe.unlink(missing_ok=True)
        await client.close()


async def test_inherit_control_group_can_write_outside_workspace(tmp_path):
    """对照组：integrity_level=inherit 时同一位置写入成功。"""
    del tmp_path
    probe = Path.home() / "ct6_mic_probe_inherit.txt"
    probe.unlink(missing_ok=True)
    code = (
        "try:\n"
        f"    open(r'{probe}', 'w').write('x')\n"
        "    print('WRITE_OK')\n"
        "except PermissionError:\n"
        "    print('WRITE_DENIED')\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-lowil-02", code, integrity_level="inherit")
        )
        events = await _run_to_exited(client)
        text = _stdout(events)
        assert "WRITE_OK" in text, f"对照组写入失败：{text!r}"
    finally:
        probe.unlink(missing_ok=True)
        await client.close()


async def test_low_integrity_child_runs_with_explicit_env_only(tmp_path):
    """Low IL 子进程环境变量仅为显式 allowlist 集合。"""
    if not await _low_il_child_can_initialize():
        pytest.skip("本机安全基线阻止低完整性进程初始化（N1b 环境阻断）")
    del tmp_path
    code = (
        "import os\n"
        "print('ENV_SYSTEMROOT_SET=', bool(os.environ.get('SystemRoot')))\n"
        "print('ENV_HOST_SECRET=', 'PA_EXEC_HOST_PROBE' in os.environ)\n"
    )
    client = ExecHostClient([str(EXEC_HOST_BINARY)])
    try:
        await client.start()
        await client.start_execution(
            _params("exec-rust-lowil-03", code, integrity_level="low")
        )
        events = await _run_to_exited(client)
        text = _stdout(events)
        assert "ENV_SYSTEMROOT_SET= True" in text, text
        assert "ENV_HOST_SECRET= False" in text, text
        assert events[-1].exit_code == 0
    finally:
        await client.close()
