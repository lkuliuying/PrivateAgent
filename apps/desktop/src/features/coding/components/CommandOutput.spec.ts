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
      // 与后端真实 output_json 字段对齐（args/cwd/returncode）
      args: ["pytest", "tests", "-q"],
      cwd: "F:/workspace/demo",
      returncode: 0,
      succeeded: true,
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
    // W6-R：输出体默认折叠，展开后渲染行（长输出不拖垮页面）
    expect(wrapper.find('[data-testid="command-output-body"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("2 行");
    await wrapper.find('[data-testid="command-output-toggle"]').trigger("click");
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

  // ============ v0.8.0 W6-R：命令卡可追溯事实（计划 §4.3/§6.6） ============
  it("默认呈现脱敏命令文本、工作目录范围、退出码与耗时", () => {
    const wrapper = mount(CommandOutput, { props: { execution: execution(), page: null } });
    const command = wrapper.find('[data-testid="command-line"]');
    expect(command.text()).toContain("pytest tests -q");
    expect(wrapper.find('[data-testid="command-cwd"]').text()).toContain("F:/workspace/demo");
    expect(wrapper.find('[data-testid="command-exit-code"]').text()).toContain("退出码 0");
    expect(wrapper.find('[data-testid="command-duration"]').text()).toContain("耗时");
  });

  it("命令参数中的凭据呈现为 [REDACTED]（零容忍：不泄露敏感信息）", () => {
    const wrapper = mount(CommandOutput, {
      props: {
        execution: execution({
          output: {
            args: [
              "git",
              "push",
              "https://user:hunter2@example.com/repo.git",
              "--token=sk-live-abcdef",
            ],
            cwd: "F:/workspace/demo",
            returncode: 0,
          },
        }),
        page: null,
      },
    });
    const text = wrapper.find('[data-testid="command-line"]').text();
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("sk-live-abcdef");
    expect(text).toContain("[REDACTED]");
  });

  it("非零退出码呈现失败语义色", () => {
    const wrapper = mount(CommandOutput, {
      props: {
        execution: execution({ status: "failed", output: { returncode: 2 } }),
        page: null,
      },
    });
    const exit = wrapper.find('[data-testid="command-exit-code"]');
    expect(exit.text()).toContain("退出码 2");
    expect(exit.classes()).toContain("bad");
  });

  it("无公开命令事实时不虚构命令/目录（只显示状态与错误）", () => {
    const wrapper = mount(CommandOutput, {
      props: {
        execution: execution({ output: null, error_message: "工具执行超时" }),
        page: null,
      },
    });
    expect(wrapper.find('[data-testid="command-line"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="command-cwd"]').exists()).toBe(false);
    expect(wrapper.text()).toContain("工具执行超时");
  });
});
