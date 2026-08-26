/**
 * v0.8.0 W2 · run 流 composable
 *
 * 生命周期：startRun（创建+续流）/ attachRun（已知 run 水合）/ cancelActive / detach。
 * - 世代令牌拒绝迟到回调：切换 thread/detach 后旧流帧不再写入（零容忍 §10）；
 * - 断线恢复：快照纠偏 → events 缺口重放（after_sequence=游标）→ SSE 续读，
 *   指数退避（1s/2s/4s/8s 封顶），收到帧即复位；
 * - 清理：AbortController/重连定时器随 detach 与作用域销毁释放。
 */
import { onScopeDispose, ref, shallowRef, triggerRef, type Ref, type ShallowRef } from "vue";
import {
  cancelCodingRun,
  createCodingRun,
  fetchRunEvents,
  fetchRunSnapshot,
  streamRunEvents,
} from "../api/runs";
import {
  applyRunFrame,
  cloneRunProjection,
  createRunProjection,
  reconcileRunWithSnapshot,
  type RunProjection,
} from "../model/runProjector";
import type {
  CodingRunCreateInput,
  RunConnectionPhase,
  RunSnapshot,
  RunStreamFrame,
} from "../model/runContracts";
import { isTerminalRunStatus } from "../model/runContracts";

export interface RunStreamDeps {
  createRun: (input: CodingRunCreateInput) => Promise<RunSnapshot>;
  fetchSnapshot: (runId: string) => Promise<RunSnapshot>;
  fetchEvents: (runId: string, afterSequence: number) => Promise<{ items: RunStreamFrame[] }>;
  openStream: (
    runId: string,
    afterSequence: number,
    callbacks: {
      onFrame: (frame: RunStreamFrame) => void;
      onError: (message: string) => void;
      onClose: () => void;
    }
  ) => AbortController;
  cancelRun: (runId: string) => Promise<unknown>;
  schedule: (handler: () => void, delayMs: number) => number;
  cancelSchedule: (handle: number) => void;
}

export interface RunStreamController {
  projection: ShallowRef<RunProjection | null>;
  phase: Ref<RunConnectionPhase>;
  connectionError: Ref<string | null>;
  /**
   * v0.9.0 H1-B（计划 §5.6）：创建失败的平铺 error_code（后端
   * coding_errors 契约）；供阻塞项诊断与恢复入口派生，未知为 null。
   */
  createErrorCode: Ref<string | null>;
  startRun: (input: CodingRunCreateInput) => Promise<void>;
  attachRun: (runId: string, userMessage?: string | null) => Promise<void>;
  cancelActive: () => Promise<void>;
  retryConnection: () => Promise<void>;
  detach: () => void;
}

/** CodingApiError 形状判定（{status, code, message}，非 Error 实例）。 */
function asCodingApiError(
  error: unknown
): { code: string; message: string } | null {
  if (
    error !== null &&
    typeof error === "object" &&
    "code" in error &&
    "message" in error &&
    typeof (error as { code: unknown }).code === "string" &&
    typeof (error as { message: unknown }).message === "string"
  ) {
    const parsed = error as { code: string; message: string };
    return { code: parsed.code, message: parsed.message };
  }
  return null;
}

function eventItemToFrame(item: {
  sequence: number;
  type: string;
  payload: Record<string, unknown>;
}): RunStreamFrame {
  return { sequence: item.sequence, type: item.type, payload: item.payload };
}

