import { beforeEach, expect, it, vi } from "vitest";
import { apiFetch, ensureApiBase } from "./http";
import { exportBackup, exportHistoryArchive } from "./backups";

vi.mock("./http", () => ({ apiFetch: vi.fn(), ensureApiBase: vi.fn() }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(ensureApiBase).mockResolvedValue("http://privateagent.localhost"); });
function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(reader.error); reader.readAsText(blob);
  });
}

it.each(["0.0", "1.0", "0.7"])("导出保留服务端原始字节与数值表示 %s", async temperature => {
  const original = `{"format":"privateagent.backup.v2","payload":{"temperature":${temperature},"中文":"备份材料"},"sha256":"untouched"}\n`;
  vi.mocked(apiFetch).mockResolvedValue(new Response(original, { headers: { "Content-Type": "application/json" } }));
  const blob = await exportBackup("application", "compact");
  expect(await readBlob(blob)).toBe(original);
  expect(apiFetch).toHaveBeenCalledWith("http://privateagent.localhost/local-backups/export", expect.objectContaining({
    method: "POST", body: JSON.stringify({ kind: "application", home_layout: "compact" }),
  }));
});

it("历史归档导出也保留原始字节", async () => {
  const original = '{"cost_usd":0.0,"content":"历史"}';
  vi.mocked(apiFetch).mockResolvedValue(new Response(original));
  expect(await readBlob(await exportHistoryArchive("import-one"))).toBe(original);
  expect(apiFetch).toHaveBeenCalledWith("http://privateagent.localhost/local-history/imports/import-one/export", undefined);
});

it("拒绝错误响应，保留业务原因并兼容非 JSON 错误页", async () => {
  vi.mocked(apiFetch).mockResolvedValueOnce(Response.json({ detail: "请先取消当前任务" }, { status: 409 }));
  await expect(exportBackup("application", "standard")).rejects.toThrow("请先取消当前任务");
  vi.mocked(apiFetch).mockResolvedValueOnce(new Response("<html>unavailable</html>", { status: 503 }));
  await expect(exportBackup("application", "standard")).rejects.toThrow("备份导出失败（HTTP 503）");
});

it("连接失败不生成空备份", async () => {
  vi.mocked(apiFetch).mockRejectedValue(new Error("本机执行器未就绪"));
  await expect(exportBackup("configuration", "standard")).rejects.toThrow("本机执行器未就绪");
});
