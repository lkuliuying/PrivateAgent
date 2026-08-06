// Tauri 桌面壳：管理 Python 后端 sidecar 生命周期、端口协商、连接配置与更新检查（第五阶段）。
//
// 职责：
// 1. 启动时仅注册状态（不自动 spawn sidecar）；由前端引导流程按需调用 start_sidecar。
// 2. start_sidecar 分配空闲端口（OS 分配 127.0.0.1:0），通过 PA_API_PORT 传给 sidecar 并拉起进程。
//    dev 模式（cfg!(debug_assertions)）下不 spawn，返回 dev_mode=true，前端回退到手动后端 127.0.0.1:8000。
// 3. 配置命令：config_exists / read_config / write_config —— 读写 %APPDATA%/personal-assistant/.env（PA_ 前缀）。
// 4. 依赖检测：check_dependencies（默认端口探测）/ test_connections（按配置探测 MySQL + Ollama）。
// 5. 更新命令：check_for_updates / download_and_install_update / relaunch_app（基于 tauri-plugin-updater + process）。
// 6. 应用退出时终止 sidecar 子进程。
//
// .env 字段（与 src/personal_assistant/config.py 的 PA_ 前缀对齐）：
//   PA_DB_HOST / PA_DB_PORT / PA_DB_USER / PA_DB_NAME / PA_DB_SECRET_REF
//   PA_OLLAMA_BASE_URL=...   PA_LLM_MODEL=...   PA_EMBED_MODEL=...

mod credential_prompt;
mod credentials;

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use std::{collections::BTreeMap, collections::BTreeSet};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

use credential_prompt::PromptOutcome;
use credentials::{
    mcp_account, mcp_reference, provider_account, validate_mcp_secret_alias,
    CLAUDE_API_KEY_ACCOUNT, DATABASE_PASSWORD_ACCOUNT, OPENAI_API_KEY_ACCOUNT,
};
use zeroize::{Zeroize, Zeroizing};

/// sidecar 二进制名（对应 tauri.conf.json 的 externalBin，去掉平台后缀）。
const SIDECAR_BIN: &str = "personal-assistant-server";

/// sidecar 状态：协商端口与子进程句柄。
/// port 为 None 表示未启动 sidecar（dev 模式手动起后端，或尚未调用 start_sidecar）。
struct SidecarState {
    port: Mutex<Option<u16>>,
    token: Mutex<Option<String>>,
    child: Mutex<Option<CommandChild>>,
}

/// 连接配置（向导编辑的字段；写盘时组装成 PA_DB_URL 等）。
#[derive(Serialize, Deserialize, Clone)]
struct ConfigData {
    db_host: String,
    db_port: u16,
    db_user: String,
    db_name: String,
    #[serde(default)]
    db_password_configured: bool,
    ollama_base_url: String,
    llm_model: String,
    embed_model: String,
    #[serde(default)]
    mcp_enabled: bool,
}

impl Default for ConfigData {
    fn default() -> Self {
        ConfigData {
            db_host: "127.0.0.1".into(),
            db_port: 3306,
            db_user: "root".into(),
            db_name: "personal_assistant".into(),
            db_password_configured: false,
            ollama_base_url: "http://127.0.0.1:11434".into(),
            llm_model: "qwen2.5:14b-instruct-q4_K_M".into(),
            embed_model: "bge-m3".into(),
            mcp_enabled: false,
        }
    }
}

/// start_sidecar 的返回。
#[derive(Serialize)]
struct SidecarStartResult {
    ok: bool,
    /// dev 模式未 spawn 真实 sidecar（前端回退到 127.0.0.1:8000）。
    dev_mode: bool,
    port: Option<u16>,
    /// High-entropy token for this sidecar process; never persisted or logged.
    token: Option<String>,
    error: Option<String>,
}

#[derive(Serialize)]
struct ApiConnection {
    port: u16,
    token: String,
}

#[derive(Serialize)]
struct ProviderSecretStatus {
    openai_configured: bool,
    claude_configured: bool,
}

#[derive(Serialize)]
struct DatabaseSecretPromptResult {
    configured: bool,
    cancelled: bool,
}

#[derive(Serialize)]
struct ProviderSecretPromptResult {
    openai_configured: bool,
    claude_configured: bool,
    cancelled: bool,
}

#[derive(Serialize)]
struct McpSecretStatus {
    reference: String,
    configured: bool,
}

#[derive(Serialize)]
struct McpSecretPromptResult {
    reference: String,
    configured: bool,
    cancelled: bool,
}

#[derive(Default, Deserialize, Serialize)]
struct McpSecretIndex {
    aliases: Vec<String>,
}

struct LoadedConfig {
    public: ConfigData,
    legacy_password: Option<String>,
    legacy_format: bool,
    secret_ref_configured: bool,
}

