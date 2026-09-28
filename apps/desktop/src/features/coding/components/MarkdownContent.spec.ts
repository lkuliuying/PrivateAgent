import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import MarkdownContent from "./MarkdownContent.vue";
import { copyAnswerText } from "../../agent/model/copyAnswerText";

vi.mock("../../agent/model/copyAnswerText", () => ({ copyAnswerText: vi.fn() }));

describe("MarkdownContent", () => {
  afterEach(() => { vi.resetAllMocks(); });

  it("文件引用通过事件交给工作区预览，支持空格、括号和行号", async () => {
    const wrapper = mount(MarkdownContent, { props: { content: "[源码](src/app.py:12) 和 [报告](</F:/My Project/report (draft).md#L3>)", copyControl: "none" } });
    expect(wrapper.find("a").exists()).toBe(false);
    const links = wrapper.findAll(".md-file-link");
    expect(links).toHaveLength(2);
    await links[0].trigger("click");
    await links[1].trigger("click");
    expect(wrapper.emitted("open-file")).toEqual([[{ path: "src/app.py", line: 12 }], [{ path: "F:/My Project/report (draft).md", line: 3 }]]);
    wrapper.unmount();
  });

  it("拒绝穿越、网络共享和 file 协议，保留正常网页链接", () => {
    const wrapper = mount(MarkdownContent, { props: { content: "[穿越](../private.txt) [共享](//server/share/a.txt) [本机](file:///C:/a.txt) [网页](https://example.com/docs)", copyControl: "none" } });
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.findAll("a")).toHaveLength(1);
    expect(wrapper.text()).toContain("穿越");
    wrapper.unmount();
  });

  it("每个代码块只复制代码正文，复制失败明确显示", async () => {
    vi.mocked(copyAnswerText).mockResolvedValueOnce("ok").mockResolvedValueOnce("failed");
    const wrapper = mount(MarkdownContent, { props: { content: "```py\nprint(1)\n```\n\n```\nprint(2)\n```", copyControl: "none" } });
    const buttons = wrapper.findAll('button[aria-label="复制代码"]');
    await buttons[0].trigger("click");
    await flushPromises();
    expect(copyAnswerText).toHaveBeenLastCalledWith("print(1)");
    expect(wrapper.get('[role="status"]').text()).toBe("已复制");
    await buttons[1].trigger("click");
    await flushPromises();
    expect(copyAnswerText).toHaveBeenLastCalledWith("print(2)");
    expect(wrapper.get('[role="status"]').text()).toContain("复制失败");
    wrapper.unmount();
  });

  it("流式代码变化后不把旧复制完成显示为新代码已复制", async () => {
    let finish!: (result: "ok") => void;
    vi.mocked(copyAnswerText).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(MarkdownContent, { props: { content: "```\nold\n```", copyControl: "none" } });
    await wrapper.get('button[aria-label="复制代码"]').trigger("click");
    await wrapper.setProps({ content: "```\nnew\n```" });
    await wrapper.get('button[aria-label="复制代码"]').trigger("click");
    expect(copyAnswerText).toHaveBeenCalledTimes(1);
    finish("ok");
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("文件名和标识符中的下划线原样显示，词边界的强调仍然有效", () => {
    const source = "tests/test_app.py .pytest_cache/intent-trial-test-ran unit_price foo__bar 中文_变量";
    const wrapper = mount(MarkdownContent, { props: { content: `${source}\n\n_强调_ 和 __重点__，以及 \`test_app.py\`` } });
    expect(wrapper.find("p").text()).toBe(source);
    expect(wrapper.findAll("em").map(item => item.text())).toEqual(["强调"]);
    expect(wrapper.findAll("strong").map(item => item.text())).toEqual(["重点"]);
    expect(wrapper.find("code").text()).toBe("test_app.py");
    wrapper.unmount();
  });

  it("代码语言标签不进入代码正文，复制保留源 Markdown 的围栏和表头", async () => {
    const code = "def calculate_total(unit_price, quantity):\n    return unit_price * quantity";
    const content = `## 结论\n\n\`\`\`python\n${code}\n\`\`\`\n\n| 入参 | 现实现 | 应为 | 是否相符 |\n|---|---|---|---|\n| 10, 3 | 13 | 30 | 否 |`;
    vi.mocked(copyAnswerText).mockResolvedValue("ok");
    const wrapper = mount(MarkdownContent, { props: { content } });
    expect(wrapper.get("pre code").element.textContent).toBe(code);
    expect(wrapper.get(".md-code-language").text()).toBe("python");
    expect(wrapper.findAll("th").map(item => item.text())).toEqual(["入参", "现实现", "应为", "是否相符"]);
    await wrapper.get('button[aria-label="复制 Markdown"]').trigger("click");
    await flushPromises();
    expect(copyAnswerText).toHaveBeenCalledTimes(1);
    expect(copyAnswerText).toHaveBeenCalledWith(content);
    expect(wrapper.get('[role="status"]').text()).toBe("已复制");
    wrapper.unmount();
  });

  it.each(["failed", "unavailable"] as const)("复制 %s 时显示失败，不宣称成功", async (result) => {
    vi.mocked(copyAnswerText).mockResolvedValue(result);
    const wrapper = mount(MarkdownContent, { props: { content: "回答" } });
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="status"]').text()).toContain("复制失败");
    wrapper.unmount();
  });

  it("流式内容变更不发起并发复制，也不把旧复制结果标为新内容成功", async () => {
    let finish!: (result: "ok") => void;
    vi.mocked(copyAnswerText).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const wrapper = mount(MarkdownContent, { props: { content: "旧回答" } });
    await wrapper.get("button").trigger("click");
    await wrapper.setProps({ content: "新回答" });
    expect(wrapper.get("button").attributes("disabled")).toBeDefined();
    await wrapper.get("button").trigger("click");
    expect(copyAnswerText).toHaveBeenCalledTimes(1);
    finish("ok");
    await flushPromises();
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
    expect(wrapper.get("button").attributes("disabled")).toBeUndefined();
    vi.mocked(copyAnswerText).mockResolvedValueOnce("ok");
    await wrapper.get("button").trigger("click");
    await flushPromises();
    expect(copyAnswerText).toHaveBeenLastCalledWith("新回答");
    expect(wrapper.get('[role="status"]').text()).toBe("已复制");
    wrapper.unmount();
  });

  it("空内容没有复制入口", () => {
    const wrapper = mount(MarkdownContent, { props: { content: " \n " } });
    expect(wrapper.find("button").exists()).toBe(false);
    wrapper.unmount();
  });

  it("进展可关闭复制，最终图标仍复制原始Markdown且置于产物之后", async () => {
    const content = "## 回答\n\n`test_app.py`\n\n| 项目 | 状态 |\n|---|---|\n| 检查 | 通过 |";
    vi.mocked(copyAnswerText).mockResolvedValue("ok");
    const wrapper = mount(MarkdownContent, { props: { content, copyControl: "none" },
      slots: { "after-content": '<div data-testid="artifact">文件修改</div>' } });
    try {
      expect(wrapper.find("button").exists()).toBe(false);
      expect(wrapper.find("table").exists()).toBe(true);
      await wrapper.setProps({ copyControl: "icon" });
      const button = wrapper.get('button[aria-label="复制 Markdown"]');
      expect(button.text()).toBe("");
      expect(button.find("svg").exists()).toBe(true);
      expect(wrapper.get('[data-testid="artifact"]').element.compareDocumentPosition(button.element)
        & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      await button.trigger("click");
      await flushPromises();
      expect(copyAnswerText).toHaveBeenCalledWith(content);
      expect(wrapper.get('[role="status"]').text()).toBe("已复制");
    } finally { wrapper.unmount(); }
  });

  it("超大表格限制补齐开销并保留未表格化的内容", () => {
    const headers = Array(32).fill("标题").join("|");
    const separators = Array(32).fill("---").join("|");
    const rows = Array.from({ length: 70 }, (_, index) => `第${index}行 | 值`).join("\n");
    const wrapper = mount(MarkdownContent, { props: { content: `${headers}\n${separators}\n${rows}` } });
    expect(wrapper.findAll("td")).toHaveLength(2048);
    expect(wrapper.findAll("tbody tr")).toHaveLength(64);
    expect(wrapper.find("p").text()).toContain("第69行 | 值");
    const tooWide = mount(MarkdownContent, { props: { content: `${headers}|超宽\n${separators}|---` } });
    expect(tooWide.find("table").exists()).toBe(false);
    expect(tooWide.text()).toContain("超宽");
  });

  it("把 T01 验收表格渲染为安全的语义表格", () => {
    const wrapper = mount(MarkdownContent, { props: { content:
      "验收对照\n| 要求 | 状态 | 证据 |\n|---|:---:|---:|\n| 修改 `app.py` | **满足** | 已读回 |\n| pytest | 满足 | `4 passed` |"
    } });
    expect(wrapper.find("p").text()).toBe("验收对照");
    expect(wrapper.findAll("th").map(cell => cell.text())).toEqual(["要求", "状态", "证据"]);
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
    expect(wrapper.find("td code").text()).toBe("app.py");
    expect(wrapper.find("td strong").text()).toBe("满足");
    expect(wrapper.findAll("th")[1].attributes("style")).toContain("text-align: center");
    expect(wrapper.findAll("td")[2].attributes("style")).toContain("text-align: right");
    expect(wrapper.find('[role="region"]').attributes("tabindex")).toBe("0");
  });

  it("支持省略外侧竖线、转义竖线和参差不齐的数据行", () => {
    const content = "名称 | 内容\n:--- | ---\n`a\\|b` | x\\|y\nonly |\nextra | value | ignored\n\n后续段落";
    const wrapper = mount(MarkdownContent, { props: { content } });
    expect(wrapper.find("td code").text()).toBe("a|b");
    expect(wrapper.findAll("tbody tr").map(row => row.findAll("td").map(cell => cell.text())))
      .toEqual([["a|b", "x|y"], ["only", ""], ["extra", "value"]]);
    expect(wrapper.findAll("th")[0].attributes("style")).toContain("text-align: left");
    expect(wrapper.find("p").text()).toBe("后续段落");
  });

  it.each([
    "a | b\n--- | invalid\n1 | 2",
    "a | b\n--- | --- | ---\n1 | 2",
    "a \\| b\n--- | ---",
    "普通文字 | 仍是普通文字",
    "```text\n| a | b |\n|---|---|\n```",
  ])("无效或字面内容不误判为表格：%s", (content) => {
    const wrapper = mount(MarkdownContent, { props: { content } });
    expect(wrapper.find("table").exists()).toBe(false);
  });

  it("流式表格补齐分隔行后再渲染，后续标题不吞入数据行", async () => {
    const wrapper = mount(MarkdownContent, { props: { content: "| a | b |\n|---|" } });
    expect(wrapper.find("table").exists()).toBe(false);
    await wrapper.setProps({ content: "| a | b |\n|---|---|\n|1|2|\n## 下一步 | 说明" });
    expect(wrapper.findAll("tbody tr")).toHaveLength(1);
    expect(wrapper.find("h2").text()).toBe("下一步 | 说明");
  });

  it("表格中的 HTML 和危险链接不会执行", () => {
    const wrapper = mount(MarkdownContent, { props: { content:
      '| 内容 | 链接 |\n|---|---|\n| <img src=x onerror=alert(1)> | [危险](javascript:alert(1)) |\n| `x` | [文档](https://example.com/docs) |'
    } });
    expect(wrapper.find("img").exists()).toBe(false);
    expect(wrapper.findAll("a")).toHaveLength(1);
    expect(wrapper.find("a").attributes("href")).toBe("https://example.com/docs");
    expect(wrapper.find("td").text()).toContain("<img");
  });

  it("渲染标题、列表和代码围栏，不显示 Markdown 控制字符", () => {
    const wrapper = mount(MarkdownContent, {
      props: {
        content: "## 完成\n\n- 写入 `hello.c`\n- 已验证\n\n```c\n#include <stdio.h>\n```",
      },
    });
    expect(wrapper.find("h2").text()).toBe("完成");
    expect(wrapper.findAll("li")).toHaveLength(2);
    expect(wrapper.find("pre code").text()).toContain("#include <stdio.h>");
    expect(wrapper.text()).not.toContain("```");
  });

  it("只把 http/https 链接渲染为可点击链接", () => {
    const safe = mount(MarkdownContent, {
      props: { content: "[文档](https://example.com/docs)" },
    });
    expect(safe.find("a").attributes("href")).toBe("https://example.com/docs");

    const unsafe = mount(MarkdownContent, {
      props: { content: "[危险](javascript:alert(1))" },
    });
    expect(unsafe.find("a").exists()).toBe(false);
    expect(unsafe.text()).toContain("危险");
  });
});
