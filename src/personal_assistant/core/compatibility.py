"""Low-cardinality telemetry for compatibility paths awaiting retirement."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from threading import Lock


_LABELS = {
    "/tools": {
        "modes": frozenset({"legacy_registry"}),
        "outcomes": frozenset({"returned"}),
    },
    "/tools/plan": {
        "modes": frozenset({"legacy_full", "runtime_filtered"}),
        "outcomes": frozenset({"planned", "not_planned", "error"}),
    },
    "/chat/stream": {
        "modes": frozenset(
            {
                "agent_runtime",
                "legacy_runtime_disabled",
                "legacy_tool_result",
                "legacy_rag_tools_disabled",
                "legacy_output_verification_disabled",
            }
        ),
        "outcomes": frozenset({"routed"}),
    },
    "/tool-calls/:id/approve": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"succeeded", "failed", "conflict", "not_found"}),
    },
    "/tool-calls/:id/reject": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"rejected", "conflict", "not_found"}),
    },
    "/tool-calls": {
        "modes": frozenset({"all", "session_filtered"}),
        "outcomes": frozenset({"returned"}),
    },
    "/tool-calls/:id": {
        "modes": frozenset({"legacy_tool_call"}),
        "outcomes": frozenset({"found", "not_found"}),
    },
}


class CompatibilityTelemetry:
    """Track process-lifetime compatibility calls without user-controlled labels."""

    def __init__(self) -> None:
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._lock = Lock()
        self._calls: Counter[str] = Counter()
        self._modes: Counter[tuple[str, str]] = Counter()
        self._outcomes: Counter[tuple[str, str]] = Counter()

    def record(self, *, path: str, mode: str, outcome: str) -> None:
        labels = _LABELS.get(path)
        if labels is None:
            raise ValueError(f"unsupported compatibility path: {path}")
        if mode not in labels["modes"]:
            raise ValueError(f"unsupported compatibility mode: {mode}")
        if outcome not in labels["outcomes"]:
            raise ValueError(f"unsupported compatibility outcome: {outcome}")
        with self._lock:
            self._calls[path] += 1
            self._modes[(path, mode)] += 1
            self._outcomes[(path, outcome)] += 1

    def snapshot(self) -> dict:
        with self._lock:
            calls = self._calls.copy()
            modes = self._modes.copy()
            outcomes = self._outcomes.copy()
        return {
            "scope": "current_process",
            "started_at": self._started_at,
            "paths": {
                path: {
                    "calls": calls[path],
                    "modes": {
                        mode: modes[(path, mode)]
                        for mode in sorted(_LABELS[path]["modes"])
                    },
                    "outcomes": {
                        outcome: outcomes[(path, outcome)]
                        for outcome in sorted(_LABELS[path]["outcomes"])
                    },
                }
                for path in sorted(_LABELS)
            },
        }


compatibility_telemetry = CompatibilityTelemetry()
