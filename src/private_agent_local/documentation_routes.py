"""受本机身份验证保护的项目文档服务设置接口。"""
from fastapi import Depends, Query
from fastapi.responses import Response

from .documentation_mcp import SelectionInput, SourceInput, VersionInput


def install_documentation_routes(app, local):
    @app.get("/projects/{project_id}/documentation-sources")
    async def sources(project_id: int, runtime=Depends(local)):
        return runtime.documentation.sources(project_id)

    @app.post("/projects/{project_id}/documentation-sources", status_code=201)
    async def create(project_id: int, data: SourceInput, runtime=Depends(local)):
        return runtime.documentation.create(project_id, data)

    @app.post("/projects/{project_id}/documentation-sources/{source_id}/discover")
    async def discover(project_id: int, source_id: str, data: VersionInput, runtime=Depends(local)):
        return await runtime.documentation.discover(project_id, source_id, data.expected_version)

    @app.put("/projects/{project_id}/documentation-sources/{source_id}/selection")
    async def select(project_id: int, source_id: str, data: SelectionInput, runtime=Depends(local)):
        return runtime.documentation.select(project_id, source_id, data)

    @app.delete("/projects/{project_id}/documentation-sources/{source_id}", status_code=204)
    async def remove(project_id: int, source_id: str, expected_version: str = Query(pattern=r"^[a-f0-9]{32}$"), runtime=Depends(local)):
        runtime.documentation.delete(project_id, source_id, expected_version)
        return Response(status_code=204)
