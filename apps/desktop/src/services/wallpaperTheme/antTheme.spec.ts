import { mount, flushPromises } from "@vue/test-utils";
import { ConfigProvider } from "ant-design-vue";
import { defineComponent, ref, computed } from "vue";
import { expect, it, vi } from "vitest";
import { wallpaperAntTheme } from "./antTheme";
import { createPalette, type WallpaperPalette } from "./palette";

it("启用、更换与关闭主题不重建业务页面、不丢失未保存输入", async () => {
  const palette = ref<WallpaperPalette>();
  const mounted = vi.fn();
  const child = defineComponent({ setup() { mounted(); return { text: ref("") }; }, template: '<input v-model="text" />' });
  const wrapper = mount(defineComponent({
    components: { ConfigProvider, Child: child },
    setup: () => ({ theme: computed(() => wallpaperAntTheme(palette.value)) }),
    template: '<ConfigProvider :theme="theme"><Child /></ConfigProvider>',
  }));
  await wrapper.get("input").setValue("未保存草稿");
  for (const value of [createPalette("#18264c", "dark", false), createPalette("#f8dfb0", "light", false), undefined]) {
    palette.value = value;
    await flushPromises();
    expect(wrapper.get("input").element.value).toBe("未保存草稿");
  }
  expect(mounted).toHaveBeenCalledOnce();
  wrapper.unmount();
});
