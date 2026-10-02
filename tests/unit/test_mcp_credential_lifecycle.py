"""配置状态与系统凭据生命周期的隔离并发回归；凭据宿主只用内存替身。"""
import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from private_agent_local.integration_mcp import Integrations
from private_agent_local.mcp_credentials import McpCredentialError
from private_agent_local.mcp_library import PrepareInput, SourceInput
from private_agent_local.model_errors import CloudError
from private_agent_local.secret_filter import SecretFilter
from private_agent_local.store import Store


class Vault:
    persistent = True

    def __init__(self):
        self.values = {}
        self.fail_delete = False
        self.delete_entered = asyncio.Event()
        self.delete_release = None
        self.get_entered = asyncio.Event()
        self.get_release = None
        self.deleted = []

    async def binding(self, service_id, version, slot):
        return {"identity": "a" * 64, "service_id": service_id, "version": version, "slot": slot}

    async def get(self, *key):
        self.get_entered.set()
        if self.get_release is not None:
            await self.get_release.wait()
        return self.values.get(key)

    async def delete(self, *key):
        self.delete_entered.set()
        if self.delete_release is not None:
            await self.delete_release.wait()
        if self.fail_delete:
            raise McpCredentialError("credential_store_failed")
        self.deleted.append(key)
        self.values.pop(key, None)


@pytest.fixture
def state(tmp_path):
    owner = SimpleNamespace(store=Store(tmp_path / "state.sqlite3"), secret_filter=SecretFilter(), mcp_credentials=Vault())
    owner.integrations = Integrations(owner)
    try:
        yield owner, owner.integrations.library, owner.mcp_credentials
    finally:
        owner.store.db.close()


def configuration(*, name="服务", url="https://example.test/mcp", auth_mode="bearer", oauth_persistence="persistent"):
    return SourceInput(name=name, transport="https", url=url, auth_mode=auth_mode, oauth_persistence=oauth_persistence)


async def prepared(library, service=None, *, config=None, replace=False):
    return await library.prepare(PrepareInput(request_id=uuid.uuid4().hex, configuration=config or configuration(),
        service_id=service["id"] if service else None, expected_version=service["version"] if service else None,
        replace_credentials=replace))


def save(vault, change, value="synthetic-lifecycle-value"):
    key = (change["service_id"], change["credential_revision"], "static")
    vault.values[key] = json.dumps({"bearer": value})
    return f"secret://os-keyring/mcp/{'a' * 64}/{key[0]}/{key[1]}/static"


async def active(library, vault):
    change = await prepared(library)
    return await library.commit(change["id"], save(vault, change))


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["identity", "service", "revision", "slot"])
async def test_commit_rejects_cross_scope_reference_without_changing_active_configuration(state, dimension):
    _, library, vault = state
    service = await active(library, vault)
    change = await prepared(library, service, replace=True)
    save(vault, change)
    parts = {"identity": "a" * 64, "service": service["id"], "revision": change["credential_revision"], "slot": "static"}
    parts[dimension] = "oauth" if dimension == "slot" else "b" * (64 if dimension == "identity" else 32)
    reference = "secret://os-keyring/mcp/{identity}/{service}/{revision}/{slot}".format(**parts)
    with pytest.raises(CloudError, match="引用与待保存配置不匹配"):
        await library.commit(change["id"], reference)
    assert library.service(service["id"])["version"] == service["version"]
    assert library.change(change["id"])["status"] == "prepared"


@pytest.mark.asyncio
async def test_discard_blocks_commit_and_cleanup_failure_survives_reopen(state):
    owner, library, vault = state
    change = await prepared(library)
    reference = save(vault, change)
    vault.fail_delete = True
    result = await library.discard(change["id"])
    assert result == {"discarded": True, "cleanup_pending": True}
    assert library.cleanup_pending() and vault.values
    with pytest.raises(CloudError, match="已放弃"):
        await library.commit(change["id"], reference)
    path = owner.store.path
    owner.store.db.close()
    owner.store = Store(path)
    owner.integrations = Integrations(owner)
    assert owner.integrations.library.cleanup_pending()
    vault.fail_delete = False
    assert await owner.integrations.library.cleanup() == {"credential_cleanup_pending": []}
    assert vault.values == {}


@pytest.mark.asyncio
async def test_inflight_commit_cannot_be_reported_as_successfully_discarded(state):
    _, library, vault = state
    change = await prepared(library)
    reference = save(vault, change)
    vault.get_release = asyncio.Event()
    commit = asyncio.create_task(library.commit(change["id"], reference))
    await asyncio.wait_for(vault.get_entered.wait(), 1)
    discard = asyncio.create_task(library.discard(change["id"]))
    await asyncio.sleep(0)
    assert not discard.done()
    vault.get_release.set()
    service = await asyncio.wait_for(commit, 1)
    with pytest.raises(CloudError, match="已生效"):
        await asyncio.wait_for(discard, 1)
    assert library.change(change["id"])["status"] == "completed"
    assert library.service(service["id"])["version"] == service["version"]
    assert len(vault.values) == 1


@pytest.mark.asyncio
async def test_cancelled_commit_then_discard_cleans_native_draft(state):
    _, library, vault = state
    change = await prepared(library)
    reference = save(vault, change)
    vault.get_release = asyncio.Event()
    commit = asyncio.create_task(library.commit(change["id"], reference))
    await asyncio.wait_for(vault.get_entered.wait(), 1)
    commit.cancel()
    with pytest.raises(asyncio.CancelledError):
        await commit
    assert await library.discard(change["id"]) == {"discarded": True, "cleanup_pending": False}
    assert not vault.values and not library.services()