/// test_connections 的返回。
#[derive(Serialize)]
struct ConnResult {
    mysql_ok: bool,
    mysql_error: Option<String>,
    ollama_ok: bool,
    ollama_error: Option<String>,
    ollama_models: Vec<String>,
    /// 配置的 llm_model 是否在 Ollama 已拉取的模型列表中。
    llm_model_available: bool,
    embed_model_available: bool,
}

/// check_dependencies 的返回（默认端口探测，向导首屏环境提示用）。
#[derive(Serialize)]
struct DepResult {
    mysql_reachable: bool,
    ollama_reachable: bool,
}

/// check_for_updates 的返回（无更新时为 None）。
#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    date: Option<String>,
    body: Option<String>,
}

// ============ 路径 ============

/// 配置目录：dev=项目根下隔离的 .run/desktop-config；打包模式按平台--
/// Windows `%APPDATA%/personal-assistant`、macOS `~/Library/Application Support/personal-assistant`、
/// Linux `$XDG_DATA_HOME/personal-assistant`（或 `~/.local/share/personal-assistant`）。
fn config_dir() -> PathBuf {
    if cfg!(debug_assertions) {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // Keep desktop-dev writes isolated from the project .env used by the
        // manually started Python backend.
        manifest
            .ancestors()
            .nth(3)
            .map(|p| p.join(".run").join("desktop-config"))
            .unwrap_or_else(|| manifest.join("target").join("desktop-config"))
    } else {
        #[cfg(windows)]
        {
            let base = std::env::var("APPDATA").unwrap_or_default();
            PathBuf::from(base).join("personal-assistant")
        }
        // macOS：~/Library/Application Support/personal-assistant（第八阶段 M5 修正，
        // 原先误用 XDG ~/.local/share，不符合 macOS 惯例且跨应用备份会遗漏）。
        #[cfg(target_os = "macos")]
        {
            let home = std::env::var("HOME").unwrap_or_else(|_| ".".to_string());
            PathBuf::from(home)
                .join("Library")
                .join("Application Support")
                .join("personal-assistant")
        }
        #[cfg(target_os = "linux")]
        {
            let base = std::env::var("XDG_DATA_HOME")
                .ok()
                .or_else(|| {
                    std::env::var("HOME")
                        .ok()
                        .map(|h| format!("{}/.local/share", h))
                })
                .unwrap_or_else(|| ".".to_string());
            PathBuf::from(base).join("personal-assistant")
        }
    }
}

fn env_path() -> PathBuf {
    config_dir().join(".env")
}

fn mcp_secret_index_path() -> PathBuf {
    config_dir().join("mcp-secret-index.json")
}

fn read_mcp_secret_aliases() -> Result<BTreeSet<String>, String> {
    let path = mcp_secret_index_path();
    if !path.exists() {
        return Ok(BTreeSet::new());
    }
    let raw = fs::read_to_string(path).map_err(|_| "MCP credential index read failed")?;
    let index: McpSecretIndex =
        serde_json::from_str(&raw).map_err(|_| "MCP credential index is invalid")?;
    if index.aliases.len() > 32 {
        return Err("too many MCP credentials".to_string());
    }
    let mut aliases = BTreeSet::new();
    for alias in index.aliases {
        validate_mcp_secret_alias(&alias)?;
        aliases.insert(alias);
    }
    Ok(aliases)
}

fn write_mcp_secret_aliases(aliases: &BTreeSet<String>) -> Result<(), String> {
    if aliases.len() > 32 {
        return Err("too many MCP credentials".to_string());
    }
    fs::create_dir_all(config_dir()).map_err(|_| "MCP credential index directory failed")?;
    let encoded = serde_json::to_vec(&McpSecretIndex {
        aliases: aliases.iter().cloned().collect(),
    })
    .map_err(|_| "MCP credential index serialization failed")?;
    fs::write(mcp_secret_index_path(), encoded)
        .map_err(|_| "MCP credential index write failed".to_string())
}

fn collect_mcp_secrets_for_sidecar() -> Result<Zeroizing<String>, String> {
    let mut values = BTreeMap::new();
    for alias in read_mcp_secret_aliases()? {
        let account = mcp_account(&alias)?;
        if let Some(secret) = credentials::get(&account)? {
            values.insert(mcp_reference(&alias)?, secret);
        }
    }
    let mut encoded = serde_json::to_string(&values)
        .map_err(|_| "MCP credential injection serialization failed")?;
    for secret in values.values_mut() {
        secret.zeroize();
    }
    if encoded.len() > 16 * 1024 {
        encoded.zeroize();
        return Err("MCP credential injection exceeds the process limit".to_string());
    }
    Ok(Zeroizing::new(encoded))
}

// ============ .env 读写 ============

