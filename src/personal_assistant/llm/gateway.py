"""Timeout, retry, metadata and error normalization for model adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import ValidationError

from personal_assistant.agents.contracts import ModelRequest, ModelResponse
from personal_assistant.agents.runtime import CancellationToken

from .contracts import ModelCapabilities, ModelGatewayError, RetryPolicy


class ModelAdapter(Protocol):
    provider_name: str
    model_name: str
    capabilities: ModelCapabilities

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse: ...


ModelOutputSink = Callable[[str], Awaitable[None]]


class StreamingModelAdapter(ModelAdapter, Protocol):
    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
        on_delta: ModelOutputSink,
    ) -> ModelResponse: ...


_RETRYABLE_CODES = {"network_error", "rate_limited", "provider_unavailable", "timeout"}


class _ModelOutputSinkError(Exception):
    pass


def _safe_http_error_detail(response: httpx.Response) -> str:
    """Extract a bounded provider code/message without retaining response bodies."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return f"HTTP {response.status_code}"
    if not isinstance(payload, dict):
        return f"HTTP {response.status_code}"
    error = payload.get("error")
    source = error if isinstance(error, dict) else payload
    code = str(source.get("code") or "").strip().replace("\r", " ").replace("\n", " ")
    message = (
        str(source.get("message") or source.get("detail") or "")
        .strip()
        .replace("\r", " ")
        .replace("\n", " ")
    )
    parts = [f"HTTP {response.status_code}"]
    if code:
        parts.append(code[:64])
    if message:
        parts.append(message[:300])
    return " · ".join(parts)


def _normalize_error(exc: Exception, provider: str) -> ModelGatewayError:
    if isinstance(exc, ModelGatewayError):
        return exc
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        code = "timeout"
    elif isinstance(exc, httpx.ConnectError):
        code = "network_error"
    elif isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {401, 403}:
            code = "unauthorized"
        elif status == 429:
            code = "rate_limited"
        elif status == 404:
            code = "model_not_found"
        elif status >= 500:
            code = "provider_unavailable"
        else:
            code = "provider_rejected_request"
    elif isinstance(exc, (KeyError, TypeError, ValueError, ValidationError)):
        code = "invalid_response"
    else:
        code = "provider_error"
    detail = (
        _safe_http_error_detail(exc.response)
        if isinstance(exc, httpx.HTTPStatusError)
        else None
    )
    message = f"模型调用失败（{code}）"
    if detail:
        message = f"{message}：{detail}"
    return ModelGatewayError(
        message,
        code=code,
        provider=provider,
    )


class ModelGateway:
    """A ModelClient implementation with bounded retries and request timeout."""

    def __init__(
        self,
        adapter: ModelAdapter,
        *,
        request_timeout_seconds: float = 60.0,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds 必须大于 0")
        self.adapter = adapter
        self.request_timeout_seconds = request_timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy()

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.adapter.capabilities

    def _require_capabilities(self, request: ModelRequest) -> None:
        if (
            request.output_format is not None
            and not self.capabilities.structured_output
        ):
            raise ModelGatewayError(
                "Model adapter does not support structured output",
                code="unsupported_capability",
                provider=self.adapter.provider_name,
            )

    async def complete(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
    ) -> ModelResponse:
        self._require_capabilities(request)
        started = perf_counter()
        last_error: ModelGatewayError | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    response = await self.adapter.complete(
                        request,
                        cancellation=cancellation,
                    )
                latency_ms = (perf_counter() - started) * 1_000
                return response.model_copy(
                    update={
                        "provider": response.provider or self.adapter.provider_name,
                        "model": response.model or self.adapter.model_name,
                        "latency_ms": latency_ms,
                    }
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                error = _normalize_error(exc, self.adapter.provider_name)
                last_error = error
                if (
                    error.code not in _RETRYABLE_CODES
                    or attempt >= self.retry_policy.max_attempts
                ):
                    raise error from exc
                delay = min(
                    self.retry_policy.initial_backoff_seconds * (2 ** (attempt - 1)),
                    self.retry_policy.max_backoff_seconds,
                )
                if delay:
                    await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def complete_stream(
        self,
        request: ModelRequest,
        *,
        cancellation: CancellationToken,
        on_delta: ModelOutputSink,
    ) -> ModelResponse:
        """Stream native text deltas and still return one complete response.

        Retrying after a delta was published would duplicate user-visible text,
        so transient failures are retried only before the first published delta.
        Adapters without native streaming retain the same contract by publishing
        their completed text as one delta.
        """

        self._require_capabilities(request)
        adapter_stream = getattr(self.adapter, "complete_stream", None)
        if adapter_stream is None or not self.adapter.capabilities.streaming:
            response = await self.complete(request, cancellation=cancellation)
            if response.text:
                await on_delta(response.text)
            return response

        started = perf_counter()
        last_error: ModelGatewayError | None = None
        published = False

        async def publish(delta: str) -> None:
            nonlocal published
            if not delta:
                return
            try:
                await on_delta(delta)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise _ModelOutputSinkError from exc
            published = True

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                async with asyncio.timeout(self.request_timeout_seconds):
                    response = await adapter_stream(
                        request,
                        cancellation=cancellation,
                        on_delta=publish,
                    )
                latency_ms = (perf_counter() - started) * 1_000
                return response.model_copy(
                    update={
                        "provider": response.provider or self.adapter.provider_name,
                        "model": response.model or self.adapter.model_name,
                        "latency_ms": latency_ms,
                    }
                )
            except asyncio.CancelledError:
                raise
            except _ModelOutputSinkError as exc:
                if isinstance(exc.__cause__, Exception):
                    raise exc.__cause__
                raise
            except Exception as exc:  # noqa: BLE001
                error = _normalize_error(exc, self.adapter.provider_name)
                last_error = error
                if (
                    published
                    or error.code not in _RETRYABLE_CODES
                    or attempt >= self.retry_policy.max_attempts
                ):
                    raise error from exc
                delay = min(
                    self.retry_policy.initial_backoff_seconds * (2 ** (attempt - 1)),
                    self.retry_policy.max_backoff_seconds,
                )
                if delay:
                    await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error
