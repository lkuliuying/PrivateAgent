// 统一构建复用原有签名验证和发布保护；默认仅产生本机便携验证包。
const { main } = require("./build-remote-client.cjs");
try {
  if (process.argv.slice(2).includes("--help")) {
    console.log("Usage: scripts\\build-client.cmd [HTTPS_ACCOUNT_ORIGIN] [--dry-run]");
    console.log("  --preview-installer --version X.Y.Z: unsigned local installer; no update manifest");
    console.log("  --release --version X.Y.Z --update-url HTTPS_JSON: clean tree and existing protected signing environment required");
    console.log("Default: local model mode, unsigned portable validation bundle. No upload or installation.");
  } else main(["--unified", ...process.argv.slice(2)]);
} catch (error) {
  console.error(error instanceof Error ? error.message : "统一客户端构建失败");
  process.exitCode = 1;
}
