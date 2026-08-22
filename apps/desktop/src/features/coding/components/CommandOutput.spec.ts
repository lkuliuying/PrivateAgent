import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import CommandOutput from "./CommandOutput.vue";
import type { RunExecutionRecord } from "../model/runContracts";

function execution(overrides: Partial<RunExecutionRecord> = {}): RunExecutionRecord {
  return {
    id: "exec-1",
    tool_name: "run_whitelisted_command",
    tool_version: "1.0.0",
    status: "succeeded",
    error_code: null,
    error_message: null,
    output: {
      exit_code: 0,
      parsed: {
        parser: "pytest",
        summary: "12 passed in 3.42s",
        passed: 12,
        failed: 0,
        skipped: 0,
        errors: 0,
        failures: [],
        truncated: false,
      },
    },
    created_at: "2026-08-22T00:00:00Z",
    completed_at: "2026-08-22T00:00:04Z",
    ...overrides,
  };
}

describe("CommandOutput", () => {
  it("parsed 测试摘要：通过/失败/跳过统计与说明", () => {
    const wrapper = mount(CommandOutput, {
      props: { execution: execution(), page: null },
    });
    const parsed = wrapper.find('[data-testid="command-parsed"]');
    expect(parsed.text()).toContain("pytest");
    expect(parsed.text()).toContain("12 passed in 3.42s");
    expect(parsed.text()).toContain("12 通过");
  });

  it("失败摘要含 failure 明细与失败语义色", () => {
    const wrapper = mount(CommandOutput, {
      props: {
        execution: execution({
          status: "failed",
          output: {
            exit_code: 1,
            parsed: {
              parser: "pytest",
              summary: "1 failed, 11 passed",
              passed: 11,
              failed: 1,
              skipped: 0,
              errors: 0,
              failures: ["tests/test_x.py::test_y AssertionError"],
              truncated: false,
            },
          },
        }),
        page: null,
      },
    });
    expect(wrapper.find('[data-testid="command-parsed"]').classes()).toContain("has-failures");
    expect(wrapper.text()).toContain("tests/test_x.py::test_y");
  });

  it("未加载时提供「查看输出」入口并发出 load；已加载渲染行", async () => {
    const wrapper = mount(CommandOutput, { props: { execution: execution(), page: null } });
    await wrapper.find('[data-testid="command-output-load"]').trigger("click");
    expect(wrapper.emitted("load")).toBeTruthy();

    await wrapper.setProps({
      page: {
        lines: [
          { seq: 1, kind: "stdout", text: "collected 12 items" },
          { seq: 2, kind: "stderr", text: "warning: something" },
        ],
        last_seq: 2,
        finished: true,
      },
    });
    expect(wrapper.find('[data-testid="command-output-body"]').text()).toContain("collected 12 items");
    expect(wrapper.find('[data-testid="command-output-body"]').text()).toContain("warning: something");
  });

  it("输出未结束（finished=false）呈现进行中与刷新入口", async () => {
    const wrapper = mount(CommandOutput, {
      props: {
        execution: execution({ status: "running", completed_at: null }),
        page: { lines: [{ seq: 1, kind: "stdout", text: "running..." }], last_seq: 1, finished: false },
      },
    });
    expect(wrapper.text()).toContain("输出进行中");
    await wrapper.find('[data-testid="command-output-poll"]').trigger("click");
    expect(wrapper.emitted("load")).toBeTruthy();
  });
});
