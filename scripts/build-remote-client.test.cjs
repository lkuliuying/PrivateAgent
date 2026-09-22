const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const {
  parseOptions, buildEnvironment, bundleConfig, updateManifest, assertReleaseReady, collectSourceManifest,
  REMOTE_TARGET, REMOTE_IDENTIFIER,
} = require("./build-remote-client.cjs");

const release = (...args) => parseOptions(["--release", "--version", "1.0.1", ...args]);

function sourceDirectory(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "pa-build-sources-"));
  t.after(() => {
    assert.equal(path.dirname(directory), path.resolve(os.tmpdir()));
    assert.ok(path.basename(directory).startsWith("pa-build-sources-"));
    fs.rmSync(directory, { recursive: true, force: true });
  });
  return directory;
}

test("构建清单排除已删除源码，其他缺失文件仍报错", (t) => {
  const directory = sourceDirectory(t);
  fs.writeFileSync(path.join(directory, "current.vue"), "当前源码");
  fs.writeFileSync(path.join(directory, "new.vue"), "新增源码");
  const run = (_command, args) => args.includes("--deleted") ? "removed.vue\0" : "new.vue\0removed.vue\0current.vue\0current.vue\0";
  const sources = collectSourceManifest(directory, directory, run);
  assert.deepEqual(sources.map(item => item.path), ["current.vue", "new.vue"]);
  assert.ok(sources.every(item => /^[a-f0-9]{64}$/.test(item.sha256)));
  fs.unlinkSync(path.join(directory, "new.vue"));
  assert.throws(() => collectSourceManifest(directory, directory, run), { code: "ENOENT" });
});

test("构建复核重新枚举源码，检测恢复、删除和内容变化", (t) => {
  const directory = sourceDirectory(t);
  fs.writeFileSync(path.join(directory, "current.vue"), "原内容");
  let deleted = "removed.vue\0";
  const run = (_command, args) => args.includes("--deleted") ? deleted : "current.vue\0removed.vue\0";
  const initial = collectSourceManifest(directory, directory, run);
  fs.writeFileSync(path.join(directory, "removed.vue"), "恢复内容");
  deleted = "";
  const restored = collectSourceManifest(directory, directory, run);
  assert.equal(restored.length, 2);
  assert.notDeepEqual(restored, initial);
  fs.writeFileSync(path.join(directory, "current.vue"), "更新内容");
  assert.notEqual(collectSourceManifest(directory, directory, run)[0].sha256, initial[0].sha256);
  fs.unlinkSync(path.join(directory, "current.vue"));
  deleted = "current.vue\0";
  assert.deepEqual(collectSourceManifest(directory, directory, run).map(item => item.path), ["removed.vue"]);
});

test("验收候选包隔离安装与数据目录，不进入正式更新通道", () => {
  const config = bundleConfig(parseOptions(["--unified", "--qa", "--preview-installer", "--version", "1.0.0"]), "web");
  assert.equal(config.identifier, "com.personal-assistant.desktop.candidate");
  assert.equal(config.productName, "PrivateAgentCandidate");
  assert.equal(config.mainBinaryName, "privateagent-candidate");
  assert.deepEqual(config.plugins.updater.endpoints, []);
  assert.equal(config.bundle.createUpdaterArtifacts, false);
  assert.equal(config.bundle.windows.nsis.installerHooks, null);
  assert.throws(() => release("--qa"), /QA/);
  assert.throws(() => parseOptions(["--unified", "--qa"]), /QA/);
});

test("portable CLI remains unsigned and does not inherit installer identity or channel", () => {
  const options = parseOptions([]);
  const config = bundleConfig(options, "../web");
  assert.equal(options.mode, "portable");
  assert.equal(config.identifier, undefined);
  assert.equal(config.plugins, undefined);
  assert.equal(config.bundle.createUpdaterArtifacts, false);
  assert.deepEqual(config.bundle.externalBin, ["binaries/private-agent-local", "binaries/exec-host"]);
});

test("remote installers cannot replace the local edition or stop its sidecar", () => {
  const options = release();
  const config = bundleConfig(options, "../web");
  assert.equal(config.version, "1.0.1");
  assert.equal(config.identifier, REMOTE_IDENTIFIER);
  assert.equal(config.mainBinaryName, "privateagent-remote");
  assert.deepEqual(config.bundle.externalBin, ["binaries/private-agent-local", "binaries/exec-host"]);
  assert.equal(config.bundle.windows.nsis.installerHooks, null);
  assert.deepEqual(config.plugins.updater.endpoints, ["https://www.liuyingapi.top/updates/remote/latest.json"]);
  assert.equal(config.bundle.createUpdaterArtifacts, true);
});

test("update hosting can be independent of the API and keeps immutable versioned assets", () => {
  const options = release("--update-url", "https://downloads.example.com/remote/latest.json", "--download-base-url", "https://cdn.example.com/releases/");
  const manifest = updateManifest(options, "PrivateAgent Remote_1.0.1_x64-setup.exe", "fixture-signature\n");
  assert.deepEqual(Object.keys(manifest.platforms), [REMOTE_TARGET]);
  assert.equal(manifest.platforms[REMOTE_TARGET].url, "https://cdn.example.com/releases/1.0.1/PrivateAgent%20Remote_1.0.1_x64-setup.exe");
  assert.equal(manifest.platforms[REMOTE_TARGET].signature, "fixture-signature");
  assert.equal(manifest.version, "1.0.1");
});

