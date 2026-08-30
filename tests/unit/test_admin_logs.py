"""Service-log security tests; no database or real service logs are used."""
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from personal_assistant.api import routes_admin_logs as routes
from personal_assistant.core.admin_logs import (
    MAX_TAIL_BYTES,
    LogSource,
    LogUnavailable,
    read_log_tail,
    redact_log,
)
from personal_assistant.core.auth import Principal


def test_tail_is_bounded_and_filters_only_redacted_lines(tmp_path):
    log = tmp_path / "service.log"
    log.write_text("first\nERROR old\nlast\nERROR latest\n", encoding="utf-8")
    result = read_log_tail(LogSource("supervisor", "Supervisor", log), lines=1, search="error")
    assert result["lines"] == ["ERROR latest"]
    assert result["truncated"]
    assert str(tmp_path) not in str(result)


def test_large_tail_drops_partial_first_line(tmp_path):
    log = tmp_path / "large.log"
    log.write_bytes(b"password=" + b"x" * (MAX_TAIL_BYTES * 2) + b"\nlast complete line\n")
    result = read_log_tail(LogSource("supervisor", "Supervisor", log))
    assert result["lines"] == ["last complete line"]
    assert result["truncated"]
    assert result["scanned_bytes"] <= MAX_TAIL_BYTES


def test_redaction_preserves_diagnostics_but_removes_credentials():
    raw = '\n'.join([
        'POST /projects HTTP/1.1 422',
        'password="fixture-password"',
        'Authorization: Bearer fixture-bearer',
        'Cookie: session=fixture-cookie',
        'GET /projects?access_code=fixture-query HTTP/1.1 200',
        'connect mysql://name:fixture-db-password@localhost/db',
        '-----BEGIN PRIVATE KEY-----', 'fixture-pem-content', '-----END PRIVATE KEY-----',
        '\x1b[31mERROR request rejected\x1b[0m',
    ])
    result = redact_log(raw)
    assert 'POST /projects HTTP/1.1 422' in result
    assert 'ERROR request rejected' in result
    for secret in ('fixture-password', 'fixture-bearer', 'fixture-cookie', 'fixture-query', 'fixture-db-password', 'fixture-pem-content'):
        assert secret not in result
    assert '\x1b' not in result
    assert 'tail-of-key' not in redact_log('tail-of-key\n-----END PRIVATE KEY-----\nnormal')


def test_missing_and_directory_are_not_read(tmp_path):
    with pytest.raises(LogUnavailable, match="未生成"):
        read_log_tail(LogSource("x", "x", tmp_path / "missing"))
    with pytest.raises(LogUnavailable, match="普通文件"):
        read_log_tail(LogSource("x", "x", tmp_path))


def test_symbolic_link_is_not_read(tmp_path):
    target = tmp_path / "target.log"
    target.write_text("do not read", encoding="utf-8")
    link = tmp_path / "link.log"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this Windows host")
    with pytest.raises(LogUnavailable, match="链接"):
        read_log_tail(LogSource("x", "x", link))


def test_resolved_path_cannot_redirect_to_another_file(tmp_path, monkeypatch):
    path = tmp_path / "configured.log"
    monkeypatch.setattr(Path, "resolve", lambda self, **kwargs: tmp_path / "elsewhere.log")
    with pytest.raises(LogUnavailable, match="链接"):
        read_log_tail(LogSource("x", "x", path))


def test_relative_configuration_is_rejected():
    with pytest.raises(LogUnavailable, match="配置不可用"):
        read_log_tail(LogSource("x", "x", Path("relative.log")))


@pytest.fixture
def client(tmp_path, monkeypatch):
    log = tmp_path / "service.log"
    log.write_text('POST /projects HTTP/1.1 422\n', encoding="utf-8")
    monkeypatch.setattr(routes, "configured_log_sources", lambda: {
        "supervisor": LogSource("supervisor", "Supervisor", log),
    })
    app = FastAPI()

    @app.middleware("http")
    async def test_identity(request: Request, call_next):
        role = request.headers.get("x-test-role")
        if role:
            request.state.principal = Principal(
                user_id=None if role == "service" else 42,
                role=role, email=None, actor_type=role,
            )
        return await call_next(request)

    app.include_router(routes.router)
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("role,expected", [(None, 401), ("user", 403), ("service", 401)])
def test_only_authenticated_admin_can_read(client, monkeypatch, role, expected):
    def must_not_read(*args, **kwargs):
        raise AssertionError("A denied request must not touch the filesystem")
    monkeypatch.setattr(routes, "configured_log_sources", must_not_read)
    headers = {"x-test-role": role} if role else {}
    assert client.get('/admin/logs', headers=headers).status_code == expected
    assert client.get('/admin/logs/supervisor', headers=headers).status_code == expected


def test_admin_reads_fixed_source_and_unknown_paths_are_rejected(client):
    headers = {"x-test-role": "admin"}
    response = client.get('/admin/logs', headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['sources'][0]['id'] == 'supervisor'
    assert 'path' not in response.json()['sources'][0]
    response = client.get('/admin/logs/supervisor?lines=20&search=422', headers=headers)
    assert response.status_code == 200
    assert response.json()['lines'] == ['POST /projects HTTP/1.1 422']
    assert client.get('/admin/logs/arbitrary-file', headers=headers).status_code == 404
    assert client.get('/admin/logs/supervisor?lines=1001', headers=headers).status_code == 422
    assert client.get('/admin/logs/supervisor?lines=0', headers=headers).status_code == 422


def test_permission_error_does_not_expose_path(client, monkeypatch):
    def deny(*args, **kwargs):
        raise LogUnavailable("服务账号没有该日志的只读权限")
    monkeypatch.setattr(routes, "read_log_tail", deny)
    response = client.get('/admin/logs/supervisor', headers={"x-test-role": "admin"})
    assert response.status_code == 503
    assert response.json()['detail'] == '服务账号没有该日志的只读权限'
