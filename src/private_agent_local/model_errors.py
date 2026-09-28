"""本机模型调用的安全错误与调用关联标识。"""
from contextvars import ContextVar

MODEL_CALL = ContextVar("desktop_model_call", default=None)

MODEL_ERROR_MESSAGES = {
    "not_configured": "尚未配置默认模型，请在模型设置中选择并启用模型",
    "invalid_configuration": "本机模型配置无效，请检查模型服务地址和参数",
    "missing_api_key": "此电脑未配置 API Key，请在模型配置中重新保存密钥",
    "unauthorized": "模型供应商认证失败，请检查 API Key 和模型访问权限",
    "model_not_found": "模型供应商未找到所选模型，请检查模型名称和服务地址",
    "unsupported_capability": "所选模型不可用或不支持当前能力，请检查模型配置",
    "provider_rejected_request": "模型供应商拒绝请求，请检查模型能力、工具参数和推理强度配置",
    "rate_limited": "模型供应商请求限额已达到，请检查配额或稍后重试",
    "network_error": "此电脑无法连接模型供应商，请检查模型服务地址和本机网络",
    "provider_unavailable": "模型供应商暂不可用，请稍后重试",
    "timeout": "模型服务响应超时，请稍后重试",
    "invalid_response": "模型供应商响应格式无效，请检查模型接口兼容性",
    "incomplete_response": "模型响应被截断或未完整结束，未执行其中的工具请求；请检查输出预算或供应商状态",
    "provider_error": "模型调用失败，请检查供应商服务状态",
}


class CloudError(Exception):
    def __init__(self, status: int, message: str, *, code: str = "model_unavailable"):
        super().__init__(message)
        self.status = status
        self.code = code

