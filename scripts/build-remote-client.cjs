// 统一客户端与历史远程客户端共用构建、更新签名验证及发布产物保护。
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

const DEFAULT_UPDATE_URL = "https://www.liuyingapi.top/updates/remote/latest.json";

const REMOTE_IDENTIFIER = "com.personal-assistant.desktop.remote";
const REMOTE_TARGET = "remote-windows-x86_64";
const UNIFIED_TARGET = "unified-windows-x86_64";
const REMOTE_BINARY = "privateagent-remote";

function githubRepository(value) {
  const parts = value.split("/");
  if (/\s/.test(value) || parts.length !== 2 || !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/.test(parts[0]) ||
      parts[0].includes("--") || !/^[A-Za-z0-9_.-]{1,100}$/.test(parts[1]) || [".", ".."].includes(parts[1])) {
    // 输入可能误含访问令牌，错误信息不得回显仓库参数。
    throw new Error("GitHub repository must be a valid owner/repo without a URL, credentials, query or fragment.");
  }
  return value;
}

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
  const values = new Set(["--version", "--update-url", "--download-base-url", "--github-repo"]);
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--release" || arg === "--preview-installer") {
      if (options.mode !== "portable") throw new Error("Choose one installer mode.");
      options.mode = arg === "--release" ? "release" : "preview";
    } else if (arg === "--unified") {
      options.unified = true;
    } else if (arg === "--qa") {
      options.qa = true;
    } else if (arg === "--dry-run") {
      options.dryRun = true;
    } else if (values.has(arg)) {
      const value = args[++i];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${arg}.`);
      const key = { "--version": "version", "--update-url": "updateUrl", "--download-base-url": "downloadBaseUrl", "--github-repo": "githubRepo" }[arg];
      if (options[key]) throw new Error(`Duplicate ${arg}.`);
      options[key] = value;
    } else {
      throw new Error("Unknown option; platform API origins are no longer supported. Use --help.");
    }
  }
  if (options.githubRepo) {
    options.githubRepo = githubRepository(options.githubRepo);
    if (!options.unified || options.mode !== "release" || options.qa) throw new Error("--github-repo requires a unified release without QA mode.");
    if (options.updateUrl || options.downloadBaseUrl) throw new Error("--github-repo cannot be combined with --update-url or --download-base-url.");
  }
  if (options.qa && (!options.unified || options.mode !== "preview" || options.updateUrl || options.downloadBaseUrl)) {
    throw new Error("QA requires --unified --preview-installer and cannot configure update channels.");
  }
  if (options.mode === "portable") {
    if (options.version || options.updateUrl || options.downloadBaseUrl) {
      throw new Error("Version and update URLs require --release or --preview-installer.");
    }
    return options;
  }
  if (/\s/.test(options.version || "") || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(options.version || "")) {
    throw new Error("Installer builds require --version with a stable version, for example 1.0.1.");
  }
  if (options.githubRepo) {
    options.releaseTag = `v${options.version}`;
    options.updateUrl = `https://github.com/${options.githubRepo}/releases/latest/download/latest.json`;
    options.downloadBaseUrl = `https://github.com/${options.githubRepo}/releases/download/${options.releaseTag}`;
    return options;
  }
  if (options.unified && options.mode === "release" && !options.updateUrl) throw new Error("Unified releases require an explicit independent --update-url or --github-repo; old channels must not be reused implicitly.");
  options.updateUrl = options.unified && options.mode === "preview" && !options.updateUrl ? "" : httpsUrl(options.updateUrl || DEFAULT_UPDATE_URL, "update URL").href;
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
    NODE_ENV: "production", VITE_LOCAL_EXECUTOR: "true", CARGO_TARGET_DIR: targetDir,
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
      longDescription: "使用自备 API Key 直连模型供应商，项目文件及任务在本机执行，支持技术文档 MCP，无需平台账号。",
      // Remote install/uninstall must not stop another local edition's sidecar.
      windows: { nsis: { installerHooks: null } },
    });
    config.plugins = { updater: { endpoints: [options.updateUrl], windows: { installMode: "passive" } } };
  }
  if (options.unified) {
    Object.assign(config, { productName: "PrivateAgent", identifier: "com.personal-assistant.desktop", mainBinaryName: "privateagent" });
    config.bundle.shortDescription = "PrivateAgent 统一本地运行时";
    config.bundle.longDescription = "使用本机模型配置与 API Key，项目、任务、命令及技术文档 MCP 在本机工作区运行，无需平台账号。";
    config.bundle.windows = { nsis: { installerHooks: null } };
    // 测试安装包可显式检查正式更新源，仍保留公钥验签且不生成可发布更新产物。
    config.plugins = { updater: { endpoints: options.updateUrl ? [options.updateUrl] : [] } };
  }
  if (options.qa) {
    // 独立安装名称、标识和数据目录，候选包不会覆盖用户的正式客户端。
    Object.assign(config, { productName: "PrivateAgentCandidate", identifier: "com.personal-assistant.desktop.candidate", mainBinaryName: "privateagent-candidate" });
    config.app = { windows: [{ title: `PrivateAgent 候选版 ${options.version}`, width: 1200, height: 800, minWidth: 900, minHeight: 600 }] };
  }
  return config;
}

