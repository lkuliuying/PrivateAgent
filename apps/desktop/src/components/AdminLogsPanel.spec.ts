import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AdminLogsPanel from './AdminLogsPanel.vue';

const api = vi.hoisted(() => ({ getServiceLogSources: vi.fn(), getServiceLogTail: vi.fn() }));
vi.mock('../services/adminLogs', () => api);
const tail = (source: string, text: string) => ({
  source, label: source, lines: [text], truncated: false, scanned_bytes: 40,
  generated_at: '2026-08-30T08:00:00Z',
});

describe('AdminLogsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getServiceLogSources.mockResolvedValue([
      { id: 'supervisor', label: 'Supervisor', available: true, message: '' },
      { id: 'nginx-error', label: 'Nginx', available: true, message: '' },
    ]);
    api.getServiceLogTail.mockResolvedValue(tail('supervisor', 'POST /projects 422'));
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs(); });

  it.each([
    '2026-08-30T16:08:04Z',
    '2026-08-30T16:08:04.123456',
    '2026-08-31T00:08:04+08:00',
  ])('将日志快照更新时间 %s 统一显示为上海时间', async generatedAt => {
    vi.stubEnv('TZ', 'Asia/Shanghai');
    api.getServiceLogTail.mockResolvedValue({
      ...tail('supervisor', '2026-08-30 16:08:04 原始日志内容'),
      generated_at: generatedAt,
    });
    const wrapper = mount(AdminLogsPanel);
    try {
      await flushPromises();
      expect(wrapper.get('.admin-logs__footer').text()).toContain(
        '更新时间：2026年8月31日 00:08:04（Asia/Shanghai）'
      );
      expect(wrapper.get('pre').text()).toBe('2026-08-30 16:08:04 原始日志内容');
    } finally {
      wrapper.unmount();
    }
  });

  it('shows log text safely and only requests logs when mounted', async () => {
    api.getServiceLogTail.mockResolvedValue(tail('supervisor', '<img src=x onerror=alert(1)>'));
    const wrapper = mount(AdminLogsPanel);
    await flushPromises();
    expect(wrapper.get('pre').text()).toContain('<img src=x onerror=alert(1)>');
    expect(wrapper.find('img').exists()).toBe(false);
    expect(api.getServiceLogTail).toHaveBeenCalledWith('supervisor', 200, '', expect.any(AbortSignal));
    wrapper.unmount();
  });

  it('does not let a late response overwrite a newly selected source', async () => {
    let completeOld!: (value: ReturnType<typeof tail>) => void;
    api.getServiceLogTail.mockImplementationOnce(() => new Promise(resolve => { completeOld = resolve; }));
    const wrapper = mount(AdminLogsPanel);
    await flushPromises();
    const firstSignal = api.getServiceLogTail.mock.calls[0][3] as AbortSignal;
    api.getServiceLogTail.mockResolvedValueOnce(tail('nginx-error', 'new nginx output'));
    await wrapper.get('[aria-label="日志来源"]').setValue('nginx-error');
    await flushPromises();
    completeOld(tail('supervisor', 'stale output'));
    await flushPromises();
    expect(firstSignal.aborted).toBe(true);
    expect(wrapper.get('pre').text()).toBe('new nginx output');
    wrapper.unmount();
  });

  it('stops automatic refresh and pending requests when the module closes', async () => {
    vi.useFakeTimers();
    const wrapper = mount(AdminLogsPanel);
    await flushPromises();
    await wrapper.get('input[type="checkbox"]').setValue(true);
    await vi.advanceTimersByTimeAsync(5000);
    await flushPromises();
    expect(api.getServiceLogTail).toHaveBeenCalledTimes(2);
    const signal = api.getServiceLogTail.mock.calls[1][3] as AbortSignal;
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(15000);
    expect(signal.aborted).toBe(true);
    expect(api.getServiceLogTail).toHaveBeenCalledTimes(2);
  });

  it('shows permission failures and allows retry', async () => {
    api.getServiceLogTail.mockRejectedValueOnce(new Error('服务账号没有该日志的只读权限'));
    const wrapper = mount(AdminLogsPanel);
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain('只读权限');
    await wrapper.get('form').trigger('submit');
    await flushPromises();
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.get('pre').text()).toContain('422');
    wrapper.unmount();
  });
});
