import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const distRoot = join(projectRoot, "dist");
const manifestPath = join(distRoot, ".vite", "manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const entries = Object.entries(manifest);
const entry = entries.find(([, value]) => value.isEntry);

if (!entry) throw new Error("Bundle budget: Vite manifest 中没有入口资源");

const reachable = new Set();
function visit(key) {
  if (reachable.has(key)) return;
  const record = manifest[key];
  if (!record) throw new Error(`Bundle budget: manifest 缺少静态依赖 ${key}`);
  reachable.add(key);
  for (const imported of record.imports || []) visit(imported);
}
visit(entry[0]);

const gzipBytes = (relativePath) =>
  gzipSync(readFileSync(join(distRoot, relativePath))).byteLength;
const initialRecords = [...reachable].map((key) => manifest[key]);
const initialJs = [...new Set(initialRecords.map((record) => record.file))];
const initialCss = [
  ...new Set(initialRecords.flatMap((record) => record.css || [])),
];
const initialJsGzip = initialJs.reduce((sum, file) => sum + gzipBytes(file), 0);
const initialCssGzip = initialCss.reduce((sum, file) => sum + gzipBytes(file), 0);

const assetRoot = join(distRoot, "assets");
const jsAssets = readdirSync(assetRoot)
  .filter((file) => file.endsWith(".js"))
  .map((file) => ({ file, bytes: statSync(join(assetRoot, file)).size }));
const largestChunk = jsAssets.reduce(
  (largest, asset) => (asset.bytes > largest.bytes ? asset : largest),
  { file: "--", bytes: 0 }
);

const kib = (bytes) => bytes / 1024;
const limits = {
  initialJsGzip: Number(process.env.PA_MAX_INITIAL_JS_GZIP_KIB || 160) * 1024,
  initialCssGzip: Number(process.env.PA_MAX_INITIAL_CSS_GZIP_KIB || 32) * 1024,
  chunkRaw: Number(process.env.PA_MAX_CHUNK_RAW_KIB || 400) * 1024,
};

console.log(
  `Bundle budget: startup JS ${kib(initialJsGzip).toFixed(1)} KiB gzip, ` +
    `startup CSS ${kib(initialCssGzip).toFixed(1)} KiB gzip, ` +
    `largest chunk ${largestChunk.file} ${kib(largestChunk.bytes).toFixed(1)} KiB raw`
);

const failures = [];
if (initialJsGzip > limits.initialJsGzip) {
  failures.push(
    `启动 JS ${kib(initialJsGzip).toFixed(1)} KiB 超过 ${kib(limits.initialJsGzip).toFixed(0)} KiB`
  );
}
if (initialCssGzip > limits.initialCssGzip) {
  failures.push(
    `启动 CSS ${kib(initialCssGzip).toFixed(1)} KiB 超过 ${kib(limits.initialCssGzip).toFixed(0)} KiB`
  );
}
if (largestChunk.bytes > limits.chunkRaw) {
  failures.push(
    `最大 JS chunk ${largestChunk.file} ${kib(largestChunk.bytes).toFixed(1)} KiB 超过 ${kib(limits.chunkRaw).toFixed(0)} KiB`
  );
}

if (failures.length) {
  throw new Error(`Bundle budget failed:\n- ${failures.join("\n- ")}`);
}