fn percent_encode_component(value: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut out = String::with_capacity(value.len());
    for byte in value.as_bytes() {
        if byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'.' | b'_' | b'~') {
            out.push(*byte as char);
        } else {
            out.push('%');
            out.push(HEX[(byte >> 4) as usize] as char);
            out.push(HEX[(byte & 0x0f) as usize] as char);
        }
    }
    out
}

fn percent_decode_component(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let parsed = std::str::from_utf8(&bytes[i + 1..i + 3])
                .ok()
                .and_then(|s| u8::from_str_radix(s, 16).ok());
            if let Some(byte) = parsed {
                out.push(byte);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn build_db_url(cfg: &ConfigData, password: &str) -> String {
    // IPv6 主机含 ':'，需用方括号包裹，否则 URL host 无法解析。
    let host = if cfg.db_host.contains(':') {
        format!("[{}]", cfg.db_host)
    } else {
        cfg.db_host.clone()
    };
    format!(
        "mysql+aiomysql://{}:{}@{}:{}/{}?charset=utf8mb4",
        percent_encode_component(&cfg.db_user),
        percent_encode_component(password),
        host,
        cfg.db_port,
        percent_encode_component(&cfg.db_name)
    )
}

/// 解析 PA_DB_URL 为 (host, port, user, pass, db)。失败返回 None（保留默认）。
fn parse_db_url(s: &str) -> Option<(String, u16, String, String, String)> {
    let s = s.strip_prefix("mysql+aiomysql://")?;
    let (userinfo, rest) = match s.find('@') {
        Some(i) => (&s[..i], &s[i + 1..]),
        None => ("", s),
    };
    let (user, pass) = match userinfo.find(':') {
        Some(i) => (
            percent_decode_component(&userinfo[..i]),
            percent_decode_component(&userinfo[i + 1..]),
        ),
        None => (percent_decode_component(userinfo), String::new()),
    };
    let (hostport, dbpart) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i + 1..]),
        None => (rest, ""),
    };
    let db = dbpart.split('?').next().unwrap_or("");
    // hostport 可能是 "host:port"、"[ipv6]:port" 或 "[ipv6]"。
    let (host, port) = if let Some(rest) = hostport.strip_prefix('[') {
        let close = rest.find(']')?;
        let h = rest[..close].to_string();
        let p = rest[close + 1..]
            .strip_prefix(':')
            .and_then(|s| s.parse().ok())
            .unwrap_or(3306);
        (h, p)
    } else {
        match hostport.rfind(':') {
            Some(i) => (
                hostport[..i].to_string(),
                hostport[i + 1..].parse().unwrap_or(3306),
            ),
            None => (hostport.to_string(), 3306),
        }
    };
    Some((host, port, user, pass, percent_decode_component(db)))
}

fn parse_config_content(content: &str) -> LoadedConfig {
    let mut cfg = ConfigData::default();
    let mut legacy_password = None;
    let mut legacy_format = false;
    let mut secret_ref_configured = false;
    for line in content.lines() {
        let line = line.trim();
        if let Some(v) = line.strip_prefix("PA_DB_URL=") {
            if let Some((host, port, user, pass, db)) = parse_db_url(v) {
                cfg.db_host = host;
                cfg.db_port = port;
                cfg.db_user = user;
                cfg.db_name = db;
                cfg.db_password_configured = !pass.is_empty();
                legacy_password = Some(pass);
                legacy_format = true;
            }
        } else if let Some(v) = line.strip_prefix("PA_DB_HOST=") {
            cfg.db_host = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_DB_PORT=") {
            cfg.db_port = v.parse().unwrap_or(3306);
        } else if let Some(v) = line.strip_prefix("PA_DB_USER=") {
            cfg.db_user = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_DB_NAME=") {
            cfg.db_name = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_DB_SECRET_REF=") {
            secret_ref_configured = v == "secret://os-keyring/database/password";
            cfg.db_password_configured = secret_ref_configured;
        } else if let Some(v) = line.strip_prefix("PA_OLLAMA_BASE_URL=") {
            cfg.ollama_base_url = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_LLM_MODEL=") {
            cfg.llm_model = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_EMBED_MODEL=") {
            cfg.embed_model = v.to_string();
        } else if let Some(v) = line.strip_prefix("PA_MCP_ENABLED=") {
            cfg.mcp_enabled = v.eq_ignore_ascii_case("true");
        }
    }
    LoadedConfig {
        public: cfg,
        legacy_password,
        legacy_format,
        secret_ref_configured,
    }
}

