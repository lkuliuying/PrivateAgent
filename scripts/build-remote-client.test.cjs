const { test } = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const {
  parseOptions, buildEnvironment, bundleConfig, updateManifest, assertReleaseReady,
  REMOTE_TARGET, REMOTE_IDENTIFIER,
} = require("./build-remote-client.cjs");

const release = (...args) => parseOptions(["https://api.example.com", "--release", "--version", "1.0.1", ...args]);

test("portable CLI remains unsigned and does not inherit installer identity or channel", () => {
  const options = parseOptions(["https://api.example.com/"]);
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
  assert.deepEqual(config.plugins.updater.endpoints, ["https://api.example.com/updates/remote/latest.json"]);
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
  assert.throws(() => parseOptions(["https://api.example.com/private"]), /API origin/);
  assert.throws(() => release("--download-base-url", "https://user:do-not-disclose@example.com/"), (error) => !error.message.includes("do-not-disclose"));
});

test("invalid CLI combinations cannot accidentally generate a release", () => {
  for (const args of [
    ["https://api.example.com", "--release"],
    ["https://api.example.com", "--version", "1.0.1"],
    ["https://api.example.com", "--release", "--preview-installer", "--version", "1.0.1"],
    ["https://api.example.com", "--release", "--version", "../1.0.1"],
    ["https://api.example.com", "--release", "--version", "01.0.1"],
    ["https://api.example.com", "--release", "--version", "1.0.1", "--version", "1.0.2"],
  ]) assert.throws(() => parseOptions(args));
  assert.throws(() => release("--update-url", "https://example.com/downloads/"), /manifest/);
});

test("preview installers never inherit signing secrets or produce an update manifest", () => {
  const options = parseOptions(["https://api.example.com", "--preview-installer", "--version", "1.0.1"]);
  const source = { PATH: "tools", PA_API_TOKEN: "fixture", VITE_OTHER: "fixture", TAURI_CONFIG: "unsafe override", TAURI_SIGNING_PRIVATE_KEY: "fixture", TAURI_SIGNING_PRIVATE_KEY_PASSWORD: "fixture", GITHUB_TOKEN: "fixture" };
  const env = buildEnvironment(source, options, "target");
  assert.equal(env.PATH, "tools");
  assert.equal(env.PA_API_TOKEN, undefined);
  assert.equal(env.VITE_OTHER, undefined);
  assert.equal(env.GITHUB_TOKEN, undefined);
  assert.equal(env.TAURI_CONFIG, undefined);
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY, undefined);
  assert.equal(env.TAURI_SIGNING_PRIVATE_KEY_PASSWORD, undefined);
  assert.equal(env.VITE_API_TOKEN, "");
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
  const result = spawnSync(process.execPath, [path.join(__dirname, "build-remote-client.cjs"), "https://api.example.com", "--release", "--version", "1.0.1", "--dry-run"], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(result.stdout);
  assert.equal(plan.config.identifier, REMOTE_IDENTIFIER);
  assert.equal(plan.updateTarget, REMOTE_TARGET);
  assert.equal(plan.config.version, "1.0.1");
});

test("unified builds default to local mode and cannot inherit legacy update channels", () => {
  const options = parseOptions(["--unified"]);
  assert.equal(options.apiBaseUrl, "");
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
