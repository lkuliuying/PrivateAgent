"""v0.6.0 C1-3 迁移验证：升级回填 + 中断重跑幂等 + 结构检查。

流程（仅操作临时库 personal_assistant_test_v060_alpha1，不触碰主库）：
1. 空库 upgrade 到 0026（历史基线），插入旧项目 p1；
2. upgrade head：0027 升级回填为 p1 补建 root workspace，0028 建表；
3. 结构检查（表/列/索引齐全）；
4. 插入升级后新增项目 p2（v060-mig-test）；
5. 模拟 0027 中断（alembic_version 回退 0026）→ upgrade head 重跑：
   DDL 幂等跳过、p1 不重复、p2 被补插；
6. 模拟 0028 中断（alembic_version 回退 0027）→ upgrade head 重跑：幂等；
7. 验证每个项目恰好 1 个 root workspace、无重复 (project_id, root_path_sha256)。

正式应用回退不执行 downgrade（本脚本不做破坏性 downgrade 验证）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

PROJECT_ROOT = __file__.rsplit("scripts", 1)[0]


def _base_url() -> str:
    line = open(f"{PROJECT_ROOT}.env", encoding="utf-8").read()
    m = re.search(r"^PA_DB_URL=(.+)$", line, re.M)
    if not m:
        raise SystemExit("PA_DB_URL not found in .env")
    return m.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-name", default="personal_assistant_test_v060_alpha1")
    parser.add_argument("--keep", action="store_true", help="验证后保留临时库")
    args = parser.parse_args()

    base = _base_url()
    server_url = base.replace("aiomysql", "pymysql")
    db_name = args.db_name
    target_url_async = base.rsplit("/", 1)[0] + f"/{db_name}"
    target_url = server_url.rsplit("/", 1)[0] + f"/{db_name}"

    sync = create_engine(server_url.rsplit("/", 1)[0], isolation_level="AUTOCOMMIT")
    with sync.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{db_name}`"))
        conn.execute(
            text(
                f"CREATE DATABASE `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    sync.dispose()

    cfg = Config(f"{PROJECT_ROOT}alembic.ini")

    # alembic env.py 会用 personal_assistant.config.settings.db_url 覆盖
    # alembic.ini 的 URL；必须在进程内把 settings.db_url 指向目标临时库，
    # 否则迁移会落到主库（历史事故：一次脚本误把主库升到 0027）。
    # 注意保留 async driver（aiomysql），env.py 用 async engine。
    import personal_assistant.config as pa_config

    pa_config.settings.db_url = target_url_async

    issues: list[str] = []

    # 1) 空库升级到 0026（历史基线），插入旧项目 p1
    command.upgrade(cfg, "0026")
    engine = create_engine(target_url)
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO projects (name, root_path, status, created_at, updated_at) "
                 "VALUES ('v060-p1', '/tmp/v060-p1', 'active', NOW(3), NOW(3))")
        )
        conn.commit()
    engine.dispose()

    # 2) 升级 head：0027 回填 p1 + 0028 建表
    command.upgrade(cfg, "head")
    engine = create_engine(target_url)
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT table_name FROM information_schema.tables "
                     "WHERE table_schema = :db"),
                {"db": db_name},
            )
        }
        ws_columns = {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema = :db AND table_name = 'project_workspaces'"),
                {"db": db_name},
            )
        }
        run_columns = {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema = :db AND table_name = 'agent_runs'"),
                {"db": db_name},
            )
        }
        sess_columns = {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_schema = :db AND table_name = 'sessions'"),
                {"db": db_name},
            )
        }
        p1_ws = conn.execute(
            text("SELECT COUNT(*) FROM project_workspaces "
                 "WHERE project_id = (SELECT id FROM projects WHERE name = 'v060-p1')")
        ).scalar()
    engine.dispose()

    if version != "0028":
        issues.append(f"expected head 0028, found {version}")
    for required in ("project_workspaces", "run_plan_items", "agent_run_artifacts"):
        if required not in tables:
            issues.append(f"missing table: {required}")
    for col in ("id", "project_id", "kind", "root_path", "root_path_sha256",
                "status", "last_used_at"):
        if col not in ws_columns:
            issues.append(f"project_workspaces missing column: {col}")
    for col in ("project_id", "workspace_id", "base_head_sha", "model_profile_id",
                "reasoning_effort", "permission_snapshot_json", "client_request_id"):
        if col not in run_columns:
            issues.append(f"agent_runs missing column: {col}")
    for col in ("project_id", "workspace_id", "kind", "last_run_id",
                "pinned_at", "archived_at"):
        if col not in sess_columns:
            issues.append(f"sessions missing column: {col}")
    if p1_ws != 1:
        issues.append(f"upgrade backfill created {p1_ws} root workspaces for p1 (expected 1)")

    # 3) 模拟 0027 中断：插入升级后新增项目 p2，把 version 回退到 0026 后重跑 head
    engine = create_engine(target_url)
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO projects (name, root_path, status, created_at, updated_at) "
                 "VALUES ('v060-mig-test', '/tmp/v060-mig-test', 'active', NOW(3), NOW(3))")
        )
        conn.execute(text("UPDATE alembic_version SET version_num = '0026'"))
        conn.commit()
    engine.dispose()
    command.upgrade(cfg, "head")

    # 4) 模拟 0028 中断：version 回退到 0027 后重跑 head
    engine = create_engine(target_url)
    with engine.connect() as conn:
        conn.execute(text("UPDATE alembic_version SET version_num = '0027'"))
        conn.commit()
    engine.dispose()
    command.upgrade(cfg, "head")

    # 5) 终态验证
    engine = create_engine(target_url)
    with engine.connect() as conn:
        version_final = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar()
        per_project = conn.execute(
            text("SELECT COUNT(*) FROM (SELECT project_id FROM project_workspaces "
                 "WHERE kind = 'root' GROUP BY project_id HAVING COUNT(*) > 1) t")
        ).scalar()
        missing = conn.execute(
            text("SELECT COUNT(*) FROM projects p WHERE p.root_path IS NOT NULL "
                 "AND p.root_path <> '' AND NOT EXISTS "
                 "(SELECT 1 FROM project_workspaces w "
                 "WHERE w.project_id = p.id AND w.kind = 'root')")
        ).scalar()
        dup_sha = conn.execute(
            text("SELECT COUNT(*) FROM (SELECT project_id, root_path_sha256 "
                 "FROM project_workspaces GROUP BY project_id, root_path_sha256 "
                 "HAVING COUNT(*) > 1) t")
        ).scalar()
        p2_ws = conn.execute(
            text("SELECT COUNT(*) FROM project_workspaces "
                 "WHERE project_id = (SELECT id FROM projects WHERE name = 'v060-mig-test')")
        ).scalar()
        p1_ws_final = conn.execute(
            text("SELECT COUNT(*) FROM project_workspaces "
                 "WHERE project_id = (SELECT id FROM projects WHERE name = 'v060-p1')")
        ).scalar()
    engine.dispose()

    if version_final != "0028":
        issues.append(f"final version {version_final} != 0028")
    if per_project != 0:
        issues.append(f"{per_project} projects have >1 root workspace")
    if missing != 0:
        issues.append(f"{missing} projects missing root workspace after re-run")
    if dup_sha != 0:
        issues.append(f"duplicate (project_id, root_path_sha256): {dup_sha}")
    if p2_ws != 1:
        issues.append(f"re-run created {p2_ws} root workspaces for new project (expected 1)")
    if p1_ws_final != 1:
        issues.append(f"re-run changed p1 root workspace count to {p1_ws_final} (expected 1)")

    if not args.keep:
        sync = create_engine(server_url.rsplit("/", 1)[0], isolation_level="AUTOCOMMIT")
        with sync.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS `{db_name}`"))
        sync.dispose()

    result = {
        "verified": not issues,
        "schema_head": version_final,
        "tables": sorted(
            t for t in tables
            if t.startswith(("project_workspaces", "run_plan", "agent_run_artifacts"))
        ),
        "upgrade_backfill_p1": p1_ws,
        "rerun_new_project_p2": p2_ws,
        "rerun_existing_p1": p1_ws_final,
        "projects_with_dup_root": per_project,
        "projects_missing_root": missing,
        "duplicate_path_sha": dup_sha,
        "issues": issues,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
