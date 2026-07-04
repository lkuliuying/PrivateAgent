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
//   PA_DB_URL=mysql+aiomysql://user:pass@host:port/db?charset=utf8mb4
//   PA_OLLAMA_BASE_URL=...   PA_LLM_MODEL=...   PA_EMBED_MODEL=...

use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

/// sidecar 二进制名（对应 tauri.conf.json 的 externalBin，去掉平台后缀）。
const SIDECAR_BIN: &str = "personal-assistant-server";

/// sidecar 状态：协商端口与子进程句柄。
/// port 为 None 表示未启动 sidecar（dev 模式手动起后端，或尚未调用 start_sidecar）。
struct SidecarState {
    port: Mutex<Option<u16>>,
    child: Mutex<Option<CommandChild>>,
}

/// 连接配置（向导编辑的字段；写盘时组装成 PA_DB_URL 等）。
#[derive(Serialize, Deserialize, Clone)]
struct ConfigData {
    db_host: String,
    db_port: u16,
    db_user: String,
    db_password: String,
    db_name: String,
    ollama_base_url: String,
    llm_model: String,
    embed_model: String,
}

impl Default for ConfigData {
    fn default() -> Self {
        ConfigData {
            db_host: "127.0.0.1".into(),
            db_port: 3306,
            db_user: "root".into(),
            db_password: String::new(),
            db_name: "personal_assistant".into(),
            ollama_base_url: "http://127.0.0.1:11434".into(),
            llm_model: "qwen2.5:14b-instruct-q4_K_M".into(),
            embed_model: "bge-m3".into(),
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
    error: Option<String>,
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

/// 配置目录：dev=项目根（CARGO_MANIFEST_DIR 上溯 3 级），打包=%APPDATA%/personal-assistant。
fn config_dir() -> PathBuf {
    if cfg!(debug_assertions) {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // apps/desktop/src-tauri -> 项目根
        manifest
            .ancestors()
            .nth(3)
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| manifest.clone())
    } else {
        #[cfg(windows)]
        {
            let base = std::env::var("APPDATA").unwrap_or_default();
            PathBuf::from(base).join("personal-assistant")
        }
        #[cfg(not(windows))]
        {
            let base = std::env::var("XDG_DATA_HOME")
                .ok()
                .or_else(|| std::env::var("HOME").ok().map(|h| format!("{}/.local/share", h)))
                .unwrap_or_else(|| ".".to_string());
            PathBuf::from(base).join("personal-assistant")
        }
    }
}

fn env_path() -> PathBuf {
    config_dir().join(".env")
}

// ============ .env 读写 ============

fn build_db_url(cfg: &ConfigData) -> String {
    // IPv6 主机含 ':'，需用方括号包裹，否则 URL host 无法解析。
    let host = if cfg.db_host.contains(':') {
        format!("[{}]", cfg.db_host)
    } else {
        cfg.db_host.clone()
    };
    format!(
        "mysql+aiomysql://{}:{}@{}:{}/{}?charset=utf8mb4",
        cfg.db_user, cfg.db_password, host, cfg.db_port, cfg.db_name
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
        Some(i) => (userinfo[..i].to_string(), userinfo[i + 1..].to_string()),
        None => (userinfo.to_string(), String::new()),
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
    Some((host, port, user, pass, db.to_string()))
}

fn read_config_impl() -> ConfigData {
    let mut cfg = ConfigData::default();
    if let Ok(content) = fs::read_to_string(env_path()) {
        for line in content.lines() {
            let line = line.trim();
            if let Some(v) = line.strip_prefix("PA_DB_URL=") {
                if let Some((host, port, user, pass, db)) = parse_db_url(v) {
                    cfg.db_host = host;
                    cfg.db_port = port;
                    cfg.db_user = user;
                    cfg.db_password = pass;
                    cfg.db_name = db;
                }
            } else if let Some(v) = line.strip_prefix("PA_OLLAMA_BASE_URL=") {
                cfg.ollama_base_url = v.to_string();
            } else if let Some(v) = line.strip_prefix("PA_LLM_MODEL=") {
                cfg.llm_model = v.to_string();
            } else if let Some(v) = line.strip_prefix("PA_EMBED_MODEL=") {
                cfg.embed_model = v.to_string();
            }
        }
    }
    cfg
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
fn read_config() -> ConfigData {
    read_config_impl()
}

#[tauri::command]
fn write_config(cfg: ConfigData) -> Result<(), String> {
    let dir = config_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("创建配置目录失败: {}", e))?;
    let content = format!(
        "PA_DB_URL={}\nPA_OLLAMA_BASE_URL={}\nPA_LLM_MODEL={}\nPA_EMBED_MODEL={}\n",
        build_db_url(&cfg),
        cfg.ollama_base_url,
        cfg.llm_model,
        cfg.embed_model
    );
    fs::write(env_path(), content).map_err(|e| format!("写入配置失败: {}", e))?;
    Ok(())
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

    let (ollama_ok, ollama_error, ollama_models) =
        match http_get_json(&format!("{}/api/tags", cfg.ollama_base_url.trim_end_matches('/'))) {
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
            error: None,
        });
    }

    // 打包模式：尚未配置连接则不 spawn（避免拉起一个连不上 MySQL 的 sidecar）。
    if !env_path().exists() {
        return Ok(SidecarStartResult {
            ok: false,
            dev_mode: false,
            port: None,
            error: Some("尚未配置连接，请先完成向导".into()),
        });
    }

    // 若已有 sidecar 在跑（重试 / 重配），先终止旧的——CommandChild 不会在 Drop 时杀进程，
    // 不主动 kill 会留下占用端口与 DB 连接的孤儿进程。
    if let Some(prev) = state.child.lock().unwrap().take() {
        let _ = prev.kill();
        *state.port.lock().unwrap() = None;
    }

    let port = match pick_free_port() {
        Some(p) => p,
        None => {
            return Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                error: Some("分配空闲端口失败".into()),
            })
        }
    };

    match app.shell().sidecar(SIDECAR_BIN) {
        Ok(cmd) => match cmd.env("PA_API_PORT", port.to_string()).spawn() {
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
                *state.child.lock().unwrap() = Some(child);
                println!("[sidecar] 已启动 port={}", port);
                Ok(SidecarStartResult {
                    ok: true,
                    dev_mode: false,
                    port: Some(port),
                    error: None,
                })
            }
            Err(e) => Ok(SidecarStartResult {
                ok: false,
                dev_mode: false,
                port: None,
                error: Some(format!("spawn 失败: {}", e)),
            }),
        },
        Err(e) => Ok(SidecarStartResult {
            ok: false,
            dev_mode: false,
            port: None,
            error: Some(format!("未找到 sidecar 二进制: {}", e)),
        }),
    }
}

/// 返回协商好的后端端口；None 时前端应回退到默认 127.0.0.1:8000。
#[tauri::command]
fn get_api_port(state: State<SidecarState>) -> Option<u16> {
    *state.port.lock().unwrap()
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
    // 因此先手动终止 sidecar，避免更新后留下孤儿进程。
    if let Some(child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
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
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            greet,
            config_exists,
            read_config,
            write_config,
            check_dependencies,
            test_connections,
            start_sidecar,
            get_api_port,
            check_for_updates,
            download_and_install_update,
            relaunch_app,
        ])
        .setup(|app| {
            // 仅注册状态；sidecar 由前端引导流程按需 start_sidecar。
            app.manage(SidecarState {
                port: Mutex::new(None),
                child: Mutex::new(None),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            // 应用退出时终止 sidecar 子进程
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Some(child) = state.child.lock().unwrap().take() {
                        let _ = child.kill();
                        println!("[sidecar] 已终止子进程");
                    }
                }
            }
        });
}
