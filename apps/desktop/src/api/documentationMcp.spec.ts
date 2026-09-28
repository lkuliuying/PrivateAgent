import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch } from "./http";
import { documentationSources, selectDocumentationTools, type DocumentationSource } from "./documentationMcp";

vi.mock("./http", () => ({ ensureApiBase: vi.fn().mockResolvedValue("https://account.example.test"), apiFetch: vi.fn() }));
beforeEach(() => vi.clearAllMocks());

it("文档接口使用本机项目路径并携带配置版本与取消信号", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ id: "s" })));
  const source = { id: "s", version: "revision" } as DocumentationSource;
  const signal = new AbortController().signal;
  await selectDocumentationTools(7, source, ["search"], true, signal);
  const [url, init] = vi.mocked(apiFetch).mock.calls[0];
  expect(url).toBe("https://account.example.test/projects/7/documentation-sources/s/selection");
  expect(init?.signal).toBe(signal);
  expect(JSON.parse(String(init?.body))).toEqual({ expected_version: "revision", tools: ["search"], enabled: true });
});

it("保留可供用户修复的后端错误", async () => {
  vi.mocked(apiFetch).mockResolvedValue(new Response(JSON.stringify({ detail: "文档服务配置已变化" }), { status: 422 }));
  await expect(documentationSources(7, new AbortController().signal)).rejects.toThrow("配置已变化");
});
