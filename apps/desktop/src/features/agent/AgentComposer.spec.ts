import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import AgentComposer from "./AgentComposer.vue";
import {
  agentPermissionOptions,
  currentAgentCapabilityFacts,
} from "./model/agentCapabilities";
import { contextUsageUnavailable, deriveContextUsage } from "./model/contextUsage";

function mountComposer(props: Record<string, unknown> = {}) {
  return mount(AgentComposer, {
    props: {
      streaming: false,
      pendingTool: false,
      ...props,
    },
    attachTo: document.body,
  });
}

describe("AgentComposer（W6-R3 底部控制重排）", () => {
  it("原知识检索位为命令权限下拉；三档真实语义（不支持档位禁用并说明）", () => {
    const wrapper = mountComposer();
    const select = wrapper.find('[data-testid="composer-permission-select"]');
    expect(select.exists()).toBe(true);
    const options = select.findAll("option");
    expect(options.length).toBe(3);
    expect(options[0].text()).toContain("总是询问");
    expect(options[0].element.disabled).toBe(false);
    expect(options[1].element.disabled).toBe(true);
    expect(options[1].text()).toContain("替我批准");
    expect(options[1].attributes("title")).toContain("未开放");
    expect(options[2].element.disabled).toBe(true);
    expect(options[2].text()).toContain("完全访问");
    expect(options[2].attributes("title")).toContain("不可用");
  });

  it("知识检索与生成记忆按钮、快捷键与空占位均不存在（反向断言）", () => {
    const wrapper = mountComposer();
    expect(wrapper.text()).not.toContain("知识检索");
    expect(wrapper.text()).not.toContain("生成记忆");
    expect(wrapper.find('[data-testid="composer-reasoning"]').exists()).toBe(false);
  });

  it("底部模型/Provider 入口呈现当前模型与运行位置；点击进入配置", async () => {
    const wrapper = mountComposer({
      modelName: "qwen3:4b",
      providerLabel: "本地",
    });
    const entry = wrapper.find('[data-testid="composer-model-entry"]');
    expect(entry.text()).toContain("qwen3:4b");
    expect(entry.text()).toContain("本地");
    await entry.trigger("click");
    expect(wrapper.emitted("configure-model")).toBeTruthy();
  });

  it("模型未配置/远程关闭时呈现真实异常态（不伪装可用）", () => {
    const wrapper = mountComposer({
      modelName: null,
      providerLabel: "未配置",
      providerWarning: "模型未配置：请先进入设置完成模型配置",
    });
    const entry = wrapper.find('[data-testid="composer-model-entry"]');
    expect(entry.classes()).toContain("has-warning");
    expect(entry.attributes("title")).toContain("模型未配置");
    expect(entry.text()).toContain("系统默认模型");
  });

  it("上下文用量模块渲染真实事实；不可用时不显示百分比（不伪造）", () => {
    const ready = mountComposer({
      usageFacts: deriveContextUsage(1600, 8192),
    });
    expect(ready.find('[data-testid="context-usage-meter"]').text()).toContain("20%");

    const unavailable = mountComposer({ usageFacts: contextUsageUnavailable() });
    expect(unavailable.find('[data-testid="context-usage-meter"]').text()).toContain("不可用");
    expect(unavailable.find('[data-testid="context-usage-meter"]').text()).not.toContain("%");
  });

  it("发送/停止事件透传（沿用既有输入语义）", async () => {
    const wrapper = mountComposer();
    const input = wrapper.find('[data-testid="task-composer-input"]');
    await input.setValue("你好");
    await input.trigger("keydown.enter");
    expect(wrapper.emitted("send")?.[0]).toEqual(["你好"]);
  });
});

describe("agentCapabilities（契约事实）", () => {
  it("无独立完全访问支持位时不得伪装可用", () => {
    const facts = currentAgentCapabilityFacts({});
    expect(facts.fullAccessSupported).toBe(false);
    const options = agentPermissionOptions(facts);
    expect(options.find((o) => o.id === "full_access")?.available).toBe(false);
    const future = currentAgentCapabilityFacts({ full_access_enabled: true });
    expect(future.fullAccessSupported).toBe(true);
  });
});
