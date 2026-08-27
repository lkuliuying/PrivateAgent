import { describe, expect, it } from "vitest";
import { autoCapabilityLabel, deriveAutoContextCapabilities } from "./autoContext";

describe("deriveAutoContextCapabilities（W6-R3 自动化能力：不伪造）", () => {
  it("RAG runtime 就绪 → 知识检索自动执行（移除按钮不等于关闭能力）", () => {
    const caps = deriveAutoContextCapabilities(
      { chat_execution_mode: "agent_runtime", rag_chat_runtime_enabled: true },
      null
    );
    expect(caps.knowledge).toBe("auto");
    expect(autoCapabilityLabel(caps.knowledge)).toBe("自动执行");
  });

  it("agent_runtime 但 RAG 未启用 → 未启用（如实呈现，不静默）", () => {
    const caps = deriveAutoContextCapabilities(
      { chat_execution_mode: "agent_runtime", rag_chat_runtime_enabled: false },
      null
    );
    expect(caps.knowledge).toBe("disabled");
  });

  it("legacy 运行模式 → 自动化不可用（不把旧路径伪装为自动）", () => {
    const caps = deriveAutoContextCapabilities(
      { chat_execution_mode: "legacy", rag_chat_runtime_enabled: true },
      null
    );
    expect(caps.knowledge).toBe("unavailable");
  });

  it("短期摘要与长期记忆候选：后端未公开状态 → 未就绪（不制造成功记录/伪记忆）", () => {
    const caps = deriveAutoContextCapabilities(
      { chat_execution_mode: "agent_runtime", rag_chat_runtime_enabled: true },
      null
    );
    expect(caps.shortTermSummary).toBe("not-ready");
    expect(caps.longTermMemory).toBe("not-ready");
    expect(autoCapabilityLabel(caps.shortTermSummary)).toBe("未就绪");
    expect(autoCapabilityLabel(caps.longTermMemory)).toBe("未就绪");
  });

  it("能力字段缺省按未提供处理（不猜测后端内部状态）", () => {
    const caps = deriveAutoContextCapabilities(null, null);
    expect(caps.knowledge).toBe("unavailable");
    expect(caps.shortTermSummary).toBe("not-ready");
    expect(caps.longTermMemory).toBe("not-ready");
  });
});