fn read_config_impl() -> Result<LoadedConfig, String> {
    match fs::read_to_string(env_path()) {
        Ok(content) => Ok(parse_config_content(&content)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(parse_config_content("")),
        Err(_) => Err("failed to read configuration".to_string()),
    }
}

fn validate_env_value(name: &str, value: &str) -> Result<(), String> {
    if value.contains('\r') || value.contains('\n') {
        return Err(format!("invalid newline in {name}"));
    }
    Ok(())
}

fn validate_db_host(value: &str) -> Result<(), String> {
    use std::net::IpAddr;

    if value.is_empty() || value.trim() != value {
        return Err("invalid database host".to_string());
    }
    if value.parse::<IpAddr>().is_ok() {
        return Ok(());
    }
    if value.len() > 253
        || value.split('.').any(|label| {
            label.is_empty()
                || label.len() > 63
                || label.starts_with('-')
                || label.ends_with('-')
                || !label
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        })
    {
        return Err("invalid database host".to_string());
    }
    Ok(())
}

fn render_config(cfg: &ConfigData) -> Result<String, String> {
    for (name, value) in [
        ("database host", cfg.db_host.as_str()),
        ("database user", cfg.db_user.as_str()),
        ("database name", cfg.db_name.as_str()),
        ("Ollama URL", cfg.ollama_base_url.as_str()),
        ("LLM model", cfg.llm_model.as_str()),
        ("embedding model", cfg.embed_model.as_str()),
    ] {
        validate_env_value(name, value)?;
    }
    if cfg.db_host.is_empty() || cfg.db_user.is_empty() || cfg.db_name.is_empty() {
        return Err("database host, user, and name are required".to_string());
    }
    validate_db_host(&cfg.db_host)?;
    if cfg.db_port == 0 {
        return Err("database port must be between 1 and 65535".to_string());
    }

    let secret_ref = if cfg.db_password_configured {
        "PA_DB_SECRET_REF=secret://os-keyring/database/password\n"
    } else {
        ""
    };
    Ok(format!(
        "PA_DB_HOST={}\nPA_DB_PORT={}\nPA_DB_USER={}\nPA_DB_NAME={}\n{}PA_OLLAMA_BASE_URL={}\nPA_LLM_MODEL={}\nPA_EMBED_MODEL={}\nPA_MCP_ENABLED={}\n",
        cfg.db_host,
        cfg.db_port,
        cfg.db_user,
        cfg.db_name,
        secret_ref,
        cfg.ollama_base_url,
        cfg.llm_model,
        cfg.embed_model,
        cfg.mcp_enabled
    ))
}

fn write_config_impl(cfg: &ConfigData) -> Result<(), String> {
    let dir = config_dir();
    fs::create_dir_all(&dir).map_err(|_| "failed to create configuration directory".to_string())?;
    let content = render_config(cfg)?;
    fs::write(env_path(), content).map_err(|_| "failed to write configuration".to_string())
}

fn resolve_db_password_and_migrate(loaded: &mut LoadedConfig) -> Result<String, String> {
    if let Some(password) = credentials::get(DATABASE_PASSWORD_ACCOUNT)? {
        loaded.public.db_password_configured = true;
        if loaded.legacy_format || !loaded.secret_ref_configured {
            write_config_impl(&loaded.public)?;
        }
        return Ok(password);
    }

    if let Some(password) = loaded.legacy_password.as_deref() {
        if password.is_empty() {
            loaded.public.db_password_configured = false;
        } else {
            credentials::set(DATABASE_PASSWORD_ACCOUNT, password)?;
            loaded.public.db_password_configured = true;
        }
        write_config_impl(&loaded.public)?;
        return Ok(password.to_string());
    }

    if loaded.secret_ref_configured {
        return Err("database credential is configured but unavailable".to_string());
    }
    Ok(String::new())
}

// ============ 网络 ============

fn check_mysql_tcp(host: &str, port: u16) -> Result<(), String> {
    let addr = format!("{}:{}", host, port);
    let socket_addr = addr
        .to_socket_addrs()
        .map_err(|e| format!("解析地址失败: {}", e))?
        .next()
        .ok_or_else(|| "无法解析地址".to_string())?;
    TcpStream::connect_timeout(&socket_addr, Duration::from_secs(3))
        .map_err(|e| format!("连接失败: {}", e))?;
    Ok(())
}

/// 手写 HTTP GET 解析 JSON（避免引入 reqwest）。url 形如 http://host:port/api/tags。
/// 仅支持 http://（无 TLS）；https:// 明确拒绝，避免对 TLS 端口发明文。
fn http_get_json(url: &str) -> Result<serde_json::Value, String> {
    let no_scheme = url
        .strip_prefix("http://")
        .ok_or_else(|| "Ollama 地址仅支持 http://（不支持 https://）".to_string())?;
    let (host_port, path) = match no_scheme.find('/') {
        Some(i) => (&no_scheme[..i], &no_scheme[i..]),
        None => (no_scheme, "/"),
    };
    let socket_addr = host_port
        .to_socket_addrs()
        .map_err(|e| format!("解析地址失败: {}", e))?
        .next()
        .ok_or_else(|| "无法解析地址".to_string())?;
    let mut stream = TcpStream::connect_timeout(&socket_addr, Duration::from_secs(3))
        .map_err(|e| format!("连接失败: {}", e))?;
    // 读写超时：避免对非 HTTP 端口（如 MySQL 3306）read_to_end 永久阻塞。
    let rw_timeout = Some(Duration::from_secs(5));
    stream
        .set_read_timeout(rw_timeout)
        .map_err(|e| format!("设置读超时失败: {}", e))?;
    stream
        .set_write_timeout(rw_timeout)
        .map_err(|e| format!("设置写超时失败: {}", e))?;
    let req = format!(
        "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
        path, host_port
    );
    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("发送失败: {}", e))?;
    let mut buf = Vec::new();
    stream
        .read_to_end(&mut buf)
        .map_err(|e| format!("读取失败: {}", e))?;
    let sep = buf
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or_else(|| "无响应头分隔".to_string())?;
    let body = &buf[sep + 4..];
    serde_json::from_slice(body).map_err(|e| format!("解析 JSON 失败: {}", e))
}