test("unsafe URL inputs fail without disclosing credentials", () => {
  for (const value of ["http://downloads.example.com/latest.json", "https://user:do-not-disclose@example.com/latest.json", "https://example.com/latest.json?token=do-not-disclose", "https://example.com/latest.json#do-not-disclose"]) {
    assert.throws(() => release("--update-url", value), (error) => !error.message.includes("do-not-disclose") && /HTTPS/.test(error.message));
  }
  assert.throws(() => parseOptions(["https://www.liuyingapi.top/private"]), /API origins/);
  assert.throws(() => release("--download-base-url", "https://user:do-not-disclose@example.com/"), (error) => !error.message.includes("do-not-disclose"));
});

test("invalid CLI combinations cannot accidentally generate a release", () => {
  for (const args of [
    ["--release"],
    ["--version", "1.0.1"],
    ["--release", "--preview-installer", "--version", "1.0.1"],
    ["--release", "--version", "../1.0.1"],
    ["--release", "--version", "01.0.1"],
    ["--release", "--version", "1.0.1", "--version", "1.0.2"],
  ]) assert.throws(() => parseOptions(args));
  assert.throws(() => release("--update-url", "https://example.com/downloads/"), /manifest/);
});

test("preview installers never inherit signing secrets or produce an update manifest", () => {
  const options = parseOptions(["--preview-installer", "--version", "1.0.1"]);
  const source = { PATH: "tools", PA_API_TOKEN: "fixture", VITE_OTHER: "fixture", TAURI_CONFIG: "unsafe override", TAURI_SIGNING_PRIVATE_KEY: "fixture", TAURI_SIGNING_PRIVATE_KEY_PASSWORD: "fixture", GITHUB_TOKEN: "fixture" };
  const env = buildEnvironment(source, options, "target");
  assert.equal(env.PATH, "tools");
  assert.equal(env.PA_API_TOKEN, undefined);
  assert.equal(env.VITE_OTHER, undefined);
  assert.equal(env.GITHUB_TOKEN, undefined);
  assert.equal(env.TAURI_CONFIG, undefined);
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY, undefined);
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD, undefined);
  assert.equal(env.VITE_API_TOKEN, undefined);
  assert.equal(env.VITE_API_BASE_URL, undefined);
  assert.equal(env.VITE_LOCAL_EXECUTOR, "true");
  assert.equal(bundleConfig(options, "web").bundle.createUpdaterArtifacts, false);
  assert.throws(() => updateManifest(options, "app-setup.exe", "fixture"), /signed release/);
});

test("release mode only forwards signing credentials and refuses dirty or unsigned publication", () => {
  const options = release();
  const env = buildEnvironment({ TAURI_SIGNING_PRIVATE_KEY: "fixture", TAURI_SIGNING_PRIVATE_KEY_PASSWORD: "fixture-password", PA_DB_PASSWORD: "fixture", GITHUB_TOKEN: "fixture" }, options, "target");
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY, "fixture");
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD, "fixture-password");
  assert.equal(env.PA_DB_PASSWORD, undefined);
  assert.equal(env.GITHUB_TOKEN, undefined);
  assert.throws(() => assertReleaseReady(options, true, true), /clean Git/);
  assert.throws(() => assertReleaseReady(options, false, false), /signing is not configured/);
  assert.doesNotThrow(() => assertReleaseReady(options, false, true));
  assert.throws(() => updateManifest(options, "app-setup.exe", "  "), /signed release/);
  assert.throws(() => updateManifest(options, "../app-setup.exe", "fixture"), /installer filename/);
});

test("dry-run executes the real CLI without building or requiring signing material", () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, "build-remote-client.cjs"), "--release", "--version", "1.0.1", "--dry-run"], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(result.stdout);
  assert.equal(plan.config.identifier, REMOTE_IDENTIFIER);
  assert.equal(plan.updateTarget, REMOTE_TARGET);
  assert.equal(plan.config.version, "1.0.1");
});

test("统一客户端无需账号地址，并拒绝旧平台地址参数", () => {
  assert.equal(parseOptions(["--unified"]).apiBaseUrl, undefined);
  assert.throws(() => parseOptions(["--unified", "https://other.example.test"]), /no longer supported/);
  const options = parseOptions(["--unified"]);
  assert.equal(options.apiBaseUrl, undefined);
  const config = bundleConfig(options, "web");
  assert.equal(config.identifier, "com.personal-assistant.desktop");
  assert.equal(config.mainBinaryName, "privateagent");
  assert.deepEqual(config.plugins.updater.endpoints, []);
  assert.throws(() => parseOptions(["--unified", "--release", "--version", "1.0.0"]), /independent/);
  const signed = parseOptions(["--unified", "--release", "--version", "1.0.0", "--update-url", "https://updates.example.com/unified/latest.json"]);
  assert.deepEqual(Object.keys(updateManifest(signed, "app-setup.exe", "fixture").platforms), ["unified-windows-x86_64"]);
  const preview = parseOptions(["--unified", "--preview-installer", "--version", "1.0.0"]);
  assert.deepEqual(bundleConfig(preview, "web").plugins.updater.endpoints, []);
});
