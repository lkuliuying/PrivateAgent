import { afterEach, describe, expect, it, vi } from "vitest";
import { copyAnswerText } from "./copyAnswerText";

describe("copyAnswerText（W6-R2 回答复制）", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("剪贴板可用：写入完整回答（保留换行，去除尾部空白）", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const result = await copyAnswerText("第一行\n第二行  \n");
    expect(result).toBe("ok");
    expect(writeText).toHaveBeenCalledWith("第一行\n第二行");
  });

  it("剪贴板写入被拒绝：回退成功仍返回 ok", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    const execCommand = vi.fn().mockReturnValue(true);
    document.execCommand = execCommand;
    const result = await copyAnswerText("回答正文");
    expect(result).toBe("ok");
    expect(execCommand).toHaveBeenCalledWith("copy");
    // 临时 textarea 不保留在 DOM 中
    expect(document.querySelector("textarea[aria-hidden]")).toBeNull();
  });

  it("剪贴板不可用且回退失败：返回 failed（组件给出可恢复提示）", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    document.execCommand = vi.fn().mockReturnValue(false);
    const result = await copyAnswerText("回答正文");
    expect(result).toBe("failed");
  });

  it("空回答返回 failed（不复制按钮文案或隐藏内容）", async () => {
    const result = await copyAnswerText("   \n ");
    expect(result).toBe("failed");
  });
});