/// 绑定 127.0.0.1:0 让 OS 分配一个空闲端口，立即关闭监听供 sidecar 复用。
fn pick_free_port() -> Option<u16> {
    TcpListener::bind("127.0.0.1:0")
        .ok()
        .and_then(|l| l.local_addr().ok())
        .map(|a| a.port())
}

/// 终止 sidecar 及其整个子进程树（0.2.1 QA 修复）。
///
/// ``CommandChild::kill`` 只终止 sidecar 直接进程，其派生的命令执行、git、
/// MCP stdio server 等子进程会残留为孤儿。Windows 上用 ``taskkill /T /F``
/// 递归终止进程树（PID 会随 0.2.1+ sidecar 复用重生成，故按当前 PID 终止），
/// 并保留 ``child.kill()`` 作为兜底；非 Windows 平台保持原 kill 语义。
fn kill_sidecar_tree(child: CommandChild) {
    #[cfg(target_os = "windows")]
    {
        let pid = child.pid();
        let _ = std::process::Command::new("taskkill")
            .args(["/T", "/F", "/PID", &pid.to_string()])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }
    let _ = child.kill();
}

/// Generate a 256-bit per-process bearer token using the operating system RNG.
fn generate_api_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::getrandom(&mut bytes)
        .map_err(|e| format!("failed to generate API startup token: {e}"))?;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut token = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        token.push(HEX[(byte >> 4) as usize] as char);
        token.push(HEX[(byte & 0x0f) as usize] as char);
    }
    Ok(token)
}

/// 比较 Ollama 模型名（去除 :tag 后缀做基名匹配，兼容 qwen2.5:14b... 这类）。
fn model_base(name: &str) -> &str {
    name.split(':').next().unwrap_or(name)
}

fn model_available(models: &[String], target: &str) -> bool {
    // 精确匹配优先；仅当 target 未带 :tag 时回退到基名匹配（兼容默认 latest）。
    if models.iter().any(|m| m == target) {
        return true;
    }
    if !target.contains(':') {
        let t = model_base(target);
        return models.iter().any(|m| model_base(m) == t);
    }
    false
}

// ============ 命令 ============

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn config_exists() -> bool {
    env_path().exists()
}

#[tauri::command]
fn read_config() -> Result<ConfigData, String> {
    Ok(read_config_impl()?.public)
}

#[tauri::command]
fn write_config(mut cfg: ConfigData) -> Result<(), String> {
    let mut loaded = read_config_impl()?;
    if loaded.legacy_format {
        let _ = resolve_db_password_and_migrate(&mut loaded)?;
    }
    let credential_available = credentials::exists(DATABASE_PASSWORD_ACCOUNT)?;
    if cfg.db_password_configured && !credential_available {
        return Err("database credential is not available in the system credential store".into());
    }
    cfg.db_password_configured = cfg.db_password_configured && credential_available;
    write_config_impl(&cfg)
}

#[tauri::command]
fn prompt_database_password() -> Result<DatabaseSecretPromptResult, String> {
    let outcome = credential_prompt::prompt_and_store(
        DATABASE_PASSWORD_ACCOUNT,
        "PrivateAgent database credential",
        "Enter the MySQL password. It will be stored in Windows Credential Manager.",
    )?;
    Ok(DatabaseSecretPromptResult {
        configured: credentials::exists(DATABASE_PASSWORD_ACCOUNT)?,
        cancelled: outcome == PromptOutcome::Cancelled,
    })
}

fn read_provider_secret_status() -> Result<ProviderSecretStatus, String> {
    Ok(ProviderSecretStatus {
        openai_configured: credentials::exists(OPENAI_API_KEY_ACCOUNT)?,
        claude_configured: credentials::exists(CLAUDE_API_KEY_ACCOUNT)?,
    })
}

