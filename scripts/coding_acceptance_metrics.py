"""只使用同一进程时钟和所属资源的过程指标；缺失不填零。"""
from __future__ import annotations

import ctypes
import os
import threading
import time

from coding_acceptance_budget import finite


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end < start:
            raise ValueError("时间区间倒置")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def duration(intervals):
    return sum(end - start for start, end in union(intervals))


def without(intervals, excluded):
    return max(0, duration(intervals) - duration([(max(a, c), min(b, d)) for a, b in union(intervals)
                                               for c, d in union(excluded) if max(a, c) < min(b, d)]))


def process_metrics(history, run):
    kinds = {"model": ("model.requested", {"model.output.finished", "model.output.interrupted"}, "attempt_id"),
             "tool": ("tool.requested", {"tool.invocation_finished"}, "tool_call_id"),
             "approval": ("tool.approval_required", {"tool.approval_resolved"}, "approval_id")}
    intervals, missing = {}, {}
    clocks = {event.get("payload", {}).get("timing", {}).get("clock_id") for event in history}
    valid_clock = bool(history) and len(clocks - {None}) == 1
    for name, (start_type, end_types, id_key) in kinds.items():
        pending, spans, reason = {}, [], None
        for event in history:
            kind, payload = event["type"], event.get("payload", {})
            if kind != start_type and kind not in end_types:
                continue
            timing, identity = payload.get("timing", {}), payload.get(id_key)
            stamp = timing.get("monotonic_seconds")
            if not valid_clock or not finite(stamp) or timing.get("clock_id") is None or not identity:
                reason = "missing_clock_or_correlation"
                continue
            if kind == start_type:
                if identity in pending:
                    reason = "duplicate_interval_start"
                pending[identity] = stamp
            elif identity not in pending or stamp < pending[identity]:
                reason = "missing_start_or_reversed_interval"
            else:
                spans.append((pending.pop(identity), stamp))
        if pending:
            reason = "unfinished_interval"
        if not history:
            reason = "events_unavailable"
        intervals[name] = spans
        missing[name + "_seconds"] = reason
    values = {name + "_seconds": None if missing[name + "_seconds"] else duration(spans) for name, spans in intervals.items()}
    if values["tool_seconds"] is not None:
        values["tool_seconds"] = without(intervals["tool"], intervals["approval"]) if values["approval_seconds"] is not None else None
        if values["tool_seconds"] is None:
            missing["tool_seconds"] = "approval_intervals_incomplete"
    transports = [e["payload"] for e in history if e["type"] == "model.transport"]
    requests = sum(e["type"] == "model.requested" for e in history)
    requested_ids = [e["payload"].get("attempt_id") for e in history if e["type"] == "model.requested"]
    transport_ids = [p.get("attempt_id") for p in transports]
    provider_known = (len(transports) == requests and len(set(requested_ids)) == requests and None not in requested_ids
                      and set(transport_ids) == set(requested_ids) and len(set(transport_ids)) == len(transport_ids)
                      and all(type(p.get("provider_requests")) is int and p["provider_requests"] >= 0
                              and type(p.get("provider_retries")) is int and p["provider_retries"] >= 0
                              and (p.get("call_id") is None or p["call_id"] == p["attempt_id"]) for p in transports))
    return {"version": "s6-process-1", **values, "total_seconds": None,
            "active_seconds": run.get("loop_budget", {}).get("active_seconds"),
            "model_requests": requests if history else None,
            "provider_requests": sum(p["provider_requests"] for p in transports) if provider_known and history else None,
            "provider_retries": sum(p["provider_retries"] for p in transports) if provider_known and history else None,
            "verification_retries": run.get("verification_retries", 0) if history else None,
            "compactions": sum(e["type"] == "context.compaction_completed" for e in history) if history else None,
            "compaction_attempts": sum(e["type"] == "context.compaction_started" for e in history) if history else None,
            "model_tool_union_seconds": duration([*intervals["model"], *intervals["tool"]]) if not any(missing.values()) else None,
            "missing_reasons": {**{key: value for key, value in missing.items() if value},
                                **({} if provider_known else {"provider_requests": "missing_or_unbound_transport"}),
                                **({} if finite(run.get("loop_budget", {}).get("active_seconds")) else {"active_seconds": "runtime_budget_unavailable"})},
            "source": "runtime_events_monotonic; loop_budget", "clock_ids": sorted(clocks - {None}),
            "interval_policy": "union_in_one_clock; tool_invocation_excludes_approval; background_process_lifetime_separate; categories_not_additive"}


def owned_process_count(process):
    job = getattr(process, "coding_job", None)
    if os.name != "nt" or job is None or not job.handle:
        raise ValueError("owned_job_unavailable")
    kernel = job.kernel
    kernel.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    accounting = (ctypes.c_uint64 * 6)()
    if not kernel.QueryInformationJobObject(job.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
        raise OSError("owned_job_query_failed")
    return ctypes.cast(accounting, ctypes.POINTER(ctypes.c_uint32))[10]


class ResourceSampler:
    def __init__(self, process, area, *, interval=1.0):
        if not finite(interval) or interval <= 0:
            raise ValueError("采样间隔无效")
        self.process, self.area, self.interval = process, area, interval
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.peak_processes, self.peak_storage = None, None
        self.errors, self.samples, self.times = set(), 0, []

    def sample(self):
        from coding_acceptance_catalog import storage_usage

        self.samples += 1
        self.times.append(time.monotonic())
        for key, getter in (("processes", lambda: owned_process_count(self.process)), ("storage", lambda: storage_usage(self.area))):
            try:
                value = getter()
                if key == "processes":
                    self.peak_processes = max(self.peak_processes or 0, value)
                else:
                    self.peak_storage = max(self.peak_storage or 0, value)
            except (OSError, ValueError):
                self.errors.add(key + "_sampling_incomplete")

    def _run(self):
        while not self.stop_event.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop_event.set()
        self.thread.join()
        self.sample()

    def snapshot(self):
        return {"interval_seconds": self.interval, "samples": self.samples,
                "max_observed_interval_seconds": max((b-a for a, b in zip(self.times, self.times[1:])), default=None),
                "peak_processes": self.peak_processes, "peak_sampled_storage_bytes": self.peak_storage,
                "missing_reasons": sorted(self.errors), "process_scope": "this_runtime_windows_job_including_descendants",
                "storage_scope": "this_attempt_directory", "limitation": "short_processes_and_between_sample_peaks_may_be_missed"}
