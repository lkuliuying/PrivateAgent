/**
 * 普通用户端固定使用 Coding 工作台；管理员由路由隔离到独立后台。
 * 旧版 URL/localStorage 开关不再允许恢复已经下线的兼容壳。
 */
export function isCodingWorkspaceEnabled(isAdmin: boolean): boolean {
  return !isAdmin;
}
