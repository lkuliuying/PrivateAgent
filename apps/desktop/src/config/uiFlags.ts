/**
 * 客户端固定使用本机 Coding 工作台。
 * 旧版 URL/localStorage 开关不再允许恢复已经下线的兼容壳。
 */
export function isCodingWorkspaceEnabled(): boolean {
  return true;
}