function updateManifest(options, installerName, signature) {
  if (options.mode !== "release" || !signature.trim()) throw new Error("Only a signed release can have an update manifest.");
  if (path.basename(installerName) !== installerName || !installerName.endsWith("-setup.exe")) throw new Error("Expected an NSIS installer filename.");
  if (options.unified && installerName !== `PrivateAgent_${options.version}_x64-setup.exe`) throw new Error("Unified releases require the exact PrivateAgent versioned x64 NSIS installer filename.");
  return {
    version: options.version, notes: `PrivateAgent ${options.unified ? "Unified" : "Remote"} v${options.version}`,
    pub_date: new Date().toISOString(),
    platforms: { [options.unified ? UNIFIED_TARGET : REMOTE_TARGET]: {
      url: `${options.downloadBaseUrl}/${options.githubRepo ? "" : `${options.version}/`}${encodeURIComponent(installerName)}`,
      signature: signature.trim(),
    } },
  };
}

function writeReleaseArtifacts(options, installer, signatureFile, output) {
  const installerName = path.basename(installer);
  const manifest = updateManifest(options, installerName, fs.readFileSync(signatureFile, "utf8"));
  const publish = path.join(output, "publish");
  const assets = path.join(publish, options.version);
  fs.mkdirSync(assets, { recursive: true });
  fs.copyFileSync(installer, path.join(assets, installerName), fs.constants.COPYFILE_EXCL);
  fs.copyFileSync(signatureFile, path.join(assets, `${installerName}.sig`), fs.constants.COPYFILE_EXCL);
  fs.writeFileSync(path.join(publish, "latest.json"), JSON.stringify(manifest, null, 2) + "\n", { flag: "wx" });
  const files = [`publish/${options.version}/${installerName}`, `publish/${options.version}/${installerName}.sig`, "publish/latest.json"];
  return files.map(file => `${crypto.createHash("sha256").update(fs.readFileSync(path.join(output, file))).digest("hex")}  ${file}\n`).join("");
}

function assertReleaseReady(options, dirty, signingConfigured) {
  if (options.mode !== "release") return;
  if (dirty) throw new Error("Signed releases require a clean Git working tree; use --preview-installer for local validation.");
  if (!signingConfigured) throw new Error("Updater signing is not configured. Use your existing protected signing environment; do not paste keys into commands or source files.");
}

function collectSourceManifest(root, desktop, run) {
  const inputs = ["../../src", "src", "src-tauri", "../../apps/exec-host", "../../pyproject.toml", "../../requirements.txt", "../../uv.lock",
    "package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json", "tsconfig.node.json",
    "../../scripts/build-client.cjs", "../../scripts/build-remote-client.cjs"];
  const listed = run("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", ...inputs], true);
  const deleted = new Set(run("git", ["ls-files", "-z", "--deleted", "--", ...inputs], true).split("\0"));
  // 仅排除 Git 确认的工作树删除；其余读取失败仍中止构建，结束时重新枚举以检测集合变化。
  return [...new Set(listed.split("\0").filter(file => file && !deleted.has(file)))].sort().map(file => ({
    path: path.relative(root, path.resolve(desktop, file)).replaceAll("\\", "/"),
    sha256: crypto.createHash("sha256").update(fs.readFileSync(path.resolve(desktop, file))).digest("hex"),
  }));
}

