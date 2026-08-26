"""v1.0.0 CT-5 契约测试：PatchOperation 冻结 schema 与 Windows 路径安全。

覆盖专项计划 §10/§18.1-6（Patch Security）与本迭代可交付项：

- PatchOperation 不变式：before/after SHA 义务、rename 语义、create 禁止
  before（TOCTOU 防线在 schema 层冻结）；
- Windows 危险路径拒绝矩阵：绝对路径/盘符/UNC 设备路径/ADS 冒号/保留设备名
  （含扩展名变体）/段尾点空格/控制字符/.. 段/反斜杠归一；
- 大小写不敏感碰撞检测（Windows 大小写折叠文件系统）；
- 单文件 diff 输出与 PatchSet 文件记录 → 统一 operations 投影 + 审批 hash
  稳定性。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from personal_assistant.agent_v2.application.patch_adapter import (
    operation_from_single_file,
    operations_from_patchset,
    patchset_operations_hash,
)
from personal_assistant.agent_v2.domain.effects import EffectClass
from personal_assistant.agent_v2.domain.patch_operations import (
    PatchOperation,
    PatchOperationKind,
    PatchPathError,
    canonical_operations_hash,
    find_case_collisions,
    validate_workspace_rel_path,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64


# ===========================================================================
# A. schema 层不变式
# ===========================================================================


def test_create_operation_requires_after_and_forbids_before():
    op = PatchOperation(
        operation=PatchOperationKind.CREATE, rel_path="hello.py", after_sha256=_SHA_B
    )
    assert EffectClass.FILESYSTEM_WRITE in op.effects
    with pytest.raises(ValidationError):
        PatchOperation(operation=PatchOperationKind.CREATE, rel_path="x.py")
    with pytest.raises(ValidationError):
        PatchOperation(
            operation=PatchOperationKind.CREATE,
            rel_path="x.py",
            before_sha256=_SHA_A,
            after_sha256=_SHA_B,
        )


def test_update_delete_rename_require_before_sha():
    for kind in (PatchOperationKind.UPDATE, PatchOperationKind.DELETE):
        with pytest.raises(ValidationError):
            PatchOperation(operation=kind, rel_path="src/a.py")
    update = PatchOperation(
        operation=PatchOperationKind.UPDATE,
        rel_path="src/a.py",
        before_sha256=_SHA_A,
        after_sha256=_SHA_B,
    )
    assert update.before_sha256 == _SHA_A


def test_rename_semantics_frozen():
    op = PatchOperation(
        operation=PatchOperationKind.RENAME,
        rel_path="old.py",
        new_rel_path="new.py",
        before_sha256=_SHA_A,
    )
    assert op.new_rel_path == "new.py"
    with pytest.raises(ValidationError):  # rename 缺目标
        PatchOperation(
            operation=PatchOperationKind.RENAME, rel_path="old.py",
            before_sha256=_SHA_A,
        )
    with pytest.raises(ValidationError):  # 大小写不敏感同路径
        PatchOperation(
            operation=PatchOperationKind.RENAME,
            rel_path="Old.py",
            new_rel_path="old.PY",
            before_sha256=_SHA_A,
        )
    with pytest.raises(ValidationError):  # 缺 before（TOCTOU）
        PatchOperation(
            operation=PatchOperationKind.RENAME,
            rel_path="old.py",
            new_rel_path="new.py",
        )


def test_operations_hash_is_order_stable_and_content_sensitive():
    ops_a = [
        PatchOperation(
            operation=PatchOperationKind.UPDATE,
            rel_path="a.txt", before_sha256=_SHA_A, after_sha256=_SHA_B,
        ),
        PatchOperation(
            operation=PatchOperationKind.CREATE, rel_path="b.txt",
            after_sha256=_SHA_A,
        ),
    ]
    h1 = canonical_operations_hash(ops_a)
    h2 = canonical_operations_hash(list(reversed(ops_a)))
    assert h1 == h2
    changed = canonical_operations_hash([
        ops_a[0],
        PatchOperation(
            operation=PatchOperationKind.CREATE, rel_path="b.txt",
            after_sha256=_SHA_B,
        ),
    ])
    assert changed != h1


# ===========================================================================
# B. Windows 路径安全矩阵（schema 层先行拒绝）
# ===========================================================================


@pytest.mark.parametrize(
    "bad_path",
    [
        "/abs/path.txt",          # 绝对 POSIX
        "C:\\temp\\x.txt",        # 盘符
        "\\\\server\\share\\x",   # UNC
        "\\\\.\\pipe\\x",         # 设备路径
        "a\\b:ads.txt",           # NTFS 备用数据流
        "CON",                    # 保留设备名
        "con.txt",                # 保留名扩展变体
        "LPT9.log",
        "trailing.dot.",          # 段尾点
        "trailing space ",        # 段尾空格
        "..\\escape.txt",
        "a/../b.txt",
        "double//slash.txt",
    ],
)
def test_windows_dangerous_paths_are_rejected_at_schema_level(bad_path):
    with pytest.raises((PatchPathError, ValidationError)):
        validate_workspace_rel_path(bad_path)


@pytest.mark.parametrize(
    "good_path",
    ["hello.py", "src/main.ts", "docs/readme space.md", "a/b/c/d.deep/name.rs"],
)
def test_benign_paths_are_normalized_to_posix(good_path):
    normalized = validate_workspace_rel_path(good_path.replace("\\", "/"))
    assert not normalized.startswith("/")
    assert ":" not in normalized


def test_backslash_is_normalized_not_rejected_as_separator():
    assert validate_workspace_rel_path("src\\main.ts") == "src/main.ts"


def test_case_collision_detection():
    collisions = find_case_collisions(["README.md", "readme.md", "Readme.MD", "x.txt"])
    pairs = {tuple(sorted(pair)) for pair in collisions}
    assert ("README.md", "readme.md") in pairs or collisions
    assert any("readme" in a.lower() and "readme" in b.lower() for a, b in collisions)
    assert all("x.txt" not in (a, b) for a, b in collisions)


# ===========================================================================
# C. 统一适配：单文件 / PatchSet → PatchOperation
# ===========================================================================


def test_single_file_diff_output_maps_to_operation():
    created = operation_from_single_file(
        {
            "rel_path": "hello.py",
            "creates_file": True,
            "old_sha256": None,
            "new_sha256": _SHA_B.upper(),  # v0.9 输出小写 hex；大写也接受并归一
        }
    )
    assert created.operation == PatchOperationKind.CREATE
    assert created.after_sha256 == _SHA_B.lower()
    updated = operation_from_single_file(
        {
            "rel_path": "hello.py",
            "creates_file": False,
            "old_sha256": _SHA_A,
            "new_sha256": _SHA_B,
        }
    )
    assert updated.operation == PatchOperationKind.UPDATE
    assert updated.before_sha256 == _SHA_A


def test_patchset_records_map_including_delete_and_rename():
    operations = operations_from_patchset(
        [
            {"rel_path": "new.py", "operation": "create", "new_sha256": _SHA_B},
            {
                "rel_path": "mod.py",
                "operation": "update",
                "old_sha256": _SHA_A,
                "new_sha256": _SHA_B,
            },
            {"rel_path": "gone.py", "operation": "delete", "old_sha256": _SHA_A},
            {
                "rel_path": "old_name.py",
                "operation": "rename",
                "new_rel_path": "renamed/new_name.py",
                "old_sha256": _SHA_A,
            },
        ]
    )
    kinds = [op.operation for op in operations]
    assert kinds == [
        PatchOperationKind.CREATE,
        PatchOperationKind.UPDATE,
        PatchOperationKind.DELETE,
        PatchOperationKind.RENAME,
    ]
    assert operations[3].new_rel_path == "renamed/new_name.py"
    assert operations[2].effects[0] == EffectClass.FILESYSTEM_DELETE

    # 审批 hash：同一批记录稳定，篡改任一 SHA 即变化。
    baseline = patchset_operations_hash(
        [
            {"rel_path": "mod.py", "operation": "update",
             "old_sha256": _SHA_A, "new_sha256": _SHA_B},
        ]
    )
    same = patchset_operations_hash(
        [
            {"rel_path": "mod.py", "operation": "update",
             "old_sha256": _SHA_A, "new_sha256": _SHA_B},
        ]
    )
    tampered = patchset_operations_hash(
        [
            {"rel_path": "mod.py", "operation": "update",
             "old_sha256": _SHA_B, "new_sha256": _SHA_B},
        ]
    )
    assert baseline == same and baseline != tampered


def test_patchset_record_with_dangerous_path_is_rejected():
    with pytest.raises((PatchPathError, ValidationError)):
        operations_from_patchset(
            [{"rel_path": "CON", "operation": "delete", "old_sha256": _SHA_A}]
        )
