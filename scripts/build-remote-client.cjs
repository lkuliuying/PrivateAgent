// Build a remote client, or a separately identified NSIS remote update release.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

const serverSource = fs.readFileSync(path.join(__dirname, "../apps/desktop/src-tauri/src/server.rs"), "utf8");
const FIXED_API_ORIGIN = serverSource.match(/ACCOUNT_SERVER_ORIGIN: &str = "([^"]+)"/)?.[1];
if (!FIXED_API_ORIGIN) throw new Error("Missing backend account server constant.");

const REMOTE_IDENTIFIER = "com.personal-assistant.desktop.remote";
const REMOTE_TARGET = "remote-windows-x86_64";
const UNIFIED_TARGET = "unified-windows-x86_64";
const REMOTE_BINARY = "privateagent-remote";

function httpsUrl(value, label, originOnly = false) {
  let url;
  try { url = new URL(value); } catch { throw new Error(`Invalid ${label}.`); }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
      (originOnly && url.pathname !== "/")) {
    // Never echo an invalid input: it may accidentally contain credentials.
    throw new Error(`${label} must use HTTPS without credentials, a query or fragment${originOnly ? ", or a path" : ""}.`);
  }
  return url;
}

function parseOptions(args) {
  const options = { mode: "portable", dryRun: false };
  const values = new Set(["--version", "--update-url", "--download-base-url"]);
  let api;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--release" || arg === "--preview-installer") {
      if (options.mode !== "portable") throw new Error("Choose one installer mode.");
      options.mode = arg === "--release" ? "release" : "preview";
    } else if (arg === "--unified") {
      options.unified = true;
    } else if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (values.has(arg)) {
      const value = args[++i];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${arg}.`);
      const key = { "--version": "version", "--update-url": "updateUrl", "--download-base-url": "downloadBaseUrl" }[arg];
      if (options[key]) throw new Error(`Duplicate ${arg}.`);
      options[key] = value;
    } else if (arg.startsWith("--") || api) {
      throw new Error("Unknown option or multiple API origins. Use --help.");
    } else {
      api = arg;
    }
  }
  options.apiBaseUrl = httpsUrl(api || FIXED_API_ORIGIN, "API origin", true).origin;
  if (options.apiBaseUrl !== FIXED_API_ORIGIN) throw new Error("Account server is fixed in the desktop backend; API overrides are not supported.");
  if (options.mode === "portable") {
    if (options.version || options.updateUrl || options.downloadBaseUrl) {
      throw new Error("Version and update URLs require --release or --preview-installer.");
    }
    return options;
  }
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(options.version || "")) {
    throw new Error("Installer builds require --version with a stable version, for example 1.0.1.");
  }
  if (options.unified && options.mode === "release" && !options.updateUrl) throw new Error("Unified releases require an explicit independent --update-url; old channels must not be reused implicitly.");
  options.updateUrl = options.unified && options.mode === "preview" ? "" : httpsUrl(options.updateUrl || `${options.apiBaseUrl}/updates/remote/latest.json`, "update URL").href;
  if (!options.updateUrl) return options;
  if (!new URL(options.updateUrl).pathname.endsWith(".json")) throw new Error("Update URL must name a JSON manifest.");
  options.downloadBaseUrl = httpsUrl(options.downloadBaseUrl || new URL(".", options.updateUrl).href, "download base URL").href.replace(/\/+$/, "");
  return options;
}

function buildEnvironment(source, options, targetDir) {
  const env = {};
  for (const key of Object.keys(source)) {
    if (!/^(PA_|VITE_|TAURI_)|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL/i.test(key)) env[key] = source[key];
  }
  if (options.mode === "release") {
    for (const key of ["TAURI_SIGNING_PRIVATE_KEY", "TAURI_SIGNING_PRIVATE_KEY_PASSWORD"]) {
      if (source[key] !== undefined) env[key] = source[key];
    }
  }
  return Object.assign(env, {
    NODE_ENV: "production", VITE_API_BASE_URL: options.apiBaseUrl, VITE_API_TOKEN: "", VITE_LOCAL_EXECUTOR: "true", CARGO_TARGET_DIR: targetDir,
  });
}

function bundleConfig(options, frontendDist, localExecutor = "binaries/private-agent-local", execHost = "binaries/exec-host", execManifest = "binaries/exec-host.sha256") {
  const config = {
    build: { beforeBuildCommand: null, frontendDist },
    bundle: { externalBin: [localExecutor, execHost], resources: { [execManifest]: "exec-host.sha256" }, createUpdaterArtifacts: options.mode === "release" },
  };
  if (options.mode !== "portable") {
    Object.assign(config, { version: options.version, productName: "PrivateAgentRemote", identifier: REMOTE_IDENTIFIER, mainBinaryName: REMOTE_BINARY });
    Object.assign(config.bundle, {
      targets: ["nsis"], shortDescription: "PrivateAgent 远程客户端",
      longDescription: "账号和模型连接 PrivateAgent 服务器，项目文件及任务在本机执行，无需安装数据库或模型服务。",
      // Remote install/uninstall must not stop another local edition's sidecar.
      windows: { nsis: { installerHooks: null } },
    });
    config.plugins = { updater: { endpoints: [options.updateUrl], windows: { installMode: "passive" } } };
  }
  if (options.unified) {
    Object.assign(config, { productName: "PrivateAgent", identifier: "com.personal-assistant.desktop", mainBinaryName: "privateagent" });
    config.bundle.shortDescription = "PrivateAgent 统一本地运行时";
    config.bundle.longDescription = "固定连接服务器账号，项目、任务与命令在本机运行，保留本机模型配置。";
    config.bundle.windows = { nsis: { installerHooks: null } };
    config.plugins = { updater: { endpoints: options.mode === "release" ? [options.updateUrl] : [] } };
  }
  return config;
}

function updateManifest(options, installerName, signature) {
  if (options.mode !== "release" || !signature.trim()) throw new Error("Only a signed release can have an update manifest.");
  if (path.basename(installerName) !== installerName || !installerName.endsWith("-setup.exe")) throw new Error("Expected an NSIS installer filename.");
  return {
    version: options.version, notes: `PrivateAgent ${options.unified ? "Unified" : "Remote"} v${options.version}`,
    pub_date: new Date().toISOString(),
    platforms: { [options.unified ? UNIFIED_TARGET : REMOTE_TARGET]: {
      url: `${options.downloadBaseUrl}/${options.version}/${encodeURIComponent(installerName)}`,
      signature: signature.trim(),
    } },
  };
}

function assertReleaseReady(options, dirty, signingConfigured) {
  if (options.mode !== "release") return;
  if (dirty) throw new Error("Signed releases require a clean Git working tree; use --preview-installer for local validation.");
  if (!signingConfigured) throw new Error("Updater signing is not configured. Use your existing protected signing environment; do not paste keys into commands or source files.");
}

function main(args = process.argv.slice(2)) {
  if (args.length === 1 && args[0] === "--help") {
    console.log('Usage: scripts\\build-remote-client.cmd "[fixed backend server]"');
    console.log("  --release --version 1.0.1       signed remote NSIS installer + publish/latest.json");
    console.log("  --preview-installer --version 1.0.1  unsigned installer for local QA; no update manifest");
    console.log("  --update-url HTTPS_URL         default: API_ORIGIN/updates/remote/latest.json");
    console.log("  --download-base-url HTTPS_URL  default: update manifest directory; assets live under VERSION/");
    console.log("  --dry-run                      validate options and print non-secret build configuration only");
    console.log("Output: a new .run/remote-client-* directory; no uploads or publication. Requires desktop dependencies and MSVC.");
    return;
  }
  const options = parseOptions(args);
  if (options.dryRun) {
    console.log(JSON.stringify({ ...options, updateTarget: options.mode === "portable" ? null : options.unified ? UNIFIED_TARGET : REMOTE_TARGET, config: bundleConfig(options, "<generated frontend>") }, null, 2));
    return;
  }
  if (process.platform !== "win32") throw new Error("This build script requires Windows x64 and MSVC.");
  const { apiBaseUrl } = options;
  const root = path.resolve(__dirname, "..");
  const desktop = path.join(root, "apps", "desktop");
  const tauriDir = path.join(desktop, "src-tauri");
  const cli = path.join(desktop, "node_modules", "@tauri-apps", "cli", "tauri.js");
  const typecheck = path.join(desktop, "node_modules", "vue-tsc", "bin", "vue-tsc.js");
  const vite = path.join(desktop, "node_modules", "vite", "bin", "vite.js");
  for (const file of [cli, typecheck, vite]) {
    if (!fs.existsSync(file)) throw new Error("Desktop dependencies are missing. Run npm ci in apps/desktop first.");
  }
  const env = buildEnvironment(process.env, options, path.join(tauriDir, "target"));
  function run(command, commandArgs, capture = false) {
    const result = spawnSync(command, commandArgs, {
      cwd: desktop, env, shell: false,
      ...(capture ? { encoding: "utf8" } : { stdio: "inherit" }),
    });
    if (result.error || result.status !== 0) throw new Error("Build command failed; keep the output and do not use an old executable.");
    return capture ? result.stdout.trim() : "";
  }
  run("cargo", ["--version"]);
  const commit = run("git", ["rev-parse", "HEAD"], true);
  const dirty = run("git", ["status", "--porcelain"], true).length > 0;
  assertReleaseReady(options, dirty, Boolean(env.TAURI_SIGNING_PRIVATE_KEY));
  const runDir = path.join(root, ".run");
  fs.mkdirSync(runDir, { recursive: true });
  const output = fs.mkdtempSync(path.join(runDir, options.unified ? "unified-client-" : "remote-client-"));
  const web = path.join(output, "web");
  console.log("Build output: " + output);
  const python = path.join(root, ".venv", "Scripts", "python.exe");
  if (!fs.existsSync(python)) throw new Error("Local executor packaging requires the existing project Python environment.");
  const localBin = path.join(output, "local-bin");
  const localName = "private-agent-local-x86_64-pc-windows-msvc";
  run("cargo", ["build", "--release", "--locked", "--manifest-path", path.join(root, "apps", "exec-host", "Cargo.toml")]);
  fs.mkdirSync(localBin, { recursive: true });
  const hostFile = path.join(env.CARGO_TARGET_DIR, "release", "exec-host.exe");
  const hostBytes = fs.readFileSync(hostFile);
  const hostSha = crypto.createHash("sha256").update(hostBytes).digest("hex");
  fs.copyFileSync(hostFile, path.join(localBin, "exec-host-x86_64-pc-windows-msvc.exe"), fs.constants.COPYFILE_EXCL);
  fs.writeFileSync(path.join(localBin, "exec-host.sha256"), hostSha + "\n", { flag: "wx" });
  run(python, ["-m", "PyInstaller", "--noconfirm", "--onefile", "--console", "--name", localName,
    "--paths", path.join(root, "src"), "--distpath", localBin,
    "--workpath", path.join(output, "pyinstaller-work"), "--specpath", output,
    "--exclude-module", "personal_assistant", "--exclude-module", "torch", "--exclude-module", "numpy",
    path.join(root, "src", "private_agent_local", "entry.py")]);
  run(process.execPath, [typecheck, "--noEmit"]);
  // Direct argv avoids cmd/npm double-quoting Windows paths that contain spaces.
  run(process.execPath, [vite, "build", "--outDir", web]);
  const index = fs.readFileSync(path.join(web, "index.html"), "utf8");
  const entry = index.match(/src="([^"]+\.js)"/);
  if (!entry) throw new Error("Built frontend entry was not found.");
  const entryFile = path.join(web, entry[1].replace(/^\//, ""));
  if (!fs.readFileSync(entryFile, "utf8").includes("account_server_origin")) {
    throw new Error("Built frontend must obtain the account server from the desktop backend.");
  }
  const triple = "x86_64-pc-windows-msvc";
  // An absolute Windows frontendDist is parsed as a URL by Tauri, omitting assets.
  const config = bundleConfig(options, path.relative(tauriDir, web).replaceAll("\\", "/"),
    path.relative(tauriDir, path.join(localBin, "private-agent-local")).replaceAll("\\", "/"),
    path.relative(tauriDir, path.join(localBin, "exec-host")).replaceAll("\\", "/"),
    path.relative(tauriDir, path.join(localBin, "exec-host.sha256")).replaceAll("\\", "/"));
  const configPath = path.join(output, "tauri-build.json");
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2) + "\n", { flag: "wx" });
  const buildFlags = options.mode === "portable" ? ["--no-bundle", "--no-sign"] : options.mode === "preview" ? ["--no-sign"] : [];
  const buildStarted = Date.now();
  run(process.execPath, [cli, "build", ...buildFlags, "--ci",
    "--target", triple, "--config", JSON.stringify(config), "--", "--locked"]);
  const builtExe = path.join(env.CARGO_TARGET_DIR, triple, "release", options.unified ? "privateagent.exe" : options.mode === "portable" ? "appsdesktop.exe" : `${REMOTE_BINARY}.exe`);
  const exeBytes = fs.readFileSync(builtExe);
  if (exeBytes.subarray(0, 2).toString() !== "MZ" || !exeBytes.includes(Buffer.from(entry[1].split("/").pop())) || !exeBytes.includes(Buffer.from(apiBaseUrl))) {
    throw new Error("Executable validation failed: missing PE header, current frontend entry or fixed backend account origin.");
  }
  const exeName = options.unified ? "PrivateAgent-windows-x64.exe" : "PrivateAgent-remote-windows-x64.exe";
  fs.copyFileSync(builtExe, path.join(output, exeName), fs.constants.COPYFILE_EXCL);
  const localBytes = fs.readFileSync(path.join(localBin, `${localName}.exe`));
  fs.copyFileSync(path.join(localBin, `${localName}.exe`), path.join(output, "private-agent-local.exe"), fs.constants.COPYFILE_EXCL);
  fs.copyFileSync(hostFile, path.join(output, "exec-host.exe"), fs.constants.COPYFILE_EXCL);
  fs.copyFileSync(path.join(localBin, "exec-host.sha256"), path.join(output, "exec-host.sha256"), fs.constants.COPYFILE_EXCL);
  const sha256 = crypto.createHash("sha256").update(exeBytes).digest("hex");
  let sums = `${sha256}  ${exeName}\n${crypto.createHash("sha256").update(localBytes).digest("hex")}  private-agent-local.exe\n${hostSha}  exec-host.exe\n`;
  if (options.mode !== "portable") {
    const installerName = `${options.unified ? "PrivateAgent" : "PrivateAgentRemote"}_${options.version}_x64-setup.exe`;
    const installer = path.join(env.CARGO_TARGET_DIR, triple, "release", "bundle", "nsis", installerName);
    if (!fs.existsSync(installer) || fs.statSync(installer).mtimeMs < buildStarted - 2000) throw new Error("Current remote installer was not generated; refusing stale artifacts.");
    if (options.mode === "release") {
      const sig = `${installer}.sig`;
      if (!fs.existsSync(sig)) throw new Error("Remote installer signature was not generated.");
      const publicKey = JSON.parse(fs.readFileSync(path.join(tauriDir, "tauri.conf.json"), "utf8")).plugins.updater.pubkey;
      const publicKeyFile = path.join(output, "updater-public-key.txt");
      fs.writeFileSync(publicKeyFile, publicKey + "\n", { flag: "wx" });
      // A valid signature from the wrong key would brick client updates; verify before publishing a manifest.
      run("cargo", ["run", "--release", "--locked", "--manifest-path", path.join(root, "scripts", "windows", "updater-signature-verifier", "Cargo.toml"), "--", installer, sig, publicKeyFile]);
      const publish = path.join(output, "publish");
      const assets = path.join(publish, options.version);
      fs.mkdirSync(assets, { recursive: true });
      fs.copyFileSync(installer, path.join(assets, installerName), fs.constants.COPYFILE_EXCL);
      fs.copyFileSync(sig, path.join(assets, `${installerName}.sig`), fs.constants.COPYFILE_EXCL);
      fs.writeFileSync(path.join(publish, "latest.json"), JSON.stringify(updateManifest(options, installerName, fs.readFileSync(sig, "utf8")), null, 2) + "\n", { flag: "wx" });
      sums += `${crypto.createHash("sha256").update(fs.readFileSync(installer)).digest("hex")}  publish/${options.version}/${installerName}\n`;
      console.log("Verified update artifacts (not uploaded): " + publish);
    } else {
      fs.copyFileSync(installer, path.join(output, installerName), fs.constants.COPYFILE_EXCL);
      sums += `${crypto.createHash("sha256").update(fs.readFileSync(installer)).digest("hex")}  ${installerName}\n`;
      console.log("UNSIGNED INSTALLER PREVIEW: local QA only; no latest.json was generated. Do not publish as an update.");
    }
  }
  fs.writeFileSync(path.join(output, "SHA256SUMS.txt"), sums, { flag: "wx" });
  fs.writeFileSync(path.join(output, "build-info.json"), JSON.stringify({
    commit, dirty, apiBaseUrl, unified: Boolean(options.unified), transport: "stdio-v2", executionHostSha256: hostSha,
    target: triple, signing: options.mode === "release" ? "updater-verified" : "unsigned", sidecar: "desktop-local",
    mode: options.mode, updateTarget: options.mode === "portable" ? null : options.unified ? UNIFIED_TARGET : REMOTE_TARGET,
    updateUrl: options.updateUrl || null, downloadBaseUrl: options.downloadBaseUrl || null,
    version: options.version || JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8")).version,
    createdAt: new Date().toISOString(), sha256, node: process.version,
  }, null, 2) + "\n", { flag: "wx" });
  console.log("Client EXE: " + path.join(output, exeName));
  console.log("SHA256: " + sha256);
  if (options.mode === "portable") console.log("Unsigned test build. Keep private-agent-local.exe, exec-host.exe and exec-host.sha256 beside the client. Requires WebView2. Do not use the in-app updater.");
  if (dirty) console.log("Source has uncommitted changes; build-info.json records dirty=true.");
}

module.exports = { main, parseOptions, buildEnvironment, bundleConfig, updateManifest, assertReleaseReady, REMOTE_TARGET, REMOTE_IDENTIFIER, UNIFIED_TARGET };

if (require.main === module) {
  try { main(); } catch (error) {
    console.error(error instanceof Error ? error.message : "Remote client build failed.");
    process.exitCode = 1;
  }
}