export function useRunStream(deps: Partial<RunStreamDeps> = {}): RunStreamController {
  const source: RunStreamDeps = {
    createRun: createCodingRun,
    fetchSnapshot: fetchRunSnapshot,
    fetchEvents: (runId, after) =>
      fetchRunEvents(runId, after).then((page) => ({
        items: page.items.map(eventItemToFrame),
      })),
    openStream: streamRunEvents,
    cancelRun: cancelCodingRun,
    schedule: (handler, delayMs) => window.setTimeout(handler, delayMs),
    cancelSchedule: (handle) => window.clearTimeout(handle),
    ...deps,
  };

  const projection = shallowRef<RunProjection | null>(null);
  const phase = ref<RunConnectionPhase>("idle");
  const connectionError = ref<string | null>(null);
  const createErrorCode = ref<string | null>(null);

  let generation = 0;
  let controller: AbortController | null = null;
  let reconnectTimer: number | null = null;
  let reconnectAttempts = 0;

  function publish(next: RunProjection): void {
    projection.value = next;
    triggerRef(projection);
  }

  /**
   * 写时复制：在 draft 上应用变更后以新引用发布——shallowRef 值变化使
   * 依赖投影的 computed 链（runStatus/plan 等）正确失效，子组件 props 更新。
   */
  function mutate(mutator: (draft: RunProjection) => void): void {
    const current = projection.value;
    if (!current) return;
    const draft = cloneRunProjection(current);
    mutator(draft);
    projection.value = draft;
    triggerRef(projection);
  }

  function abortStream(): void {
    if (controller) {
      controller.abort();
      controller = null;
    }
  }

  function clearReconnectTimer(): void {
    if (reconnectTimer !== null) {
      source.cancelSchedule(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function scheduleReconnect(runId: string, mine: number, reason: string): void {
    if (mine !== generation) return;
    if (projection.value && isTerminalRunStatus(projection.value.status)) {
      phase.value = "terminal";
      return;
    }
    phase.value = "reconnecting";
    connectionError.value = reason;
    reconnectAttempts += 1;
    const delay = Math.min(1000 * 2 ** Math.min(reconnectAttempts - 1, 3), 8000);
    clearReconnectTimer();
    reconnectTimer = source.schedule(() => {
      reconnectTimer = null;
      if (mine !== generation) return;
      void recover(runId, mine);
    }, delay);
  }

  /** 快照纠偏 + 缺口重放 + 续流 */
  async function recover(runId: string, mine: number): Promise<void> {
    try {
      const snapshot = await source.fetchSnapshot(runId);
      if (mine !== generation) return;
      const base =
        projection.value && projection.value.runId === runId
          ? cloneRunProjection(projection.value)
          : createRunProjection(runId);
      publish(reconcileRunWithSnapshot(base, snapshot));
      const cursor = projection.value?.lastSequence ?? 0;
      if (snapshot.last_event_sequence > cursor) {
        const page = await source.fetchEvents(runId, cursor);
        if (mine !== generation) return;
        mutate((target) => {
          for (const frame of page.items) applyRunFrame(target, frame);
        });
      }
      const status = projection.value?.status;
      if (status && isTerminalRunStatus(status)) {
        phase.value = "terminal";
        connectionError.value = null;
        return;
      }
      openStream(runId, mine);
    } catch (error) {
      if (mine !== generation) return;
      scheduleReconnect(runId, mine, error instanceof Error ? error.message : String(error));
    }
  }

  /**
   * 合成 run.terminal 只负责关流，不携带 completed_at。终态后补拉一次快照，
   * 让总耗时、最终用量与输出都收敛到后端 durable 事实；失败不推翻已收到的
   * 终态，用户仍可在下次重开任务时由 attachRun 恢复。
   */
  async function settleTerminalSnapshot(runId: string, mine: number): Promise<void> {
    try {
      const snapshot = await source.fetchSnapshot(runId);
      if (mine !== generation || !isTerminalRunStatus(snapshot.status)) return;
      const current = projection.value;
      if (!current || current.runId !== runId) return;
      const next = cloneRunProjection(current);
      if (snapshot.last_event_sequence >= next.lastSequence) {
        reconcileRunWithSnapshot(next, snapshot);
      } else {
        // 测试/兼容传输可能给合成帧分配额外序号；终态快照的时间字段仍是
        // 独立 durable 事实，可安全用于计时而不回退事件游标。
        next.startedAt = snapshot.started_at ?? next.startedAt;
        next.completedAt = snapshot.completed_at ?? next.completedAt;
      }
      publish(next);
    } catch {
      // 终态与最终输出已经由 durable 事件收敛；这里只缺少精确计时事实。
    }
  }

  function openStream(runId: string, mine: number): void {
    abortStream();
    phase.value = "streaming";
    connectionError.value = null;
    controller = source.openStream(runId, projection.value?.lastSequence ?? 0, {
      onFrame: (frame) => {
        if (mine !== generation) return;
        reconnectAttempts = 0;
        mutate((target) => {
          applyRunFrame(target, frame);
        });
        if (frame.type === "run.terminal") {
          phase.value = "terminal";
          abortStream();
          void settleTerminalSnapshot(runId, mine);
        }
      },
      onError: (message) => {
        if (mine !== generation) return;
        scheduleReconnect(runId, mine, message);
      },
      onClose: () => {
        if (mine !== generation) return;
        if (phase.value === "terminal") return;
        scheduleReconnect(runId, mine, "连接已关闭");
      },
    });
  }

  async function startRun(input: CodingRunCreateInput): Promise<void> {
    const mine = ++generation;
    abortStream();
    clearReconnectTimer();
    reconnectAttempts = 0;
    phase.value = "starting";
    connectionError.value = null;
    createErrorCode.value = null;
    try {
      const snapshot = await source.createRun(input);
      if (mine !== generation) return;
      const next = createRunProjection(snapshot.id, input.message);
      reconcileRunWithSnapshot(next, snapshot);
      publish(next);
      openStream(snapshot.id, mine);
    } catch (error) {
      if (mine !== generation) return;
      phase.value = "error";
      // 创建失败是失败关闭状态（无 run、不产生假完成记录）：结构化错误码交给
      // 阻塞项诊断派生恢复入口，而不是显示「[object Object]」或静默吞掉。
      const parsed = asCodingApiError(error);
      if (parsed) {
        createErrorCode.value = parsed.code;
        connectionError.value = parsed.message;
      } else {
        connectionError.value =
          error instanceof Error ? error.message : String(error);
      }
    }
  }

  async function attachRun(
    runId: string,
    userMessage: string | null = null
  ): Promise<void> {
    const mine = ++generation;
    abortStream();
    clearReconnectTimer();
    reconnectAttempts = 0;
    phase.value = "starting";
    connectionError.value = null;
    publish(createRunProjection(runId, userMessage));
    await recover(runId, mine);
  }

  async function retryConnection(): Promise<void> {
    const runId = projection.value?.runId;
    if (!runId) return;
    const mine = generation;
    await recover(runId, mine);
  }

  async function cancelActive(): Promise<void> {
    const runId = projection.value?.runId;
    if (!runId) return;
    await source.cancelRun(runId);
    // 状态由 durable run.cancelled 事件 / 重连快照收敛，不本地猜测
  }

  function detach(): void {
    generation += 1;
    abortStream();
    clearReconnectTimer();
    phase.value = "idle";
    connectionError.value = null;
    createErrorCode.value = null;
  }

  onScopeDispose(detach);

  return {
    projection,
    phase,
    connectionError,
    createErrorCode,
    startRun,
    attachRun,
    cancelActive,
    retryConnection,
    detach,
  };
}