#[tauri::command]
fn provider_secret_status() -> Result<ProviderSecretStatus, String> {
    read_provider_secret_status()
}

#[tauri::command]
fn prompt_provider_secret(provider: String) -> Result<ProviderSecretPromptResult, String> {
    let account = provider_account(&provider)?;
    let provider_label = match provider.as_str() {
        "openai" => "OpenAI",
        "claude" => "Claude",
        _ => return Err("unsupported provider secret".to_string()),
    };
    let outcome = credential_prompt::prompt_and_store(
        account,
        &format!("PrivateAgent {provider_label} credential"),
        &format!(
            "Enter the {provider_label} API key. It will be stored in Windows Credential Manager."
        ),
    )?;
    let status = read_provider_secret_status()?;
    Ok(ProviderSecretPromptResult {
        openai_configured: status.openai_configured,
        claude_configured: status.claude_configured,
        cancelled: outcome == PromptOutcome::Cancelled,
    })
}

#[tauri::command]
fn clear_provider_secret(provider: String) -> Result<ProviderSecretStatus, String> {
    credentials::delete(provider_account(&provider)?)?;
    read_provider_secret_status()
}

fn read_mcp_secret_status(alias: &str) -> Result<McpSecretStatus, String> {
    let account = mcp_account(alias)?;
    let aliases = read_mcp_secret_aliases()?;
    Ok(McpSecretStatus {
        reference: mcp_reference(alias)?,
        configured: mcp_secret_is_configured(&aliases, alias, credentials::exists(&account)?),
    })
}

fn mcp_secret_is_configured(aliases: &BTreeSet<String>, alias: &str, secret_exists: bool) -> bool {
    secret_exists && aliases.contains(alias)
}

#[tauri::command]
fn mcp_secret_status(alias: String) -> Result<McpSecretStatus, String> {
    read_mcp_secret_status(&alias)
}

#[tauri::command]
fn prompt_mcp_secret(alias: String) -> Result<McpSecretPromptResult, String> {
    let account = mcp_account(&alias)?;
    let outcome = credential_prompt::prompt_and_store(
        &account,
        "PrivateAgent MCP credential",
        "Enter the MCP credential. It will be stored in the system credential store.",
    )?;
    if credentials::exists(&account)? {
        let mut aliases = read_mcp_secret_aliases()?;
        aliases.insert(alias.clone());
        write_mcp_secret_aliases(&aliases)?;
    }
    let status = read_mcp_secret_status(&alias)?;
    Ok(McpSecretPromptResult {
        reference: status.reference,
        configured: status.configured,
        cancelled: outcome == PromptOutcome::Cancelled,
    })
}

#[tauri::command]
fn clear_mcp_secret(alias: String) -> Result<McpSecretStatus, String> {
    let account = mcp_account(&alias)?;
    credentials::delete(&account)?;
    let mut aliases = read_mcp_secret_aliases()?;
    aliases.remove(&alias);
    write_mcp_secret_aliases(&aliases)?;
    read_mcp_secret_status(&alias)
}

#[tauri::command]
async fn check_dependencies() -> DepResult {
    let mysql_reachable = check_mysql_tcp("127.0.0.1", 3306).is_ok();
    let ollama_reachable = http_get_json("http://127.0.0.1:11434/api/tags").is_ok();
    DepResult {
        mysql_reachable,
        ollama_reachable,
    }
}

#[tauri::command]
async fn test_connections(cfg: ConfigData) -> ConnResult {
    let mysql_res = check_mysql_tcp(&cfg.db_host, cfg.db_port);
    let mysql_ok = mysql_res.is_ok();
    let mysql_error = mysql_res.err();

    let (ollama_ok, ollama_error, ollama_models) = match http_get_json(&format!(
        "{}/api/tags",
        cfg.ollama_base_url.trim_end_matches('/')
    )) {
        Ok(v) => {
            let models: Vec<String> = v
                .get("models")
                .and_then(|m| m.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.get("name").and_then(|n| n.as_str()).map(String::from))
                        .collect()
                })
                .unwrap_or_default();
            (true, None, models)
        }
        Err(e) => (false, Some(e), Vec::new()),
    };

    let llm_model_available = ollama_ok && model_available(&ollama_models, &cfg.llm_model);
    let embed_model_available = ollama_ok && model_available(&ollama_models, &cfg.embed_model);

    ConnResult {
        mysql_ok,
        mysql_error,
        ollama_ok,
        ollama_error,
        ollama_models,
        llm_model_available,
        embed_model_available,
    }
}

