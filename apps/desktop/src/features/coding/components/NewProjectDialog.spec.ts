import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import NewProjectDialog from "./NewProjectDialog.vue";

const pickDirectory = vi.hoisted(() => vi.fn());
const createCodingProject = vi.hoisted(() => vi.fn());

vi.mock("../../../api/tauri", () => ({ pickDirectory }));
vi.mock("../api/projects", () => ({
  authorizeProjectScope: vi.fn(),
  createCodingProject,
  ensureUserHomeProject: vi.fn(),
}));

describe("NewProjectDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickDirectory.mockResolvedValue("F:\\workspace\\private-agent");
    createCodingProject.mockResolvedValue({ id: 42 });
  });

  it("工作目录只能通过资源管理器选择并以只读方式呈现", async () => {
    const wrapper = mount(NewProjectDialog);

    expect(wrapper.find('[data-testid="new-project-path"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="new-project-submit"]').attributes("disabled")).toBeDefined();

    await wrapper.get('[data-testid="new-project-pick-directory"]').trigger("click");
    await flushPromises();

    expect(pickDirectory).toHaveBeenCalledTimes(1);
    expect(wrapper.text()).toContain("F:\\workspace\\private-agent");

    await wrapper.get('[data-testid="new-project-name"]').setValue("PrivateAgent");
    await wrapper.get('[data-testid="new-project-submit"]').trigger("click");
    await flushPromises();

    expect(createCodingProject).toHaveBeenCalledWith(
      "PrivateAgent",
      "F:\\workspace\\private-agent"
    );
    expect(wrapper.emitted("created")?.[0]).toEqual([42]);
  });

  it("取消目录选择时不填写路径，也不能创建项目", async () => {
    pickDirectory.mockResolvedValueOnce(null);
    const wrapper = mount(NewProjectDialog);

    await wrapper.get('[data-testid="new-project-mode-directory"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-testid="new-project-name"]').setValue("未选目录");

    expect(wrapper.text()).toContain("从资源管理器选择目录");
    expect(wrapper.get('[data-testid="new-project-submit"]').attributes("disabled")).toBeDefined();
    expect(createCodingProject).not.toHaveBeenCalled();
  });
});
