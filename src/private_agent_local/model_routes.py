"""本机模型管理 API，复用现有桌面端契约。"""
from fastapi import Depends, HTTPException
from fastapi.responses import Response

from .direct_models import ConfiguredModels
from .model_catalog import (
    DiscoveryInput,
    ModelParameters,
    ProfileInput,
    ProviderInput,
    SecretInput,
)


def install_model_routes(app, cloud, local):
    @app.api_route("/providers", methods=["GET", "POST", "PUT", "DELETE"])
    @app.api_route("/providers/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    @app.api_route("/desktop/model/{path:path}", methods=["GET", "POST"])
    async def obsolete_model_api(runtime=Depends(local)):
        raise HTTPException(410, "旧模型接口已停用，请使用本机模型供应商设置")

    def service(runtime):
        if not isinstance(cloud, ConfiguredModels):
            raise HTTPException(409, "请重启客户端以使用本机供应商设置")
        return cloud.authorized(runtime.token)

    @app.get("/model-providers")
    async def providers(runtime=Depends(local)):
        catalog = service(runtime)
        return [cloud.provider_output(runtime.token, provider) for provider in catalog.data["providers"].values()]

    @app.post("/model-providers/discover/models")
    async def discover(data: DiscoveryInput, runtime=Depends(local)):
        service(runtime)
        return {"models": await cloud.discover(runtime.token, data)}

    @app.put("/model-providers/{provider_id}")
    async def upsert(provider_id: str, data: ProviderInput, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        catalog = service(runtime)
        if data.credential_reference is not None:
            raise ValueError("本机凭据引用由客户端管理，请重新保存模型设置")
        provider = catalog.upsert(provider_id, data)
        return cloud.provider_output(runtime.token, provider)

    @app.delete("/model-providers/{provider_id}", status_code=204)
    async def remove(provider_id: str, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        catalog = service(runtime)
        cloud.clear_secret(runtime.token, provider_id)
        catalog.delete(provider_id)
        return Response(status_code=204)

    @app.get("/model-providers/{provider_id}/secret-reference")
    async def reference(provider_id: str, runtime=Depends(local)):
        return service(runtime).reference(provider_id)

    @app.put("/model-providers/{provider_id}/runtime-secret")
    async def secret(provider_id: str, data: SecretInput, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        cloud.set_secret(runtime.token, provider_id, data.secret.get_secret_value())
        return {"configured": True}

    @app.delete("/model-providers/{provider_id}/runtime-secret")
    async def clear_secret(provider_id: str, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        cloud.clear_secret(runtime.token, provider_id)
        return {"configured": False}

    @app.get("/model-settings")
    async def parameters(runtime=Depends(local)):
        return ModelParameters.model_validate(service(runtime).data["parameters"])

    @app.put("/model-settings")
    async def update_parameters(data: ModelParameters, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        catalog = service(runtime)
        catalog.data["parameters"] = data.model_dump()
        catalog.save()
        return data

    @app.get("/agent-model-profiles")
    async def profiles(enabled_only: bool = False, runtime=Depends(local)):
        if not isinstance(cloud, ConfiguredModels) and getattr(cloud, "local_inference", False):
            return await cloud.profiles(runtime.token)
        service(runtime)
        return cloud.profile_list(runtime.token, enabled_only)

    @app.get("/agent-model-profiles/import-status")
    async def import_status(runtime=Depends(local)):
        service(runtime)
        return {"import_state": "not_needed", "reason_code": "local_configuration_required", "provider": None, "model_available": False}

    @app.post("/agent-model-profiles/import")
    async def import_profiles(runtime=Depends(local)):
        service(runtime)
        raise HTTPException(409, "请在本机模型设置中添加供应商；服务器密钥不会导入此电脑")

    @app.get("/agent-model-profiles/{profile_id}")
    async def get_profile(profile_id: str, runtime=Depends(local)):
        service(runtime)
        return next((p for p in cloud.profile_list(runtime.token) if p["id"] == profile_id), None) or Response(status_code=404)

    @app.put("/agent-model-profiles/{profile_id}")
    async def update_profile(profile_id: str, data: ProfileInput, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        return service(runtime).update_profile(profile_id, data)

    @app.delete("/agent-model-profiles/{profile_id}", status_code=204)
    async def remove_profile(profile_id: str, runtime=Depends(local)):
        service(runtime)
        await cloud.cancel_probes()
        catalog = service(runtime)
        profile = catalog.data["profiles"][profile_id]
        provider = catalog.provider(profile["provider_id"])
        remaining = [item for item in provider["models"] if item["profile_id"] != profile_id]
        if not remaining:
            raise HTTPException(409, "这是供应商的最后一个模型，请在供应商设置中删除供应商")
        provider["models"] = remaining
        del catalog.data["profiles"][profile_id]
        catalog.data["probes"].pop(profile_id, None)
        catalog.reconcile_default()
        catalog.save()
        return Response(status_code=204)

    @app.post("/agent-model-profiles/{profile_id}/set-default")
    async def set_default(profile_id: str, runtime=Depends(local)):
        return service(runtime).set_default(profile_id)

    @app.post("/agent-model-profiles/{profile_id}/probe")
    async def probe(profile_id: str, runtime=Depends(local)):
        service(runtime)
        selected, provider, _ = cloud.selection(runtime.token, profile_id)
        models = await cloud.discover(runtime.token, DiscoveryInput(provider_id=provider["id"], protocol=provider["protocol"], base_url=provider["base_url"]))
        exists = any(item["model_id"] in {selected["model_name"], selected["model_name"] + ":latest"} for item in models)
        return {"status": "ok" if exists else "failed", "provider_reachable": True, "model_exists": exists,
                "native_tool_calls": None, "detail": "已从本机检查模型列表，尚未验证聊天生成或工具能力"}

    @app.get("/agent-model-profiles/{profile_id}/tool-probe")
    async def tool_probe(profile_id: str, runtime=Depends(local)):
        catalog = service(runtime)
        if profile_id not in catalog.data["profiles"]:
            raise KeyError(profile_id)
        return catalog.data["probes"].get(profile_id, {"status": "none", "error_code": None, "pass_count": 0,
            "sample_count": 0, "results": None, "requirements": None, "probed_at": None})

    @app.post("/agent-model-profiles/{profile_id}/tool-probe", status_code=202)
    async def start_tool_probe(profile_id: str, runtime=Depends(local)):
        service(runtime)
        cloud.start_probe(runtime.token, profile_id)
        return {"status": "running"}
