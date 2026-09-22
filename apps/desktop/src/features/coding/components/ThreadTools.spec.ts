import { afterEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import ThreadTools from "./ThreadTools.vue";
import type { CodingWorkspaceStore } from "../model/codingWorkspaceStore";
const api = vi.hoisted(() => ({ archive: vi.fn(), pin: vi.fn(), rename: vi.fn(), delete: vi.fn(), prompt: vi.fn(), confirm: vi.fn() }));
vi.mock('../api/threads', () => ({ setThreadArchived: api.archive, renameThread: api.rename, setThreadPinned: api.pin, deleteThread: api.delete }));
vi.mock('../../../stores/notifications', () => ({ useNotifications: () => ({ prompt: api.prompt, confirm: api.confirm }) }));
afterEach(() => vi.clearAllMocks());
describe('ThreadTools', () => {
  it('观察诊断从任务菜单按需挂载，切换页签卸载', async () => {
    const wrapper = mount(ThreadTools, { props: { store: { selectedThread: ref(null) } as unknown as CodingWorkspaceStore, filesOpen: false, running: false }, slots: { observer: '<p data-testid="observer-slot">运行诊断</p>' } });
    expect(wrapper.find('[data-testid="observer-slot"]').exists()).toBe(false);
    await wrapper.get('[data-testid="thread-environment-toggle"]').trigger('click');
    expect(wrapper.find('[data-testid="observer-slot"]').exists()).toBe(false);
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger('click');
    await wrapper.findAll('[role="menuitem"]').find(item => item.text() === '观察诊断')!.trigger('click');
    expect(wrapper.get('[role="tabpanel"]').text()).toBe('运行诊断');
    await wrapper.get('#environment-tab-overview').trigger('click');
    expect(wrapper.find('[data-testid="observer-slot"]').exists()).toBe(false);
    wrapper.unmount();
  });
  it('已有操作可置顶，Escape 关闭菜单', async () => {
    const refresh = vi.fn();
    const store = { selectedThread: ref({ id: 11, title: '试用', pinnedAt: null }), refresh } as unknown as CodingWorkspaceStore;
    const wrapper = mount(ThreadTools, { props: { store, filesOpen: false, running: false }, attachTo: document.body });
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger('click'); expect(wrapper.findAll('[role="menuitem"]')).toHaveLength(7); expect(wrapper.text()).not.toContain('分享');
    await wrapper.findAll('[role="menuitem"]')[1].trigger('click'); await flushPromises();
    expect(api.pin).toHaveBeenCalledWith(11, true); expect(refresh).toHaveBeenCalledOnce();
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger('click'); await wrapper.get('[role="menu"]').trigger('keydown', { key: 'Escape' });
    expect(wrapper.find('[role="menu"]').exists()).toBe(false); wrapper.unmount();
  });
  it('环境页按需呈现，打开文件区关闭浮层', async () => {
    const wrapper = mount(ThreadTools, { props: { store: { selectedThread: ref(null) } as unknown as CodingWorkspaceStore, filesOpen: false, running: true }, slots: { changes: '<p>变更内容</p>' } });
    await wrapper.get('[data-testid="thread-environment-toggle"]').trigger('click'); await wrapper.get('#environment-tab-changes').trigger('click');
    expect(wrapper.get('[role="tabpanel"]').text()).toBe('变更内容'); await wrapper.get('[data-testid="thread-files-toggle"]').trigger('click');
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false); expect(wrapper.emitted('toggle-files')).toHaveLength(1); wrapper.unmount();
  });

  it('归档入口可见，删除成功后清理选择，运行中禁止删除', async () => {
    const removeDeletedThread = vi.fn();
    const refresh = vi.fn();
    const store = { selectedThread: ref({ id: 11, title: '对话' }), removeDeletedThread, refresh } as unknown as CodingWorkspaceStore;
    const wrapper = mount(ThreadTools, { props: { store, filesOpen: false, running: true } });
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger('click');
    expect(wrapper.findAll('[role="menuitem"]').find(item => item.text() === '归档任务')!.attributes('disabled')).toBeDefined();
    expect(wrapper.get('[data-testid="thread-menu-delete"]').attributes('disabled')).toBeDefined();
    await wrapper.setProps({ running: false });
    api.confirm.mockResolvedValueOnce(false);
    await wrapper.get('[data-testid="thread-menu-delete"]').trigger('click');
    await flushPromises();
    expect(api.delete).not.toHaveBeenCalled();
    api.confirm.mockResolvedValueOnce(true);
    await wrapper.get('[data-testid="thread-menu-delete"]').trigger('click');
    await flushPromises();
    expect(api.delete).toHaveBeenCalledWith(11);
    expect(removeDeletedThread).toHaveBeenCalledWith(11);
    expect(refresh).toHaveBeenCalledOnce();
    wrapper.unmount();
  });

  it('删除失败保留会话并显示原因', async () => {
    const removeDeletedThread = vi.fn();
    const store = { selectedThread: ref({ id: 11, title: '对话' }), removeDeletedThread } as unknown as CodingWorkspaceStore;
    const wrapper = mount(ThreadTools, { props: { store, filesOpen: false, running: false } });
    await wrapper.get('[data-testid="thread-menu-toggle"]').trigger('click');
    api.confirm.mockResolvedValueOnce(true);
    api.delete.mockRejectedValueOnce({ message: '进程仍在运行' });
    await wrapper.get('[data-testid="thread-menu-delete"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toBe('进程仍在运行');
    expect(removeDeletedThread).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
