const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const crypto = require("node:crypto");
const {
  parseOptions, buildEnvironment, bundleConfig, updateManifest, writeReleaseArtifacts, assertReleaseReady, collectSourceManifest,
  REMOTE_TARGET, REMOTE_IDENTIFIER, UNIFIED_TARGET,
} = require("./build-remote-client.cjs");

const release = (...args) => parseOptions(["--release", "--version", "1.0.1", ...args]);
const githubRelease = (...args) => parseOptions(["--unified", "--release", "--version", "1.0.0", "--github-repo", "lkuliuying/PrivateAgent", ...args]);

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
    ["--release", "--version", "1.0.1\n"],
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
  assert.deepEqual(Object.keys(updateManifest(signed, "PrivateAgent_1.0.0_x64-setup.exe", "fixture").platforms), ["unified-windows-x86_64"]);
  const preview = parseOptions(["--unified", "--preview-installer", "--version", "1.0.0"]);
  assert.deepEqual(bundleConfig(preview, "web").plugins.updater.endpoints, []);
});

test("统一预览可显式检查正式更新源，但不获得发布能力或签名材料", () => {
  const updateUrl = "https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json";
  const options = parseOptions(["--unified", "--preview-installer", "--version", "1.0.0", "--update-url", updateUrl]);
  const config = bundleConfig(options, "web");
  assert.equal(options.mode, "preview");
  assert.equal(options.updateUrl, updateUrl);
  assert.equal(config.identifier, "com.personal-assistant.desktop");
  assert.equal(config.productName, "PrivateAgent");
  assert.equal(config.mainBinaryName, "privateagent");
  assert.deepEqual(config.plugins.updater, { endpoints: [updateUrl] });
  assert.equal(config.bundle.createUpdaterArtifacts, false);
  const env = buildEnvironment({ TAURI_SIGNING_PRIVATE_KEY: "fixture", TAURI_SIGNING_PRIVATE_KEY_PASSWORD: "fixture" }, options, "target");
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY, undefined);
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD, undefined);
  assert.throws(() => updateManifest(options, "PrivateAgent_1.0.0_x64-setup.exe", "fixture"), /signed release/);
  assert.doesNotThrow(() => assertReleaseReady(options, true, false));
  const signed = release("--unified", "--update-url", updateUrl);
  assert.throws(() => assertReleaseReady(signed, true, true), /clean Git/);
  assert.throws(() => assertReleaseReady(signed, false, false), /signing is not configured/);
});

test("统一预览的显式更新源须通过地址校验，独立候选包不能启用更新源", () => {
  const args = ["--unified", "--preview-installer", "--version", "1.0.0"];
  for (const value of [
    "http://example.com/latest.json", "https://user:do-not-disclose@example.com/latest.json",
    "https://example.com/latest.json?token=do-not-disclose", "https://example.com/latest.json#do-not-disclose",
    "https://example.com/setup.exe", "not-a-url",
  ]) {
    assert.throws(() => parseOptions([...args, "--update-url", value]), error => !error.message.includes("do-not-disclose"));
  }
  assert.throws(() => parseOptions([...args, "--qa", "--update-url", "https://example.com/latest.json"]), /QA/);
  assert.throws(() => parseOptions([...args, "--github-repo", "lkuliuying/PrivateAgent"]), /unified release/);
});

