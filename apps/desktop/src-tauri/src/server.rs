// 该 HTTPS 入口对应服务器 43.163.232.238；保留域名用于站点路由和证书校验。
pub(crate) const ACCOUNT_SERVER_ORIGIN: &str = "https://www.liuyingapi.top";

#[tauri::command]
pub(crate) fn account_server_origin() -> &'static str {
    ACCOUNT_SERVER_ORIGIN
}
