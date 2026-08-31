import { invoke } from "@tauri-apps/api/core";

interface PipeFrame {
  id: string;
  status?: number;
  headers?: Record<string, string>;
  data?: string;
  done?: boolean;
  error?: string;
}

/** 把私有管道的有界响应转换为现有 API/SSE 消费的 Response。 */
export async function requestPrivateRuntime(path: string, init: RequestInit): Promise<Response> {
  if (init.signal?.aborted) throw init.signal.reason ?? new DOMException("请求已取消", "AbortError");
  const { Channel } = await import("@tauri-apps/api/core");
  const id = crypto.randomUUID();
  const headers: Record<string, string> = {};
  new Headers(init.headers).forEach((value, key) => {
    if (["authorization", "content-type", "accept", "last-event-id"].includes(key)) headers[key] = value;
  });
  let body = "";
  if (typeof init.body === "string") body = init.body;
  else if (init.body instanceof ArrayBuffer || ArrayBuffer.isView(init.body)) body = new TextDecoder("utf-8", { fatal: true }).decode(init.body);
  else if (init.body !== null && init.body !== undefined) throw new Error("本机管道仅接受 UTF-8 请求正文");
  if (new TextEncoder().encode(body).length > 2 * 1024 * 1024) throw new Error("本机请求超过 2 MiB 限制");

  return new Promise<Response>((resolve, reject) => {
    let ended = false;
    let started = false;
    let controller: ReadableStreamDefaultController<Uint8Array>;
    const cancelHost = () => { void invoke("local_executor_cancel", { id }).catch(() => undefined); };
    const cleanup = () => {
      ended = true;
      window.clearTimeout(timer);
      init.signal?.removeEventListener("abort", abort);
    };
    const fail = (reason: unknown) => {
      if (ended) return;
      cleanup();
      if (started) controller.error(reason);
      else reject(reason);
      cancelHost();
    };
    const abort = () => fail(init.signal?.reason ?? new DOMException("请求已取消", "AbortError"));
    const timer = window.setTimeout(() => fail(new Error("本机管道响应超时")), 20000);
    const stream = new ReadableStream<Uint8Array>({
      start(value) { controller = value; },
      cancel() { if (!ended) { cleanup(); cancelHost(); } },
    }, new ByteLengthQueuingStrategy({ highWaterMark: 4 * 1024 * 1024 }));
    const onEvent = new Channel<PipeFrame>();
    onEvent.onmessage = (frame) => {
      if (ended) return;
      if (frame.id !== id) { fail(new Error("本机管道请求标识不匹配")); return; }
      if (frame.error) { fail(new Error(frame.error)); return; }
      if (frame.status !== undefined) {
        if (started || frame.status < 200 || frame.status > 599) { fail(new Error("本机响应状态无效")); return; }
        started = true;
        window.clearTimeout(timer);
        resolve(new Response([204, 205, 304].includes(frame.status) ? null : stream,
          { status: frame.status, headers: frame.headers }));
      }
      if (frame.data !== undefined) {
        if (!started || (controller.desiredSize ?? 0) < 0) { fail(new Error("本机响应未开始或消费过慢")); return; }
        controller.enqueue(new TextEncoder().encode(frame.data));
      }
      if (frame.done) {
        if (!started) { fail(new Error("本机响应缺少状态")); return; }
        cleanup();
        controller.close();
      }
    };
    init.signal?.addEventListener("abort", abort, { once: true });
    if (init.signal?.aborted) { abort(); return; }
    void invoke("local_executor_request", { id, request: { path, method: init.method ?? "GET", headers, body }, onEvent }).catch(fail);
  });
}
