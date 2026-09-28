import type { Page, Route } from "@playwright/test";

/** 场景夹具只返回本机健康状态，不提供平台认证服务。 */
export async function fulfillCodingAuth(route: Route): Promise<boolean> {
  if (new URL(route.request().url()).pathname !== "/health") return false;
  await route.fulfill({ json: { mode: "desktop-local", protocol: 1 } });
  return true;
}

export async function prepareCodingFixture(page: Page): Promise<void> {
  await page.addInitScript(() => {
    // 真实请求层通过原生边界替身访问场景路由，不读取本机数据或凭据。
    const surface = window as unknown as { isTauri: boolean; __TAURI_INTERNALS__: Record<string, unknown> };
    surface.isTauri = true;
    let callbackId = 0;
    surface.__TAURI_INTERNALS__ = {
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main" } },
      transformCallback: () => ++callbackId, unregisterCallback: () => undefined,
      invoke: async (command: string, args: {
        id: string; request: { path: string; method: string; headers: Record<string, string>; body: string };
        onEvent: { onmessage: (frame: unknown) => void };
      }) => {
        if (command === "start_local_executor") return { transport: "stdio", protocol: 2 };
        if (command.startsWith("plugin:event|")) return 1;
        if (command === "local_executor_cancel") return;
        if (command !== "local_executor_request") throw new Error("测试未开放此原生操作");
        const path = args.request.path;
        let response: Response;
        if (path === "/health") response = Response.json({ mode: "desktop-local", protocol: 1 });
        else if (path === "/identity/local") response = Response.json({ ready: true, access_token: `local-session:${"a".repeat(43)}` });
        else if (path === "/projects/context") response = Response.json({ ready: true });
        else response = await fetch(`http://127.0.0.1:8000${path}`, {
          method: args.request.method, headers: args.request.headers,
          ...(args.request.body ? { body: args.request.body } : {}),
        });
        args.onEvent.onmessage({ id: args.id, status: response.status, headers: Object.fromEntries(response.headers) });
        const reader = response.body?.getReader();
        if (reader) {
          const decoder = new TextDecoder();
          while (true) {
            const item = await reader.read();
            if (item.done) break;
            args.onEvent.onmessage({ id: args.id, data: decoder.decode(item.value, { stream: true }) });
          }
          const tail = decoder.decode();
          if (tail) args.onEvent.onmessage({ id: args.id, data: tail });
        }
        args.onEvent.onmessage({ id: args.id, done: true });
      },
    };
  });
  await page.route("**://127.0.0.1:8000/**", route => route.abort("blockedbyclient"));
}