@pytest.mark.asyncio
async def test_replacement_cleans_only_unreferenced_revision_and_keeps_new_config_on_cleanup_failure(state):
    _, library, vault = state
    service = await active(library, vault)
    old_key = (service["id"], service["credential_revision"], "static")
    shared = await prepared(library, service, config=configuration(name="未提交的重命名"))
    replacement = await prepared(library, service, replace=True)
    replaced = await library.commit(replacement["id"], save(vault, replacement, "synthetic-replacement"))
    assert old_key in vault.values and not replaced["cleanup_pending"]
    vault.fail_delete = True
    assert (await library.discard(shared["id"]))["cleanup_pending"]
    assert library.service(service["id"])["version"] == replaced["version"]
    vault.fail_delete = False
    await library.cleanup()
    assert old_key not in vault.values
    assert (service["id"], replaced["credential_revision"], "static") in vault.values
    assert not library.cleanup_pending()


@pytest.mark.asyncio
async def test_discard_of_shared_active_revision_never_erases_active_secret(state):
    _, library, vault = state
    service = await active(library, vault)
    change = await prepared(library, service, config=configuration(name="重命名"))
    assert change["credential_revision"] == service["credential_revision"]
    await library.discard(change["id"])
    assert not vault.deleted and len(vault.values) == 1
    assert library.service(service["id"])["version"] == service["version"]


@pytest.mark.asyncio
async def test_delete_serializes_prepare_and_refuses_new_project_binding(state):
    owner, library, vault = state
    service = await active(library, vault)
    vault.delete_release = asyncio.Event()
    delete = asyncio.create_task(library.delete(service["id"], service["version"]))
    await asyncio.wait_for(vault.delete_entered.wait(), 1)
    update = asyncio.create_task(prepared(library, service, config=configuration(name="并发修改")))
    await asyncio.sleep(0)
    assert not update.done()
    project = owner.store.create("project", {"name": "项目", "root_path": str(owner.store.path.parent)})
    with pytest.raises(CloudError, match="正在连接或修改"):
        library.bind(project["id"], service["id"])
    vault.delete_release.set()
    assert await asyncio.wait_for(delete, 1) == {"deleted": True, "cleanup_pending": False}
    with pytest.raises(KeyError):
        await asyncio.wait_for(update, 1)
    assert not library.services() and not vault.values and not library.cleanup_pending()


@pytest.mark.asyncio
async def test_changed_oauth_target_drops_auth_revision_and_clears_old_tokens(state):
    owner, library, vault = state
    service = library.create(configuration(auth_mode="oauth"))
    key = (service["id"], service["auth_revision"], "oauth")
    vault.values[key] = "synthetic-oauth-bundle"
    owner.integrations.tokens[service["id"]] = object()
    change = await prepared(library, service, config=configuration(url="https://other.example.test/mcp", auth_mode="oauth"))
    replaced = await library.commit(change["id"], None)
    assert replaced["auth_revision"] != service["auth_revision"]
    assert key not in vault.values and service["id"] not in owner.integrations.tokens
    assert not replaced["cleanup_pending"]


@pytest.mark.asyncio
async def test_http_cleanup_drops_session_copy_but_keeps_persistent_erase_journal(state):
    _, library, vault = state
    service = library.create(configuration(auth_mode="oauth"))
    key = (service["id"], service["auth_revision"], "oauth")
    vault.values[key] = "synthetic-session-copy"
    vault.persistent = False
    assert (await library.delete(service["id"], service["version"]))["cleanup_pending"]
    assert not vault.values and library.cleanup_pending()
    vault.persistent = True
    assert await library.cleanup() == {"credential_cleanup_pending": []}


@pytest.mark.asyncio
async def test_logout_cleans_oauth_even_with_a_prepared_rename_and_preserves_failure_journal(state):
    owner, library, vault = state
    service = library.create(configuration(auth_mode="oauth"))
    key = (service["id"], service["auth_revision"], "oauth")
    vault.values[key] = "synthetic-old-login"
    owner.integrations.tokens[service["id"]] = object()
    change = await prepared(library, service, config=configuration(name="重命名", auth_mode="oauth"))
    vault.fail_delete = True
    assert await owner.integrations.logout(service["id"], service["version"]) == {"logged_out": True, "cleanup_pending": True}
    assert service["id"] not in owner.integrations.tokens
    assert library.service(service["id"])["auth_revision"] != service["auth_revision"]
    with pytest.raises(CloudError):
        await library.commit(change["id"], None)
    vault.fail_delete = False
    await library.cleanup()
    assert key not in vault.values and not library.cleanup_pending()


@pytest.mark.asyncio
async def test_cleanup_cancellation_keeps_retryable_journal(state):
    _, library, vault = state
    change = await prepared(library)
    save(vault, change)
    vault.delete_release = asyncio.Event()
    discard = asyncio.create_task(library.discard(change["id"]))
    await asyncio.wait_for(vault.delete_entered.wait(), 1)
    discard.cancel()
    with pytest.raises(asyncio.CancelledError):
        await discard
    assert library.change(change["id"])["status"] == "discarded"
    assert library.cleanup_pending()
    vault.delete_release.set()
    await library.cleanup()
    assert not vault.values and not library.cleanup_pending()
