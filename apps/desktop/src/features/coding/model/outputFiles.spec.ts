import { describe, expect, it } from "vitest";
import { parseWorkspaceFileTarget, resolveWorkspaceFileTarget } from "./outputFiles";

describe("输出文件引用", () => {
  it.each([
    ["./src/app.py:42", { path: "src/app.py", line: 42 }],
    ["src/app.py#L7C2", { path: "src/app.py", line: 7 }],
    ["F:\\Project\\src\\app.py:3:2", { path: "F:/Project/src/app.py", line: 3 }],
    ["</F:/My Project/说明.md:2>", { path: "F:/My Project/说明.md", line: 2 }],
    ["docs/My%20Report.md", { path: "docs/My Report.md" }],
    ["README.md", { path: "README.md" }],
  ])("解析 %s", (source, expected) => expect(parseWorkspaceFileTarget(source as string)).toEqual(expected));

  it.each([
    "javascript:alert(1)", "data:text/html,x", "file:///F:/Project/app.py", "https://example.com/file",
    "//server/share/a.txt", "\\\\server\\share\\a.txt", "../outside.txt", "src/../../outside.txt",
    "%2e%2e/outside.txt", "src/%2e%2e/outside.txt", "src/app.py:0", "src/app.py#L0",
    "src/app.py:9007199254740992", "src/app.py?download=1", "src/a\u0000.txt", "src/", "%zz", "C:relative.txt",
  ])("拒绝协议、网络路径、穿越和无效位置 %s", (source) => expect(parseWorkspaceFileTarget(source)).toBeNull());

  it("Windows 绝对路径按完整目录边界映射，保留路径大小写和行号", () => {
    expect(resolveWorkspaceFileTarget({ path: "f:/PROJECT/src/Main.py", line: 3 }, "F:\\Project\\"))
      .toEqual({ path: "src/Main.py", line: 3 });
    expect(resolveWorkspaceFileTarget({ path: "F:/Project-copy/a.txt" }, "F:/Project")).toBeNull();
    expect(resolveWorkspaceFileTarget({ path: "G:/Project/a.txt" }, "F:/Project")).toBeNull();
    expect(resolveWorkspaceFileTarget({ path: "F:/Project/../other/a.txt" }, "F:/Project")).toBeNull();
  });

  it("POSIX 路径区分大小写，相对路径无需获取绝对目录", () => {
    expect(resolveWorkspaceFileTarget({ path: "/work/repo/src/a.py" }, "/work/repo")).toEqual({ path: "src/a.py" });
    expect(resolveWorkspaceFileTarget({ path: "/Work/repo/a.py" }, "/work/repo")).toBeNull();
    expect(resolveWorkspaceFileTarget({ path: "src/a.py", line: 5 })).toEqual({ path: "src/a.py", line: 5 });
    expect(resolveWorkspaceFileTarget({ path: "src/a.py", line: -1 })).toBeNull();
    expect(resolveWorkspaceFileTarget({ path: "/work/repo/a.py" })).toBeNull();
    expect(resolveWorkspaceFileTarget({ path: "C:/a.py" }, "C:/")).toEqual({ path: "a.py" });
  });

  it("解析后不再次解码，百分号文件名不被改指到另一文件", () => {
    const target = parseWorkspaceFileTarget("docs/value%2520.txt");
    expect(target).toEqual({ path: "docs/value%20.txt" });
    expect(resolveWorkspaceFileTarget(target!)).toEqual(target);
  });
});
