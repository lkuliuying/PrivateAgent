import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import MarkdownContent from "./MarkdownContent.vue";

describe("MarkdownContent", () => {
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