test("统一预览 CLI 将显式更新源写入配置，默认仍不继承任何更新源", () => {
  const cli = path.join(__dirname, "build-client.cjs");
  const args = [cli, "--preview-installer", "--version", "1.0.0", "--dry-run"];
  for (const updateUrl of [null, "https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json"]) {
    const result = spawnSync(process.execPath, [...args, ...(updateUrl ? ["--update-url", updateUrl] : [])], { encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    const plan = JSON.parse(result.stdout);
    assert.equal(plan.mode, "preview");
    assert.equal(plan.updateTarget, UNIFIED_TARGET);
    assert.equal(plan.config.bundle.createUpdaterArtifacts, false);
    assert.deepEqual(plan.config.plugins.updater.endpoints, updateUrl ? [updateUrl] : []);
  }
});

test("GitHub 正式构建生成固定更新入口及不重复版本目录的清单", () => {
  const options = githubRelease();
  assert.equal(options.releaseTag, "v1.0.0");
  assert.equal(options.updateUrl, "https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json");
  assert.equal(options.downloadBaseUrl, "https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0");
  const config = bundleConfig(options, "web");
  assert.equal(config.identifier, "com.personal-assistant.desktop");
  assert.deepEqual(config.plugins.updater.endpoints, [options.updateUrl]);
  assert.equal(config.bundle.createUpdaterArtifacts, true);
  const manifest = updateManifest(options, "PrivateAgent_1.0.0_x64-setup.exe", "fixture-signature\r\n");
  assert.deepEqual(Object.keys(manifest.platforms), [UNIFIED_TARGET]);
  assert.equal(manifest.platforms[UNIFIED_TARGET].url, "https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/PrivateAgent_1.0.0_x64-setup.exe");
  assert.equal(manifest.platforms[UNIFIED_TARGET].signature, "fixture-signature");
  assert.equal(manifest.version, "1.0.0");
  assert.match(manifest.pub_date, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  assert.ok(Number.isFinite(Date.parse(manifest.pub_date)));
});

test("GitHub 参数只支持正式统一客户端且禁止混合自定义地址", () => {
  for (const args of [
    ["--github-repo", "lkuliuying/PrivateAgent"],
    ["--unified", "--github-repo", "lkuliuying/PrivateAgent"],
    ["--release", "--version", "1.0.0", "--github-repo", "lkuliuying/PrivateAgent"],
    ["--unified", "--preview-installer", "--version", "1.0.0", "--github-repo", "lkuliuying/PrivateAgent"],
    ["--unified", "--qa", "--preview-installer", "--version", "1.0.0", "--github-repo", "lkuliuying/PrivateAgent"],
  ]) assert.throws(() => parseOptions(args), /unified release/);
  assert.throws(() => githubRelease("--qa"), /unified release/);
  assert.throws(() => githubRelease("--update-url", "https://example.com/latest.json"), /cannot be combined/);
  assert.throws(() => githubRelease("--download-base-url", "https://example.com/releases"), /cannot be combined/);
  assert.throws(() => githubRelease("--github-repo", "another/repo"), /Duplicate/);
  assert.throws(() => parseOptions(["--unified", "--release", "--version", "1.0.0", "--github-repo"]), /Missing value/);
});

test("GitHub 仓库拒绝路径、凭据、异常长度和非法名称且不回显输入", () => {
  for (const value of [
    "https://github.com/owner/repo", "user:do-not-disclose@github.com/repo", "owner/repo?token=do-not-disclose", "owner/repo#do-not-disclose",
    "owner/repo/extra", "owner\\repo", "owner/%2e%2e", "owner/..", "owner/.", "/repo", "owner/", "-owner/repo", "owner-/repo", "a--b/repo",
    "owner/repo\n", "owner\n/repo", " owner/repo", `${"a".repeat(40)}/repo`, `owner/${"a".repeat(101)}`,
  ]) {
    assert.throws(() => parseOptions(["--unified", "--release", "--version", "1.0.0", "--github-repo", value]),
      error => error.message === "GitHub repository must be a valid owner/repo without a URL, credentials, query or fragment.");
  }
  for (const value of ["a/b", "owner-name/repo.name_1-0", `${"a".repeat(39)}/${"b".repeat(100)}`]) {
    assert.equal(parseOptions(["--unified", "--release", "--version", "1.0.0", "--github-repo", value]).githubRepo, value);
  }
});

test("正式统一清单拒绝远程版、候选版、错版本或错架构安装器", () => {
  for (const options of [githubRelease(), release("--unified", "--update-url", "https://example.com/latest.json")]) {
    for (const name of ["PrivateAgentRemote_1.0.0_x64-setup.exe", "PrivateAgentCandidate_1.0.0_x64-setup.exe", "PrivateAgent_9.0.0_x64-setup.exe", "PrivateAgent_1.0.0_arm64-setup.exe", "app-setup.exe"]) {
      assert.throws(() => updateManifest(options, name, "fixture"), /exact PrivateAgent/);
    }
  }
});

test("发布资产摘要覆盖最终安装包、原始签名文件及最新清单且拒绝覆盖", (t) => {
  const directory = sourceDirectory(t);
  const options = githubRelease();
  const installerName = "PrivateAgent_1.0.0_x64-setup.exe";
  const installer = path.join(directory, installerName);
  const signatureFile = `${installer}.sig`;
  fs.writeFileSync(installer, Buffer.from("MZ-public-test-fixture"));
  fs.writeFileSync(signatureFile, "public-test-signature\r\n");
  const sums = writeReleaseArtifacts(options, installer, signatureFile, directory);
  const lines = sums.trim().split("\n");
  assert.equal(lines.length, 3);
  assert.deepEqual(lines.map(line => line.split("  ")[1]), [
    `publish/1.0.0/${installerName}`, `publish/1.0.0/${installerName}.sig`, "publish/latest.json",
  ]);
  for (const line of lines) {
    const [digest, file] = line.split("  ");
    assert.equal(digest, crypto.createHash("sha256").update(fs.readFileSync(path.join(directory, file))).digest("hex"));
  }
  assert.deepEqual(fs.readFileSync(path.join(directory, "publish", "1.0.0", `${installerName}.sig`)), fs.readFileSync(signatureFile));
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, "publish", "latest.json"), "utf8"));
  assert.equal(manifest.platforms[UNIFIED_TARGET].signature, "public-test-signature");
  assert.throws(() => writeReleaseArtifacts(options, installer, signatureFile, directory), { code: "EEXIST" });
});