#[tauri::command]
async fn start_sidecar(
    app: AppHandle,
    state: State<'_, SidecarState>,
) -> Result<SidecarStartResult, String> {
    // dev 模式：无 PyInstaller 产物，回退手动后端。
    if cfg!(debug_assertions) {
        return Ok(SidecarStartResult {
            ok: true,
            dev_mode: true,
            port: None,
            token: None,
            error: None,
        });
    }

    // 打包模式：尚未配置连接则不 spawn（避免拉起一个连不上 MySQL 的 sidecar）。
    if !env_path().exists() {
        return Ok(SidecarStartResult {
            ok: false,
            dev_mode: false,
            port: None,
            token: None,
            error: Some("尚未配置连接，请先完成向导".into()),
        });
    }

    let mut loaded = read_config_impl()?;
    let db_password = match resolve_db_password_and_migrate(&mut loaded) {
        Ok(password) => password,
        Err(error) => {
            return Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                token: None,
                error: Some(error),
            })
        }
    };
    let db_url = build_db_url(&loaded.public, &db_password);
    let openai_api_key = credentials::get(OPENAI_API_KEY_ACCOUNT)
        .ok()
        .flatten()
        .unwrap_or_default();
    let claude_api_key = credentials::get(CLAUDE_API_KEY_ACCOUNT)
        .ok()
        .flatten()
        .unwrap_or_default();
    let mcp_secrets_json = if loaded.public.mcp_enabled {
        collect_mcp_secrets_for_sidecar()?
    } else {
        Zeroizing::new("{}".to_string())
    };

    // 若已有 sidecar 在跑（重试 / 重配），先终止旧的——CommandChild 不会在 Drop 时杀进程，
    // 不主动 kill 会留下占用端口与 DB 连接的孤儿进程。用进程树终止，避免 sidecar 的
    // 命令/git/MCP 子进程残留。
    if let Some(prev) = state.child.lock().unwrap().take() {
        kill_sidecar_tree(prev);
        *state.port.lock().unwrap() = None;
        *state.token.lock().unwrap() = None;
    }

    let port = match pick_free_port() {
        Some(p) => p,
        None => {
            return Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                token: None,
                error: Some("分配空闲端口失败".into()),
            })
        }
    };

    let token = match generate_api_token() {
        Ok(token) => token,
        Err(error) => {
            return Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                token: None,
                error: Some(error),
            })
        }
    };

    match app.shell().sidecar(SIDECAR_BIN) {
        Ok(cmd) => match cmd
            .env("PA_API_PORT", port.to_string())
            .env("PA_API_TOKEN", token.clone())
            .env("PA_PARENT_PID", std::process::id().to_string())
            .env("PA_DB_URL", db_url)
            .env("PA_OPENAI_API_KEY", openai_api_key)
            .env("PA_CLAUDE_API_KEY", claude_api_key)
            .env("PA_MCP_SECRETS_JSON", mcp_secrets_json.as_str())
            .spawn()
        {
            Ok((mut rx, child)) => {
                // 转发 sidecar 输出到主进程日志
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(line) => {
                                println!("[sidecar] {}", String::from_utf8_lossy(&line))
                            }
                            CommandEvent::Stderr(line) => {
                                eprintln!("[sidecar] {}", String::from_utf8_lossy(&line))
                            }
                            CommandEvent::Terminated(status) => {
                                eprintln!("[sidecar] 进程结束: {:?}", status);
                                break;
                            }
                            _ => {}
                        }
                    }
                });
                // 不在此阻塞等待端口就绪——前端拿到 port 后自行轮询 /health。
                *state.port.lock().unwrap() = Some(port);
                *state.token.lock().unwrap() = Some(token.clone());
                *state.child.lock().unwrap() = Some(child);
                println!("[sidecar] 已启动 port={}", port);
                Ok(SidecarStartResult {
                    ok: true,
                    dev_mode: false,
                    port: Some(port),
                    token: Some(token),
                    error: None,
                })
            }
            Err(e) => Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                token: None,
                error: Some(format!("spawn 失败: {}", e)),
            }),
        },
        Err(e) => Ok(SidecarStartResult {
            ok: false,
            dev_mode: false,
            port: None,
            token: None,
            error: Some(format!("未找到 sidecar 二进制: {}", e)),
        }),
    }
}

/// 返回协商好的后端端口；None 时前端应回退到默认 127.0.0.1:8000。
#[tauri::command]
fn get_api_port(state: State<SidecarState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

/// Return the in-memory connection material for the current WebView session.
#[tauri::command]
fn get_api_connection(state: State<SidecarState>) -> Option<ApiConnection> {
    let port = *state.port.lock().unwrap();
    let token = state.token.lock().unwrap().clone();
    match (port, token) {
        (Some(port), Some(token)) => Some(ApiConnection { port, token }),
        _ => None,
    }
}

// ============ 更新 ============

#[tauri::command]
async fn check_for_updates(app: AppHandle) -> Result<Option<UpdateInfo>, String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    match updater.check().await.map_err(|e| e.to_string())? {
        Some(u) => Ok(Some(UpdateInfo {
            version: u.version.clone(),
            date: u.date.map(|d| d.to_string()),
            body: u.body.clone(),
        })),
        None => Ok(None),
    }
}

