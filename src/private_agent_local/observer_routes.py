"""完成检查设置与只读运行诊断均复用本机身份边界。"""
from fastapi import Depends

from .observer import ObserverConfigInput


def install_observer_routes(app, local):
    @app.get("/projects/{project_id}/observer-config")
    async def config(project_id: int, runtime=Depends(local)):
        return runtime.observer.config(project_id)

    @app.put("/projects/{project_id}/observer-config")
    async def save(project_id: int, data: ObserverConfigInput, runtime=Depends(local)):
        return runtime.observer.save(project_id, data)

    @app.get("/agent-runs/{run_id}/observer")
    async def report(run_id: str, runtime=Depends(local)):
        return runtime.observer.report(run_id)
