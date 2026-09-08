import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { applyRunFrame, createRunProjection } from "../model/runProjector";
import CommandOutput from "./CommandOutput.vue";
import RunTranscript from "./RunTranscript.vue";

describe("S0 当前桌面显示基线", () => {
  it("零工具 completed 保留文字回答提示，不能将后端缺口描述为 UI 没有任何提示", () => {
    const projection = createRunProjection("s0-run", "修改文件并运行测试");
    applyRunFrame(projection, { sequence: 1, type: "run.completed", payload: {
      output: "已修改并通过测试", tool_call_count: 0,
    } });
    const wrapper = mount(RunTranscript, { props: { projection } });
    try {
      expect(projection.status).toBe("completed");
      expect(wrapper.get('[data-testid="terminal-no-evidence"]').text()).toContain("不含执行证据");
      expect(wrapper.get('[data-testid="terminal-output"]').text()).toContain("已修改并通过测试");
    } finally {
      wrapper.unmount();
    }
  });

  it("本机非零退出仍显示 completed，但保留失败退出码", () => {
    const wrapper = mount(CommandOutput, { props: { page: null, execution: {
      id: "s0-execution", tool_name: "run_project_command", tool_version: "1", status: "completed",
      error_code: null, error_message: null, created_at: "2026-09-08T00:00:00Z", completed_at: "2026-09-08T00:00:01Z",
      output: { args: ["python", "-m", "pytest"], returncode: 1, stdout: "1 failed", stderr: "", truncated: false },
    } } });
    try {
      expect(wrapper.get(".output-status").text()).toBe("completed");
      expect(wrapper.get('[data-testid="command-exit-code"]').text()).toBe("退出码 1");
      expect(wrapper.get('[data-testid="command-exit-code"]').classes()).toContain("bad");
    } finally {
      wrapper.unmount();
    }
  });
});
