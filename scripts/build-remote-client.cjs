// Build an unsigned Windows remote client without a Python sidecar or credentials.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--help") {
    console.log('Usage: scripts\\build-remote-client.cmd "https://api.example.com"');
    console.log("Output: a new .run/remote-client-* directory; requires installed desktop dependencies and MSVC.");
    return;
  }
  if (process.platform !== "win32") throw new Error("This build script requires Windows x64 and MSVC.");
  if (args.length !== 1) throw new Error("Provide exactly one HTTPS API origin (no credentials, query or path).");
  // Do not include the supplied value in errors: a mistaken URL may contain a secret.
  let url;
  try { url = new URL(args[0]); } catch { throw new Error("Invalid API origin."); }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash || url.pathname !== "/") {
    throw new Error("API origin must use HTTPS and must not contain credentials, a query, fragment or path.");
  }
  const apiBaseUrl = url.origin;
  const root = path.resolve(__dirname, "..");
  const desktop = path.join(root, "apps", "desktop");
  const tauriDir = path.join(desktop, "src-tauri");
  const cli = path.join(desktop, "node_modules", "@tauri-apps", "cli", "tauri.js");
  const typecheck = path.join(desktop, "node_modules", "vue-tsc", "bin", "vue-tsc.js");
  const vite = path.join(desktop, "node_modules", "vite", "bin", "vite.js");
  for (const file of [cli, typecheck, vite]) {
    if (!fs.existsSync(file)) throw new Error("Desktop dependencies are missing. Run npm ci in apps/desktop first.");
  }
  // Inherit tool/runtime paths, not application or signing credentials.
  const env = {};
  for (const key of Object.keys(process.env)) {
    if (!/^(PA_|VITE_|TAURI_SIGNING_)|TOKEN|SECRET|PASSWORD|PRIVATE_KEY|CREDENTIAL/i.test(key)) {
      env[key] = process.env[key];
    }
  }
  Object.assign(env, {
    NODE_ENV: "production",
    VITE_API_BASE_URL: apiBaseUrl,
    VITE_API_TOKEN: "",
    CARGO_TARGET_DIR: path.join(tauriDir, "target"),
  });
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
  const runDir = path.join(root, ".run");
  fs.mkdirSync(runDir, { recursive: true });
  const output = fs.mkdtempSync(path.join(runDir, "remote-client-"));
  const web = path.join(output, "web");
  console.log("Build output: " + output);
  run(process.execPath, [typecheck, "--noEmit"]);
  // Direct argv avoids cmd/npm double-quoting Windows paths that contain spaces.
  run(process.execPath, [vite, "build", "--outDir", web]);
  const index = fs.readFileSync(path.join(web, "index.html"), "utf8");
  const entry = index.match(/src="([^"]+\.js)"/);
  if (!entry) throw new Error("Built frontend entry was not found.");
  const entryFile = path.join(web, entry[1].replace(/^\//, ""));
  if (!fs.readFileSync(entryFile, "utf8").includes(apiBaseUrl)) {
    throw new Error("Remote API origin is missing from the built frontend.");
  }
  const triple = "x86_64-pc-windows-msvc";
  const config = {
    build: {
      beforeBuildCommand: null,
      // An absolute Windows path is parsed as a URL by Tauri, omitting assets.
      frontendDist: path.relative(tauriDir, web).replaceAll("\\", "/"),
    },
    bundle: { externalBin: [], createUpdaterArtifacts: false },
  };
  run(process.execPath, [cli, "build", "--no-bundle", "--no-sign", "--ci",
    "--target", triple, "--config", JSON.stringify(config), "--", "--locked"]);
  const builtExe = path.join(env.CARGO_TARGET_DIR, triple, "release", "appsdesktop.exe");
  const exeBytes = fs.readFileSync(builtExe);
  if (exeBytes.subarray(0, 2).toString() !== "MZ" || !exeBytes.includes(Buffer.from(entry[1].split("/").pop()))) {
    throw new Error("Executable validation failed: missing PE header or current frontend entry.");
  }
  const exeName = "PrivateAgent-remote-windows-x64.exe";
  fs.copyFileSync(builtExe, path.join(output, exeName), fs.constants.COPYFILE_EXCL);
  const sha256 = crypto.createHash("sha256").update(exeBytes).digest("hex");
  fs.writeFileSync(path.join(output, "SHA256SUMS.txt"), `${sha256}  ${exeName}\n`, { flag: "wx" });
  fs.writeFileSync(path.join(output, "build-info.json"), JSON.stringify({
    commit, dirty, apiBaseUrl, target: triple, signing: "unsigned", sidecar: false,
    version: JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8")).version,
    createdAt: new Date().toISOString(), sha256, node: process.version,
  }, null, 2) + "\n", { flag: "wx" });
  console.log("Client EXE: " + path.join(output, exeName));
  console.log("SHA256: " + sha256);
  console.log("Unsigned test build. Requires WebView2. Do not use the in-app updater.");
  if (dirty) console.log("Source has uncommitted changes; build-info.json records dirty=true.");
}

try { main(); } catch (error) {
  console.error(error instanceof Error ? error.message : "Remote client build failed.");
  process.exitCode = 1;
}
