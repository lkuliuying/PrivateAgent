"""共享的模型工具能力条件。"""
from pydantic import BaseModel, ConfigDict


class ModelRequirements(BaseModel):
    """模型能力条件（§7.1 model_requirements）。未知能力失败关闭：
    默认仅要求 function calling；freeform patch/vision/并行显式声明。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    function_calling: bool = True
    freeform_patch: bool = False
    vision: bool = False
    parallel_tool_calls: bool = False