function main(args = process.argv.slice(2)) {
  if (args.length === 1 && args[0] === "--help") {
    console.log('Usage: scripts\\build-remote-client.cmd [options]');
    console.log("  --release --version 1.0.1       signed remote NSIS installer + publish/latest.json");
    console.log("  --preview-installer --version 1.0.1  unsigned installer for local QA; no update manifest");
    console.log("  --unified --preview-installer --version 1.0.0 --update-url HTTPS_JSON  test installer with an explicit update source; unsigned, no manifest");
    console.log("  --unified --qa                independently identified local acceptance installer");
    console.log("  --unified --release --version 1.0.0 --github-repo lkuliuying/PrivateAgent  GitHub Release update source");
    console.log("  --update-url HTTPS_URL         default: built-in update manifest");
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
  const sourceManifest = () => collectSourceManifest(root, desktop, run);
  const sources = sourceManifest();
  const sourceSha256 = crypto.createHash("sha256").update(JSON.stringify(sources)).digest("hex");
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
  const entrySource = fs.readFileSync(entryFile, "utf8");
  if (!entrySource.includes("/identity/local") || entrySource.includes("account_server_origin")) {
    throw new Error("Built frontend must initialize a local workspace without platform login.");
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
  run(process.execPath, [cli, "build", ...buildFlags, ...(options.qa ? ["--features", "qa"] : []), "--ci",
    "--target", triple, "--config", JSON.stringify(config), "--", "--locked"]);
  const builtExe = path.join(env.CARGO_TARGET_DIR, triple, "release", options.qa ? "privateagent-candidate.exe" : options.unified ? "privateagent.exe" : options.mode === "portable" ? "appsdesktop.exe" : `${REMOTE_BINARY}.exe`);
  const exeBytes = fs.readFileSync(builtExe);
  if (exeBytes.subarray(0, 2).toString() !== "MZ" || !exeBytes.includes(Buffer.from(entry[1].split("/").pop()))) {
    throw new Error("Executable validation failed: missing PE header, current frontend entry.");
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
    const installerName = `${options.qa ? "PrivateAgentCandidate" : options.unified ? "PrivateAgent" : "PrivateAgentRemote"}_${options.version}_x64-setup.exe`;
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
      sums += writeReleaseArtifacts(options, installer, sig, output);
      console.log("Verified update artifacts (not uploaded): " + path.join(output, "publish"));
    } else {
      fs.copyFileSync(installer, path.join(output, installerName), fs.constants.COPYFILE_EXCL);
      sums += `${crypto.createHash("sha256").update(fs.readFileSync(installer)).digest("hex")}  ${installerName}\n`;
      console.log("UNSIGNED INSTALLER PREVIEW: local QA only; no latest.json was generated. Do not publish as an update.");
    }
  }
  fs.writeFileSync(path.join(output, "SHA256SUMS.txt"), sums, { flag: "wx" });
  if (JSON.stringify(sourceManifest()) !== JSON.stringify(sources)) throw new Error("Source changed during build; this candidate is not verified.");
  fs.writeFileSync(path.join(output, "source-manifest.json"), JSON.stringify({ sourceSha256, sources }, null, 2) + "\n", { flag: "wx" });
  fs.writeFileSync(path.join(output, "build-info.json"), JSON.stringify({
    commit, dirty, accessMode: "api-key", unified: Boolean(options.unified), qa: Boolean(options.qa), applicationIdentifier: config.identifier,
    transport: "stdio-v2", executionHostSha256: hostSha, sourceSha256,
    target: triple, signing: options.mode === "release" ? "updater-verified" : "unsigned", sidecar: "desktop-local",
    mode: options.mode, updateTarget: options.mode === "portable" ? null : options.unified ? UNIFIED_TARGET : REMOTE_TARGET,
    updateUrl: options.updateUrl || null, downloadBaseUrl: options.downloadBaseUrl || null,
    githubRepo: options.githubRepo || null, releaseTag: options.releaseTag || null,
    version: options.version || JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8")).version,
    createdAt: new Date().toISOString(), sha256, node: process.version,
  }, null, 2) + "\n", { flag: "wx" });
  console.log("Client EXE: " + path.join(output, exeName));
  console.log("SHA256: " + sha256);
  if (options.mode === "portable") console.log("Unsigned test build. Keep private-agent-local.exe, exec-host.exe and exec-host.sha256 beside the client. Requires WebView2. Do not use the in-app updater.");
  if (dirty) console.log("Source has uncommitted changes; build-info.json records dirty=true.");
}

module.exports = { main, parseOptions, buildEnvironment, bundleConfig, updateManifest, writeReleaseArtifacts, assertReleaseReady, collectSourceManifest, REMOTE_TARGET, REMOTE_IDENTIFIER, UNIFIED_TARGET };

if (require.main === module) {
  try { main(); } catch (error) {
    console.error(error instanceof Error ? error.message : "Remote client build failed.");
    process.exitCode = 1;
  }
}
