import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ConversationList from "./ConversationList.vue";
import type { Session } from "../../types";

const SESSIONS: Session[] = [
  { id: 1, title: "旧会话", created_at: "2026-08-20T00:00:00Z", updated_at: "2026-08-20T01:00:00Z" },
  { id: 2, title: "最近会话", created_at: "2026-08-22T00:00:00Z", updated_at: "2026-08-22T01:00:00Z" },
];

function mountList(props: Record<string, unknown> = {}) {
  return mount(ConversationList, {
    props: { sessions: SESSIONS, currentId: null, ...props },
    attachTo: document.body,
  });
}

describe("ConversationList（W6-R2 Agent 左栏）", () => {
  it("渲染真实会话（按更新时间倒序）并可点击选择", async () => {
    const wrapper = mountList({ currentId: 1 });
    const rows = wrapper.findAll(".session-row");
    expect(rows.length).toBe(2);
    expect(rows[0].text()).toContain("最近会话");
    expect(wrapper.find('[data-testid="agent-conversation-1"]').attributes("aria-current")).toBe("page");
    await wrapper.find('[data-testid="agent-conversation-2"]').trigger("click");
    expect(wrapper.emitted("select-session")?.[0]).toEqual([2]);
  });

  it("搜索/筛选会话（不复制假列表，作用于真实数据）", async () => {
    const wrapper = mountList();
    await wrapper.find('[data-testid="agent-conversation-search"]').setValue("最近");
    const rows = wrapper.findAll(".session-row");
    expect(rows.length).toBe(1);
    expect(rows[0].text()).toContain("最近会话");
    await wrapper.find('[data-testid="agent-conversation-search"]').setValue("不存在");
    expect(wrapper.find('[data-testid="agent-conversations-empty"]').exists()).toBe(true);
  });

  it("新建对话入口 + 当前会话运行状态点（键盘可达：均为按钮）", async () => {
    const wrapper = mountList({ currentId: 2, running: true });
    await wrapper.find('[data-testid="agent-conversation-new"]').trigger("click");
    expect(wrapper.emitted("new-session")).toBeTruthy();
    expect(wrapper.find('[data-testid="agent-conversation-running"]').exists()).toBe(true);
    for (const row of wrapper.findAll(".session-row")) {
      expect(row.element.tagName.toLowerCase()).toBe("button");
    }
  });
});
