import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CodingModelProfileDetail } from "../features/coding/model/contracts";
import {
  deleteCodingModelProfile,
  fetchModelToolProbe,
  listCodingModelProfiles,
  upsertCodingModelProfile,
} from "../features/coding/api/modelProfiles";
import ModelProfilesPanel from "./ModelProfilesPanel.vue";

const confirmMock = vi.hoisted(() => vi.fn());

vi.mock("../api", () => ({ updateSettings: vi.fn() }));
vi.mock("../stores/notifications", () => ({
  useNotifications: () => ({
    confirm: confirmMock,
    error: vi.fn(),
  }),
}));
vi.mock("../features/coding/api/modelProfiles", () => ({
  deleteCodingModelProfile: vi.fn(),
  fetchCodingProfileImportStatus: vi.fn().mockResolvedValue({
    importState: "not_needed",
    reasonCode: null,
    provider: null,
    modelAvailable: false,
  }),
  fetchModelToolProbe: vi.fn(),
  importCodingModelProfile: vi.fn(),
  listCodingModelProfiles: vi.fn(),
  probeCodingModelProfile: vi.fn(),
  retryModelToolProbe: vi.fn(),
  setCodingDefaultProfile: vi.fn(),
  upsertCodingModelProfile: vi.fn(),
}));

function profile(id: string): CodingModelProfileDetail {
  return {
    id,
    provider: "ollama",
    displayName: "本地编码模型",
    modelName: "qwen-local",
    isDefault: false,
    isLocal: true,
    nativeToolCalls: true,
    supportsStreaming: true,
    supportsStructuredOutput: false,
    supportsVision: false,
    contextTokens: 32768,
    reasoningEfforts: null,
    usageReporting: true,
    enabled: true,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchModelToolProbe).mockResolvedValue({
    status: "running",
    error_code: null,
    pass_count: 0,
    sample_count: 0,
    results: null,
    requirements: null,
    probed_at: null,
  });
});

describe("ModelProfilesPanel", () => {
  it("新建 profile 后立即刷新后台工具探测状态", async () => {
    let created: CodingModelProfileDetail | null = null;
    vi.mocked(listCodingModelProfiles).mockImplementation(async () =>
      created ? [created] : []
    );
    vi.mocked(upsertCodingModelProfile).mockImplementation(async (id) => {
      created = profile(id);
      return created;
    });

    const wrapper = mount(ModelProfilesPanel);
    await flushPromises();
    await wrapper.get('[data-testid="model-profile-create"]').trigger("click");
    const displayName = document.querySelector<HTMLInputElement>(
      'input[placeholder="例如：本地编码模型"]'
    );
    const modelName = document.querySelector<HTMLInputElement>(
      '[data-testid="model-profile-editor-model-name"]'
    );
    const save = document.querySelector<HTMLButtonElement>(
      '[data-testid="model-profile-save"]'
    );
    expect(displayName).not.toBeNull();
    expect(modelName).not.toBeNull();
    expect(save).not.toBeNull();
    displayName!.value = "本地编码模型";
    displayName!.dispatchEvent(new Event("input", { bubbles: true }));
    modelName!.value = "qwen-local";
    modelName!.dispatchEvent(new Event("input", { bubbles: true }));
    save!.click();
    await flushPromises();

    expect(created).not.toBeNull();
    expect(fetchModelToolProbe).toHaveBeenCalledWith(
      created!.id,
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(wrapper.get(`[data-testid="tool-probe-${created!.id}"]`).text()).toContain(
      "工具能力探测中"
    );
    wrapper.unmount();
  });

  it("删除模型使用全局危险操作确认", async () => {
    const existing = profile("profile-delete");
    vi.mocked(listCodingModelProfiles).mockResolvedValue([existing]);
    confirmMock.mockResolvedValue(true);
    vi.mocked(deleteCodingModelProfile).mockResolvedValue();

    const wrapper = mount(ModelProfilesPanel);
    await flushPromises();
    await wrapper.get('[aria-label="删除 本地编码模型"]').trigger("click");
    await flushPromises();

    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({ danger: true })
    );
    expect(deleteCodingModelProfile).toHaveBeenCalledWith(existing.id);
    wrapper.unmount();
  });
});
