export interface WorkspaceFileTarget {
  path: string;
  line?: number;
}

export interface WorkspaceFileOpenRequest extends WorkspaceFileTarget {
  requestId: number;
}

export function isAbsoluteWorkspacePath(path: string): boolean {
  return path.startsWith("/") || /^[a-z]:\//i.test(path);
}

/** 只解析文件引用；是否可读仍由工作区只读接口的路径与权限校验决定。 */
export function parseWorkspaceFileTarget(source: string | null | undefined): WorkspaceFileTarget | null {
  return parseFileTarget(source, true);
}

function parseFileTarget(source: string | null | undefined, decode: boolean): WorkspaceFileTarget | null {
  if (!source) return null;
  let value = source.trim();
  if (value.startsWith("<") && value.endsWith(">")) value = value.slice(1, -1);
  if (decode) {
    try { value = decodeURIComponent(value); } catch { return null; }
  }
  if (!value || value.length > 2048 || /[\x00-\x1f\x7f]/.test(value)) return null;
  value = value.replace(/\\/g, "/");
  if (/^\/[a-z]:\//i.test(value)) value = value.slice(1);
  if (value.startsWith("//") || value.endsWith("/")) return null;

  const location = /(?::([1-9]\d*)(?::[1-9]\d*)?|#L([1-9]\d*)(?:C[1-9]\d*)?)$/.exec(value);
  const line = location ? Number(location[1] ?? location[2]) : undefined;
  if (line !== undefined && !Number.isSafeInteger(line)) return null;
  if (location) value = value.slice(0, location.index);
  const drive = /^[a-z]:\//i.test(value) ? value.slice(0, 3) : "";
  const absolute = !drive && value.startsWith("/");
  const remainder = value.slice(drive ? 3 : absolute ? 1 : 0);
  if (!remainder || /[:?#*<>|]/.test(remainder)) return null;
  const parts = remainder.split("/");
  if (parts.some(part => part === ".." || !part)) return null;
  const path = `${drive || (absolute ? "/" : "")}${parts.filter(part => part !== ".").join("/")}`;
  if (!path || path === "/" || /^[a-z]:\/$/i.test(path) || path.length > 1024) return null;
  return { path, ...(line === undefined ? {} : { line }) };
}

/** 将本机绝对路径收敛到当前任务工作区，禁止相邻前缀与父目录穿越。 */
export function resolveWorkspaceFileTarget(target: WorkspaceFileTarget, workspaceRoot?: string | null): WorkspaceFileTarget | null {
  const parsed = parseFileTarget(target.path, false);
  if (!parsed || (target.line !== undefined && (!Number.isSafeInteger(target.line) || target.line < 1))) return null;
  if (!isAbsoluteWorkspacePath(parsed.path)) return { path: parsed.path, ...(target.line === undefined ? {} : { line: target.line }) };
  if (!workspaceRoot) return null;
  let root = workspaceRoot.replace(/\\/g, "/").replace(/\/+$/, "");
  if (/^\/[a-z]:\//i.test(root)) root = root.slice(1);
  if (!root && workspaceRoot === "/") root = "/";
  if (/^[a-z]:$/i.test(root)) root += "/";
  if (!isAbsoluteWorkspacePath(root) || root.startsWith("//") || root.split("/").includes("..")) return null;
  const prefix = root.endsWith("/") ? root : `${root}/`;
  const windows = /^[a-z]:\//i.test(parsed.path);
  if (!(windows ? parsed.path.toLowerCase().startsWith(prefix.toLowerCase()) : parsed.path.startsWith(prefix))) return null;
  const relative = parseFileTarget(parsed.path.slice(prefix.length), false);
  return relative ? { path: relative.path, ...(target.line === undefined ? {} : { line: target.line }) } : null;
}
