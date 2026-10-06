import { expect, test, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdir, mkdtemp, readFile } from "node:fs/promises";
import { delimiter, dirname, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { prepareCodingFixture } from "./coding-auth-fixture";

type RuntimeRequest = { path: string; method: string; headers: Record<string, string>; body?: string };
type RuntimeResponse = { status: number; headers: Record<string, string>; body: string };
type Snapshot = {
  parameters: { llm_temperature?: number };
  providers: Record<string, { enabled: boolean }>;
  projects: { id: number; name: string; root_path: string; model_restore_pending: unknown }[];
  sessions: { title: string; model_profile_id: string | null; model_restore_pending: unknown }[];
  messages: { content: string }[];
  runs: { cost_usd: number; status: string }[];
  drafts: { text: string; clientRequestId: string; requestSignature: string; attachments: unknown[] }[];
  attachments: { name: string; kind: string; content: string }[];
  attachment_files: string[];
  message_attachment_count: number; grant_count: number; account_calls: number; provider_calls: number;
};
type Ready = { ready: true; root: string; mapped_root: string; source: Snapshot };

class BackupFixture {
  private nextId = 0;
  private stderr = "";
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  private exited: Promise<void>;
  readonly ready: Promise<Ready>;

  constructor(private child: ChildProcessWithoutNullStreams) {
    this.exited = new Promise(resolveExit => child.once("exit", () => resolveExit()));
    this.ready = new Promise((resolveReady, rejectReady) => {
      const startupTimeout = setTimeout(() => rejectReady(new Error("备份 ASGI 夹具启动超时")), 20_000);
      child.stderr.on("data", chunk => { this.stderr = (this.stderr + String(chunk)).slice(-6000); });
      const lines = createInterface({ input: child.stdout });
      lines.on("line", line => {
        try {
          const value = JSON.parse(line);
          if (value.ready === true) { clearTimeout(startupTimeout); resolveReady(value); return; }
          const pending = this.pending.get(value.id);
          if (!pending) return;
          this.pending.delete(value.id);
          if (value.error) pending.reject(new Error(value.error)); else pending.resolve(value.result);
        } catch {
          clearTimeout(startupTimeout);
          rejectReady(new Error("备份 ASGI 夹具返回了无效 JSONL"));
        }
      });
      const fail = (error: Error) => {
        clearTimeout(startupTimeout);
        rejectReady(error);
        for (const pending of this.pending.values()) pending.reject(error);
        this.pending.clear();
      };
      child.on("error", fail);
      child.on("exit", (code, signal) => fail(new Error(`备份夹具已退出 (${code ?? signal})：${this.stderr}`)));
    });
  }

  async send<T>(command: string, fields: Record<string, unknown> = {}): Promise<T> {
    const id = ++this.nextId;
    const response = new Promise<T>((resolveResponse, reject) => {
      this.pending.set(id, { resolve: value => resolveResponse(value as T), reject });
      this.child.stdin.write(JSON.stringify({ id, command, ...fields }) + "\n");
    });
    let timeout: NodeJS.Timeout | undefined;
    try {
      return await Promise.race([response, new Promise<never>((_, reject) => {
        timeout = setTimeout(() => reject(new Error("备份 ASGI 请求超时")), 20_000);
      })]);
    } finally {
      clearTimeout(timeout);
      this.pending.delete(id);
    }
  }

  async close() {
    if (this.child.exitCode !== null) return;
    try { await this.send("shutdown"); } finally {
      this.child.stdin.end();
      let timeout: NodeJS.Timeout | undefined;
      try {
        await Promise.race([this.exited, new Promise<void>(resolveTimeout => {
          timeout = setTimeout(resolveTimeout, 5000);
        })]);
      } finally {
        clearTimeout(timeout);
        if (this.child.exitCode === null) { this.child.kill(); await this.exited; }
      }
    }
  }
}

async function startFixture(temperature: number): Promise<BackupFixture> {
  const repository = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
  const runDirectory = resolve(repository, ".run");
  await mkdir(runDirectory, { recursive: true });
  const root = await mkdtemp(resolve(runDirectory, "backup-roundtrip-"));
  for (const name of ["temp", "home", "home/AppData/Roaming", "home/AppData/Local"]) await mkdir(resolve(root, name), { recursive: true });
  // 只传递解释器启动所需的系统变量，用户配置、密钥和代理设置不会进入子进程。
  const environment: NodeJS.ProcessEnv = {};
  for (const name of ["PATH", "Path", "SYSTEMROOT", "SystemRoot", "WINDIR", "windir", "COMSPEC", "ComSpec", "PATHEXT"])
    if (process.env[name]) environment[name] = process.env[name];
  Object.assign(environment, { PYTHONPATH: [resolve(repository, "src"), resolve(repository, "tests/unit")].join(delimiter),
    PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1",
    HOME: resolve(root, "home"), USERPROFILE: resolve(root, "home"), APPDATA: resolve(root, "home/AppData/Roaming"),
    LOCALAPPDATA: resolve(root, "home/AppData/Local"), TEMP: resolve(root, "temp"), TMP: resolve(root, "temp") });
  const python = process.env.PA_E2E_PYTHON || resolve(repository, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  return new BackupFixture(spawn(python, ["-B", resolve(repository, "tests/coding_acceptance/backup_roundtrip_fixture.py"),
    "--root", root, "--temperature", String(temperature)], { cwd: root, env: environment, windowsHide: true, stdio: "pipe" }));
}

async function openBackups(page: Page) {
  await page.goto("/#/app");
  await page.locator(".workspace-header__profile").click();
  await page.getByTestId("settings-section-backup").click();
  await expect(page.getByRole("button", { name: "导出应用数据备份", exact: true })).toBeVisible();
}

for (const temperature of [0, 1, 0.7]) {
  test(`真实下载文件往返保留温度 ${temperature}、零费用与中文媒体`, async ({ page, baseURL }, info) => {
    const fixture = await startFixture(temperature);
    const requests: { request: RuntimeRequest; response: RuntimeResponse }[] = [];
    const blocked: string[] = [];
    const browserErrors: string[] = [];
    let selectedPath = "";
    try {
      const ready = await fixture.ready;
      page.on("pageerror", error => browserErrors.push(error.message));
      await prepareCodingFixture(page);
      await page.route("**/*", route => {
        const url = new URL(route.request().url());
        if (url.origin === new URL(baseURL!).origin) return route.continue();
        blocked.push(url.origin);
        return route.abort("blockedbyclient");
      });
      await page.exposeFunction("backupFixtureRequest", async (request: RuntimeRequest) => {
        const response = await fixture.send<RuntimeResponse>("request", { request });
        requests.push({ request, response });
        return response;
      });
      await page.exposeFunction("backupFixtureDialog", () => selectedPath);
      await page.addInitScript(() => {
        const surface = window as unknown as {
          __TAURI_INTERNALS__: { invoke: (command: string, args: unknown) => Promise<unknown> };
          backupFixtureRequest: (request: RuntimeRequest) => Promise<RuntimeResponse>;
          backupFixtureDialog: () => Promise<string>;
        };
        const invoke = surface.__TAURI_INTERNALS__.invoke;
        surface.__TAURI_INTERNALS__.invoke = async (command, args) => {
          if (command === "plugin:dialog|open") return surface.backupFixtureDialog();
          if (command === "get_update_configuration") return { version: "1.0.0", endpoint: null, target: "local" };
          if (command !== "local_executor_request") return invoke(command, args);
          const value = args as { id: string; request: RuntimeRequest; onEvent: { onmessage: (frame: unknown) => void } };
          const response = await surface.backupFixtureRequest(value.request);
          value.onEvent.onmessage({ id: value.id, status: response.status, headers: response.headers });
          value.onEvent.onmessage({ id: value.id, data: response.body });
          value.onEvent.onmessage({ id: value.id, done: true });
        };
      });
      await openBackups(page);
      await page.getByRole("button", { name: "导出应用数据备份", exact: true }).click();
      const downloadPromise = page.waitForEvent("download");
      await page.getByRole("dialog", { name: "导出应用数据备份？" }).getByRole("button", { name: "导出", exact: true }).click();
      const download = await downloadPromise;
      selectedPath = resolve(ready.root, "browser-downloaded.json");
      await download.saveAs(selectedPath);
      const downloaded = await readFile(selectedPath);
      const exported = requests.find(item => item.request.path === "/local-backups/export")!;
      expect(exported.response.status).toBe(200);
      expect(downloaded.equals(Buffer.from(exported.response.body, "utf8"))).toBe(true);
      const archive = JSON.parse(downloaded.toString("utf8"));
      expect(archive.format).toBe("privateagent.backup.v2");
      expect(archive.payload.configuration.parameters.llm_temperature).toBe(temperature);
      expect(exported.response.body).toContain(`"llm_temperature":${temperature === 0.7 ? "0.7" : `${temperature}.0`}`);
      expect(exported.response.body).toContain('"cost_usd":0.0');

      await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
      await page.goto("about:blank");
      await fixture.send("target");
      await openBackups(page);
      await page.getByRole("button", { name: "选择备份并预览", exact: true }).click();
      await expect(page.getByRole("heading", { name: "导入预览", exact: true })).toBeVisible();
      const preview = requests.filter(item => item.request.path === "/local-backups/preview").at(-1)!;
      expect(preview.response.status).toBe(200);
      expect(JSON.parse(preview.response.body).counts.sessions).toBe(1);
      await expect(page.getByLabel("恢复模型选择核对")).toHaveCount(2);
      await expect(page.getByLabel("恢复模型选择核对").first()).toContainText("需重新确认模型");
      await expect(page.getByLabel("恢复模型选择核对").last()).toContainText("需重新确认模型");
      await page.getByRole("button", { name: "确认导入普通配置", exact: true }).click();
      await page.getByRole("dialog", { name: "导入所列普通配置？" }).getByRole("button", { name: "确认导入", exact: true }).click();
      await expect.poll(async () => (await fixture.send<Snapshot>("snapshot")).parameters.llm_temperature).toBe(temperature);
      await expect(page.getByRole("status", { name: "普通配置导入结果" })).toContainText("普通配置已导入");
      selectedPath = ready.mapped_root;
      await page.getByRole("button", { name: "选择项目目录", exact: true }).click();
      await page.getByRole("button", { name: "确认恢复历史、草稿和附件", exact: true }).click();
      await page.getByRole("dialog", { name: "恢复所列应用数据？" }).getByRole("button", { name: "确认导入", exact: true }).click();
      await expect.poll(async () => (await fixture.send<Snapshot>("snapshot")).sessions.length).toBe(1);
      const resultCard = page.getByRole("status", { name: "应用数据恢复结果" });
      await expect(resultCard).toBeVisible();
      await expect(resultCard).toContainText("应用数据已恢复");
      await expect(resultCard.locator("dt").filter({ hasText: /^待确认模型选择$/ }).locator("+ dd")).toHaveText("2");
      await expect(resultCard).toContainText("任务没有自动执行");
      const materials = page.getByRole("region", { name: "附件与存储管理" });
      await expect(materials).toContainText("6 个附件");
      await expect(materials.getByRole("button", { name: /^中文图片\.png ·/ })).toBeVisible();
      await expect(materials.getByRole("button", { name: /^草稿中文文档\.pdf ·/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "核对并回滚数据", exact: true })).toBeVisible();
      await expect(page.getByRole("region", { name: "本机历史迁移" })).toContainText("待确认模型 2 个");
      const restored = await fixture.send<Snapshot>("snapshot");
      expect(restored.projects).toEqual([expect.objectContaining({ name: "中文备份项目", root_path: ready.mapped_root })]);
      expect(restored.sessions[0].title).toBe("中文历史与未发送草稿");
      expect(restored.messages[0].content).toBe("请查看中文历史附件");
      expect(restored.runs).toEqual([expect.objectContaining({ cost_usd: 0.0 })]);
      expect(restored.attachments).toEqual(ready.source.attachments);
      expect(restored.message_attachment_count).toBe(3);
      expect(restored.drafts).toEqual([expect.objectContaining({ text: "中文未发送草稿", clientRequestId: "", requestSignature: "", attachments: expect.any(Array) })]);
      expect(restored.drafts[0].attachments).toHaveLength(3);
      expect(restored.providers.provider.enabled).toBe(false);
      expect(restored.projects[0].model_restore_pending).toBeTruthy();
      expect(restored.sessions[0].model_restore_pending).toBeTruthy();
      expect(restored.sessions[0].model_profile_id).toBeNull();
      expect(restored.grant_count).toBe(0);
      expect(restored.provider_calls).toBe(0);
      expect(restored.account_calls).toBe(0);
      await page.getByRole("button", { name: "核对并回滚数据", exact: true }).click();
      await page.getByRole("dialog", { name: "回滚这次数据导入？" }).getByRole("button", { name: "核对并回滚", exact: true }).click();
      await expect.poll(async () => (await fixture.send<Snapshot>("snapshot")).projects.length).toBe(0);
      await expect(materials).toContainText("目前没有保存的附件");
      await expect(page.getByRole("region", { name: "本机历史迁移" })).toContainText("暂无数据导入记录");
      const rolledBack = await fixture.send<Snapshot>("snapshot");
      for (const key of ["projects", "sessions", "messages", "runs", "drafts", "attachments", "attachment_files"] as const)
        expect(rolledBack[key]).toEqual([]);
      expect(rolledBack.message_attachment_count).toBe(0);
      expect(rolledBack.parameters).toEqual(restored.parameters);
      expect(rolledBack.providers).toEqual(restored.providers);
      const rollback = requests.find(item => /\/local-history\/imports\/[^/]+\/rollback$/.test(item.request.path))!;
      expect(rollback.response.status).toBe(200);
      expect(JSON.parse(rollback.response.body).rolled_back).toBe(true);
      expect(await fixture.send("network")).toEqual({ account_calls: 0, provider_calls: 0 });
      expect(blocked).toEqual([]);
      expect(browserErrors).toEqual([]);
      expect(requests.filter(item => item.request.path.startsWith("/local-backups/")).map(item => item.response.status)).toEqual([200, 200, 200, 200]);
      await info.attach("browser-download", { path: resolve(ready.root, "browser-downloaded.json"), contentType: "application/json" });
    } finally {
      await page.goto("about:blank").catch(() => undefined);
      await fixture.close();
    }
  });
}
