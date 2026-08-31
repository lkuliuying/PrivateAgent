"""用真实 SQLAlchemy 查询与内存 SQLite 验证租户过滤，不连接 MySQL。"""
import json

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_local_history import AUTHORITY, archive_fixture

from personal_assistant.api import routes_desktop_history as routes
from personal_assistant.core.auth import Principal
from private_agent_core.history import FIELDS


class IsolatedDatabase:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:")
        records = archive_fixture()["records"]
        with self.engine.begin() as connection:
            for kind, entity in routes.ENTITIES.items():
                names = [name for name in FIELDS[kind] if hasattr(entity, name)] + ["owner_user_id"]
                definitions = []
                for name in names:
                    scalar = getattr(entity, name).property.columns[0].type.python_type
                    definitions.append(f'"{name}" ' + ("INTEGER" if scalar is int else "TEXT"))
                connection.exec_driver_sql(f'CREATE TABLE "{entity.__tablename__}" ({", ".join(definitions)})')
                rows = records[kind]
                if kind == "projects":
                    rows = [*rows, {"id": 2, "name": "不可导出的其他账号", "owner_user_id": 8}, {"id": 3, "name": "未归属历史", "owner_user_id": None}]
                for row in rows:
                    values = {**row, "owner_user_id": row.get("owner_user_id", 7)}
                    keys = [key for key in values if key in names]
                    parameters = tuple(json.dumps(values[k], ensure_ascii=False) if isinstance(values[k], (dict, list)) else values[k] for k in keys)
                    columns = ",".join(f'"{key}"' for key in keys)
                    connection.exec_driver_sql(f'INSERT INTO "{entity.__tablename__}" ({columns}) VALUES ({",".join("?" for _ in keys)})', parameters)
        self.session = Session(self.engine)
        self.queries = []

    async def execute(self, query):
        self.queries.append(str(query))
        return self.session.execute(query)

    def close(self):
        self.session.close()
        self.engine.dispose()


@pytest.mark.asyncio
async def test_export_filters_every_entity_and_keeps_task_run_distinction():
    database = IsolatedDatabase()
    try:
        payload = json.loads(await routes.export_history(database, 7, AUTHORITY))
        assert [row["id"] for row in payload["records"]["projects"]] == [1]
        assert payload["records"]["agent_tasks"][0]["goal"] == "不是一次运行"
        assert payload["records"]["runs"][0]["id"] == "old-run"
        assert len(database.queries) == len(FIELDS)
        for query in database.queries:
            assert "owner_user_id =" in query
            assert "approval_token_sha256" not in query and "claim_token_sha256" not in query
        assert "不可导出" not in json.dumps(payload, ensure_ascii=False)
    finally:
        database.close()


@pytest.mark.asyncio
async def test_history_endpoint_requires_identity_and_returns_download():
    database = IsolatedDatabase()
    app = FastAPI()
    @app.middleware("http")
    async def identity(request, call_next):
        if request.headers.get("authorization") == "Bearer fixture":
            request.state.principal = Principal(user_id=7, role="user", email="fixture@example.test", actor_type="user")
        return await call_next(request)
    async def isolated():
        yield database
    app.dependency_overrides[routes.get_session] = isolated
    app.include_router(routes.router)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=AUTHORITY) as client:
            assert (await client.get("/desktop/history/export")).status_code == 401
            assert not database.queries
            response = await client.get("/desktop/history/export", headers={"authorization": "Bearer fixture"})
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert "attachment" in response.headers["content-disposition"]
            assert response.json()["source"] == {"authority": AUTHORITY, "owner_id": 7}
    finally:
        database.close()
