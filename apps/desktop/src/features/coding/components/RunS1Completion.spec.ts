import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import samples from "../../../../../../tests/coding_acceptance/s1-wire-examples.json";
import { createRunProjection, reconcileRunWithSnapshot } from "../model/runProjector";
import type { RunExecutionRecord, RunSnapshot } from "../model/runContracts";
import RunTranscript from "./RunTranscript.vue";
import CommandOutput from "./CommandOutput.vue";
import ThreadHeader from "./ThreadHeader.vue";

describe("S1 使用本机 ASGI 验收产生的载荷", () => {
  it.each([
    ["answered", "已回答"], ["verified", "已验证完成"], ["unmet", "任务未完成"],
    ["test_failed", "测试失败"], ["blocked", "受阻"], ["unknown", "结果未确认"],
  ] as const)("%s 在任务正文与头部使用一致结果", (name, label) => {
    const snapshot = samples[name].snapshot as unknown as RunSnapshot;
    const projection = createRunProjection(snapshot.id, "本次请求");
    reconcileRunWithSnapshot(projection, snapshot);
    const transcript = mount(RunTranscript, { props: { projection } });
    const header = mount(ThreadHeader, { props: { title: "S1", runStatus: snapshot.status, runOutcome: projection.runOutcome } });
    try {
      expect(transcript.get('[data-testid="terminal-summary"]').text()).toContain(label);
      expect(header.get('[data-testid="thread-run-status"]').text()).toContain(label);
      if (name !== "verified") expect(transcript.get('[data-testid="terminal-summary"]').classes()).not.toContain("tone-success");
      if (snapshot.completion_requirements?.length) {
        expect(transcript.get('[data-testid="completion-requirements"]').text()).toContain(snapshot.completion_requirements[0].description);
      }
    } finally {
      transcript.unmount();
      header.unmount();
    }
  });

  it("pytest 退出 1 显示测试失败并保留真实输出", async () => {
    const execution = samples.test_failed.executions[0] as unknown as RunExecutionRecord;
    const wrapper = mount(CommandOutput, { props: { execution, page: { lines: [{ seq: 0, kind: "stdout", text: "1 failed" }], last_seq: 0, finished: true } } });
    try {
      expect(wrapper.get(".output-status").text()).toBe("测试失败");
      expect(wrapper.get('[data-testid="command-exit-code"]').text()).toContain("1");
      await wrapper.get('[data-testid="command-output-toggle"]').trigger("click");
      expect(wrapper.text()).toContain("1 failed");
    } finally { wrapper.unmount(); }
  });

  it.each(["timed_out", "cancelled", "unknown"] as const)("%s 保留独立命令结果", (outcome) => {
    const execution = samples.test_failed.executions[0] as unknown as RunExecutionRecord;
    const wrapper = mount(CommandOutput, { props: { page: null, execution: { ...execution,
      output: { stdout: "partial" }, execution_result: { ...execution.execution_result!, outcome, exit_code: null, validation_outcome: "unknown" } } } });
    try {
      expect(wrapper.get(".output-status").text()).toBe({ timed_out: "命令超时", cancelled: "已取消", unknown: "结果未知" }[outcome]);
      expect(wrapper.find('[data-testid="command-exit-code"]').exists()).toBe(false);
    } finally { wrapper.unmount(); }
  });
});
