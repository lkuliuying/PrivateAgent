"""本机供应商连接的响应大小边界。"""
from contextvars import ContextVar

import httpx

from private_agent_core.llm.contracts import ModelGatewayError

MODEL_ACCOUNTING = ContextVar("direct_model_accounting", default=None)


class BoundedStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        try:
            async for chunk in self.stream:
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ModelGatewayError("模型响应超过大小限制", code="invalid_response", provider="local")
                yield chunk
        except httpx.TimeoutException:
            raise
        except (httpx.ReadError, httpx.RemoteProtocolError):
            raise ModelGatewayError("模型响应连接中断", code="stream_interrupted", provider="local") from None

    async def aclose(self):
        await self.stream.aclose()


class BoundedTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        accounting = MODEL_ACCOUNTING.get()
        if accounting is not None:
            if accounting["provider_requests"]:
                raise ModelGatewayError("同一模型调用不得重放供应商请求", code="protocol_error", provider="local")
            accounting["provider_requests"] += 1
            request.headers["X-Model-Call-Id"] = accounting["call_id"]
        response = await self.transport.handle_async_request(request)
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            await response.aclose()
            raise ModelGatewayError("模型接口必须返回未压缩的有界响应", code="invalid_response", provider="local")
        if response.is_stream_consumed:
            if len(response.content) > 2 * 1024 * 1024:
                raise ModelGatewayError("模型响应超过大小限制", code="invalid_response", provider="local")
        else:
            response.stream = BoundedStream(response.stream)
        return response

    async def aclose(self):
        await self.transport.aclose()