test("发布资产缺失或签名为空时拒绝产出可用清单", (t) => {
  const directory = sourceDirectory(t);
  const installer = path.join(directory, "PrivateAgent_1.0.0_x64-setup.exe");
  assert.throws(() => writeReleaseArtifacts(githubRelease(), installer, `${installer}.sig`, directory), { code: "ENOENT" });
  fs.writeFileSync(`${installer}.sig`, "\r\n");
  assert.throws(() => writeReleaseArtifacts(githubRelease(), installer, `${installer}.sig`, directory), /signed release/);
  fs.writeFileSync(`${installer}.sig`, "public-test-signature");
  assert.throws(() => writeReleaseArtifacts(githubRelease(), installer, `${installer}.sig`, directory), { code: "ENOENT" });
  assert.equal(fs.existsSync(path.join(directory, "publish", "latest.json")), false);
});

test("统一 CLI 的 GitHub dry-run 无需签名材料且错误参数不泄露凭据", () => {
  const cli = path.join(__dirname, "build-client.cjs");
  const result = spawnSync(process.execPath, [cli, "--release", "--version", "1.0.0", "--github-repo", "lkuliuying/PrivateAgent", "--dry-run"], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(result.stdout);
  assert.equal(plan.githubRepo, "lkuliuying/PrivateAgent");
  assert.equal(plan.releaseTag, "v1.0.0");
  assert.equal(plan.updateTarget, UNIFIED_TARGET);
  assert.deepEqual(plan.config.plugins.updater.endpoints, ["https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json"]);
  const invalid = spawnSync(process.execPath, [cli, "--release", "--version", "1.0.0", "--github-repo", "do-not-disclose@github.com/repo", "--dry-run"], { encoding: "utf8" });
  assert.equal(invalid.status, 1);
  assert.equal(invalid.stdout, "");
  assert.match(invalid.stderr, /valid owner\/repo/);
  assert.equal(invalid.stderr.includes("do-not-disclose"), false);
});