#[tauri::command]
async fn download_and_install_update(
    app: AppHandle,
    state: State<'_, SidecarState>,
) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "当前已是最新版本".to_string())?;
    // 安装会通过 std::process::exit 退出当前进程，绕过 RunEvent::Exit（sidecar 的唯一终止点），
    // 因此先手动终止 sidecar（进程树），避免更新后留下孤儿进程。
    if let Some(child) = state.child.lock().unwrap().take() {
        kill_sidecar_tree(child);
        *state.port.lock().unwrap() = None;
    }
    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn relaunch_app(app: AppHandle) {
    app.request_restart();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            greet,
            config_exists,
            read_config,
            write_config,
            prompt_database_password,
            provider_secret_status,
            prompt_provider_secret,
            clear_provider_secret,
            mcp_secret_status,
            prompt_mcp_secret,
            clear_mcp_secret,
            check_dependencies,
            test_connections,
            start_sidecar,
            get_api_port,
            get_api_connection,
            check_for_updates,
            download_and_install_update,
            relaunch_app,
        ])
        .setup(|app| {
            // 仅注册状态；sidecar 由前端引导流程按需 start_sidecar。
            app.manage(SidecarState {
                port: Mutex::new(None),
                token: Mutex::new(None),
                child: Mutex::new(None),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            // 应用退出时终止 sidecar 子进程树
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Some(child) = state.child.lock().unwrap().take() {
                        kill_sidecar_tree(child);
                        println!("[sidecar] 已终止子进程树");
                    }
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_config_is_parsed_without_serializing_the_password() {
        let loaded = parse_config_content(
            "PA_DB_URL=mysql+aiomysql://user:p%40ss@127.0.0.1:3307/app?charset=utf8mb4\n",
        );
        assert_eq!(loaded.legacy_password.as_deref(), Some("p@ss"));
        assert_eq!(loaded.public.db_port, 3307);
        assert!(loaded.public.db_password_configured);
        let public_json = serde_json::to_string(&loaded.public).unwrap();
        assert!(!public_json.contains("p@ss"));
        assert!(!public_json.contains("db_password\""));
    }

    #[test]
    fn rendered_config_contains_only_a_fixed_secret_reference() {
        let cfg = ConfigData {
            db_password_configured: true,
            ..ConfigData::default()
        };
        let rendered = render_config(&cfg).unwrap();
        assert!(rendered.contains("PA_DB_SECRET_REF=secret://os-keyring/database/password"));
        assert!(rendered.contains("PA_MCP_ENABLED=false"));
        assert!(!rendered.contains("PA_DB_URL="));
    }

    #[test]
    fn explicit_mcp_enablement_survives_desktop_config_roundtrip() {
        let loaded = parse_config_content("PA_MCP_ENABLED=true\n");
        assert!(loaded.public.mcp_enabled);
        assert!(render_config(&loaded.public)
            .unwrap()
            .contains("PA_MCP_ENABLED=true"));
    }

    #[test]
    fn mcp_secret_status_requires_both_index_and_keyring_value() {
        let aliases = BTreeSet::from(["calendar".to_string()]);
        assert!(mcp_secret_is_configured(&aliases, "calendar", true));
        assert!(!mcp_secret_is_configured(&aliases, "calendar", false));
        assert!(!mcp_secret_is_configured(&aliases, "missing", true));
    }

    #[test]
    fn database_url_percent_encodes_secret_delimiters() {
        let cfg = ConfigData::default();
        let url = build_db_url(&cfg, "p@ss:word");
        assert!(url.contains("p%40ss%3Aword"));
        assert!(!url.contains("p@ss:word"));
    }

    #[test]
    fn config_values_cannot_inject_new_environment_lines() {
        let cfg = ConfigData {
            db_name: "db\nPA_API_AUTH_ENABLED=false".to_string(),
            ..ConfigData::default()
        };
        assert!(render_config(&cfg).is_err());
    }

    #[test]
    fn database_host_cannot_redirect_a_secret_bearing_url() {
        for host in [
            "127.0.0.1@attacker.example",
            "host/path",
            "host?query",
            "host#fragment",
        ] {
            let cfg = ConfigData {
                db_host: host.to_string(),
                ..ConfigData::default()
            };
            assert!(render_config(&cfg).is_err(), "accepted unsafe host: {host}");
        }
        for host in ["localhost", "db.internal", "127.0.0.1", "::1"] {
            let cfg = ConfigData {
                db_host: host.to_string(),
                ..ConfigData::default()
            };
            assert!(render_config(&cfg).is_ok(), "rejected valid host: {host}");
        }
    }
}
