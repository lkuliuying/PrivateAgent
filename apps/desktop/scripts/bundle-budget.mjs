/**
 * v0.8.0 W4 · bundle 预算基线（计划 §7 W4 任务 5）
 *
 * 用法：
 *   node scripts/bundle-budget.mjs            # 对照基线检查（超基线+10% 失败，+5% 警告）
 *   node scripts/bundle-budget.mjs --update   # 以当前 dist 重写基线（需人工评审后提交）
 *
 * 尺寸为 gzip 字节；chunk 归类按文件名前缀（index/vendor/tauri/css）。
 * 基线文件 scripts/bundle-baseline.json 随仓库演进，重定预算须附分布对照
 * （对齐 E-1 原则：不允许以放宽预算掩盖真实回归）。
 */
import { readFileSync, readdirSync, writeFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const HARD_RATIO = 1.1;
const WARN_RATIO = 1.05;

const baselineUrl = new URL("./bundle-baseline.json", import.meta.url);
const assetsDir = join(process.cwd(), "dist", "assets");

if (!existsSync(assetsDir)) {
  console.error("bundle-budget: dist/assets 不存在，请先执行 npm run build");
  process.exit(1);
}

function classify(name) {
  if (name.startsWith("vendor-")) return "vendor";
  if (name.startsWith("tauri-")) return "tauri";
  if (name.startsWith("index-") && name.endsWith(".js")) return "index";
  if (name.endsWith(".css")) return "css";
  return null;
}

const measured = {};
for (const file of readdirSync(assetsDir)) {
  if (!/\.(js|css)$/.test(file)) continue;
  const key = classify(file);
  if (!key) continue;
  const gz = gzipSync(readFileSync(join(assetsDir, file))).length;
  measured[key] = (measured[key] ?? 0) + gz;
}

if (process.argv.includes("--update")) {
  writeFileSync(baselineUrl, JSON.stringify(measured, null, 2) + "\n", "utf8");
  console.log("bundle-budget: 基线已更新", measured);
  process.exit(0);
}

const baseline = JSON.parse(readFileSync(baselineUrl, "utf8"));
let failed = false;
for (const [key, base] of Object.entries(baseline)) {
  const size = measured[key] ?? 0;
  const ratio = size / base;
  const tag = ratio > HARD_RATIO ? "FAIL" : ratio > WARN_RATIO ? "WARN" : "OK";
  if (ratio > HARD_RATIO) failed = true;
  console.log(
    `${tag}  ${key.padEnd(8)} ${(size / 1024).toFixed(1)} kB gzip / 基线 ${(base / 1024).toFixed(1)} kB (${(ratio * 100).toFixed(1)}%)`
  );
}
for (const key of Object.keys(measured)) {
  if (!(key in baseline)) {
    console.warn(`WARN  ${key} 为基线外新增 chunk（${(measured[key] / 1024).toFixed(1)} kB gzip），请评审后纳入基线`);
  }
}
process.exit(failed ? 1 : 0);
