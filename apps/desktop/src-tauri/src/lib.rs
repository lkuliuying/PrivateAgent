// 桌面壳仅管理本机执行器、模型凭据、窗口和更新生命周期。
mod credentials;
mod local_executor;
mod updater_config;
#[cfg(all(windows, feature = "readiness-probe"))]
#[path = "../../../exec-host/src/readiness_probe.rs"]
mod readiness_probe;
#[cfg(all(windows, feature = "readiness-probe"))]
mod readiness_transport;

use credentials::{model_provider_account, model_provider_reference, validate_secret_alias};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_updater::UpdaterExt;
use zeroize::{Zeroize, Zeroizing};

const TRAY_SHOW_ID: &str = "tray-show";
const TRAY_EXIT_ID: &str = "tray-exit";

#[derive(Serialize)]
struct ModelProviderSecretStatus {
    reference: String,
    configured: bool,
}
#[derive(Default, Deserialize, Serialize)]
struct ModelProviderSecretIndex {
    aliases: Vec<String>,
}
#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    date: Option<String>,
    body: Option<String>,
}

fn config_dir() -> PathBuf {
    if cfg!(debug_assertions) {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        // 开发模式不读写仓库环境文件；保持已保存模型凭据索引的位置。
        manifest
            .ancestors()
            .nth(3)
            .map(|p| p.join(".run").join("desktop-config"))
            .unwrap_or_else(|| manifest.join("target").join("desktop-config"))
    } else {
        #[cfg(windows)]
        {
            let base = std::env::var("APPDATA").unwrap_or_default();
            PathBuf::from(base).join(if cfg!(feature = "qa") {
                "personal-assistant-candidate"
            } else {
                "personal-assistant"
            })
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

fn model_provider_secret_index_path() -> PathBuf {
    config_dir().join("model-provider-secret-index.json")
}

fn read_model_provider_secret_aliases() -> Result<BTreeSet<String>, String> {
    let path = model_provider_secret_index_path();
    if !path.exists() {
        return Ok(BTreeSet::new());
    }
    let raw =
        fs::read_to_string(path).map_err(|_| "model provider credential index read failed")?;
    let index: ModelProviderSecretIndex =
        serde_json::from_str(&raw).map_err(|_| "model provider credential index is invalid")?;
    if index.aliases.len() > 64 {
        return Err("too many model provider credentials".to_string());
    }
    let mut aliases = BTreeSet::new();
    for alias in index.aliases {
        validate_secret_alias(&alias)?;
        aliases.insert(alias);
    }
    Ok(aliases)
}

fn write_model_provider_secret_aliases(aliases: &BTreeSet<String>) -> Result<(), String> {
    if aliases.len() > 64 {
        return Err("too many model provider credentials".to_string());
    }
    fs::create_dir_all(config_dir())
        .map_err(|_| "model provider credential index directory failed")?;
    let encoded = serde_json::to_vec(&ModelProviderSecretIndex {
        aliases: aliases.iter().cloned().collect(),
    })
    .map_err(|_| "model provider credential index serialization failed")?;
    fs::write(model_provider_secret_index_path(), encoded)
        .map_err(|_| "model provider credential index write failed".to_string())
}

fn collect_model_provider_secrets_for_sidecar() -> Result<Zeroizing<String>, String> {
    let mut values = BTreeMap::new();
    for alias in read_model_provider_secret_aliases()? {
        let account = model_provider_account(&alias)?;
        if let Some(secret) = credentials::get(&account)? {
            values.insert(model_provider_reference(&alias)?, secret);
        }
    }
    let mut encoded = serde_json::to_string(&values)
        .map_err(|_| "model provider credential injection serialization failed")?;
    for secret in values.values_mut() {
        secret.zeroize();
    }
    if encoded.len() > 64 * 1024 {
        encoded.zeroize();
        return Err("model provider credential injection exceeds the process limit".to_string());
    }
    Ok(Zeroizing::new(encoded))
}

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

fn read_model_provider_secret_status(alias: &str) -> Result<ModelProviderSecretStatus, String> {
    let account = model_provider_account(alias)?;
    let aliases = read_model_provider_secret_aliases()?;
    Ok(ModelProviderSecretStatus {
        reference: model_provider_reference(alias)?,
        configured: aliases.contains(alias) && credentials::exists(&account)?,
    })
}

#[tauri::command]
fn model_provider_secret_status(alias: String) -> Result<ModelProviderSecretStatus, String> {
    read_model_provider_secret_status(&alias)
}

#[tauri::command]
fn set_model_provider_secret(
    alias: String,
    secret: String,
) -> Result<ModelProviderSecretStatus, String> {
    let normalized = secret.trim();
    if normalized.is_empty() {
        return Err("model provider API key must not be empty".to_string());
    }
    if normalized.len() > 16_384 {
        return Err("model provider API key is too long".to_string());
    }
    let account = model_provider_account(&alias)?;
    credentials::set(&account, normalized)?;
    let mut aliases = read_model_provider_secret_aliases()?;
    aliases.insert(alias.clone());
    write_model_provider_secret_aliases(&aliases)?;
    read_model_provider_secret_status(&alias)
}

#[tauri::command]
fn clear_model_provider_secret(alias: String) -> Result<ModelProviderSecretStatus, String> {
    credentials::delete(&model_provider_account(&alias)?)?;
    let mut aliases = read_model_provider_secret_aliases()?;
    aliases.remove(&alias);
    write_model_provider_secret_aliases(&aliases)?;
    read_model_provider_secret_status(&alias)
}

fn desktop_updater(
    app: &AppHandle,
    endpoint: Option<&str>,
) -> Result<tauri_plugin_updater::Updater, String> {
    let endpoints = updater_config::resolve_endpoints(app.config(), endpoint)?;
    // 更新地址可补充，签名公钥与安装目标仍由本客户端固定。
    app.updater_builder()
        .timeout(Duration::from_secs(120))
        .target(updater_config::update_target(&app.config().identifier)?)
        .endpoints(endpoints)
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn get_update_configuration(app: AppHandle) -> Result<updater_config::UpdateConfiguration, String> {
    updater_config::configuration(app.config())
}

#[tauri::command]
async fn check_for_updates(
    app: AppHandle,
    endpoint: Option<String>,
) -> Result<Option<UpdateInfo>, String> {
    let updater = desktop_updater(&app, endpoint.as_deref())?;
    match updater.check().await.map_err(|e| e.to_string())? {
        Some(u) => {
            updater_config::validate_release_target(&u.raw_json, &u.target)?;
            Ok(Some(UpdateInfo {
                version: u.version.clone(),
                date: u.date.map(|d| d.to_string()),
                body: u.body.clone(),
            }))
        }
        None => Ok(None),
    }
}

#[tauri::command]
async fn download_and_install_update(
    app: AppHandle,
    expected_version: Option<String>,
    endpoint: Option<String>,
) -> Result<(), String> {
    let updater = desktop_updater(&app, endpoint.as_deref())?;
    let mut update = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "当前已是最新版本".to_string())?;
    updater_config::validate_release_target(&update.raw_json, &update.target)?;
    // 插件的检查超时不传给下载对象，下载也需要独立的有界等待。
    update.timeout = Some(Duration::from_secs(120));
    if expected_version
        .as_ref()
        .is_some_and(|version| version != &update.version)
    {
        return Err("更新版本已经变化，请重新检查更新后再安装".to_string());
    }
    // 先下载并验证签名，失败时保留当前运行的本机执行器。
    let bytes = update
        .download(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    // 安装可能直接退出进程，因此先清理本机执行器。
    local_executor::stop(&app);
    update.install(bytes).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn relaunch_app(app: AppHandle) {
    app.request_restart();
}

fn show_main_window(app: &AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "未找到主窗口".to_string())?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())
}

#[tauri::command]
fn hide_main_window(app: AppHandle) -> Result<(), String> {
    app.get_webview_window("main")
        .ok_or_else(|| "未找到主窗口".to_string())?
        .hide()
        .map_err(|error| error.to_string())
}

#[tauri::command]
fn exit_app(app: AppHandle) {
    request_app_exit(&app);
}

fn request_app_exit(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.hide();
    }
    app.exit(0);
}

fn install_system_tray(app: &tauri::App) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, TRAY_SHOW_ID, "打开 PrivateAgent", true, None::<&str>)?;
    let exit_item = MenuItem::with_id(app, TRAY_EXIT_ID, "退出 PrivateAgent", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &exit_item])?;

    let mut tray = TrayIconBuilder::new()
        .tooltip("PrivateAgent")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            TRAY_SHOW_ID => {
                let _ = show_main_window(app);
            }
            TRAY_EXIT_ID => request_app_exit(app),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let _ = show_main_window(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg(all(windows, feature = "readiness-probe"))]
fn readiness_windows(
    config: &mut tauri::Config,
    active: bool,
) -> Vec<tauri::utils::config::WindowConfig> {
    if !active {
        return Vec::new();
    }
    let mut isolated = Vec::new();
    for window in config.app.windows.iter_mut().filter(|window| window.create) {
        isolated.push(window.clone());
        // 阻止 Tauri 在 setup 前按 Known Folder 创建正式 WebView 数据目录。
        window.create = false;
    }
    isolated
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    #[cfg(all(windows, feature = "readiness-probe"))]
    if let Err(error) =
        readiness_probe::initialize("desktop").and_then(|_| readiness_probe::validate_profile())
    {
        eprintln!("{error}");
        std::process::exit(78);
    }
    let context = tauri::generate_context!();
    #[cfg(all(windows, feature = "readiness-probe"))]
    let (context, isolated_windows) = {
        let mut context = context;
        let windows = readiness_windows(context.config_mut(), readiness_probe::config().is_some());
        (context, windows)
    };
    tauri::Builder::default()
        // 单实例插件先注册，避免重复启动本机执行器。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = show_main_window(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![
            model_provider_secret_status,
            set_model_provider_secret,
            clear_model_provider_secret,
            local_executor::start_local_executor,
            local_executor::stop_local_executor,
            local_executor::local_executor_request,
            local_executor::local_executor_cancel,
            check_for_updates,
            get_update_configuration,
            download_and_install_update,
            relaunch_app,
            hide_main_window,
            exit_app,
        ])
        .setup(move |app| {
            #[cfg(all(windows, feature = "readiness-probe"))]
            if let Some(config) = readiness_probe::config() {
                for window in isolated_windows {
                    tauri::WebviewWindowBuilder::from_config(app, &window)?
                        .data_directory(config.root.join("webview"))
                        .build()?;
                }
            }
            app.manage(local_executor::LocalExecutorState::default());
            install_system_tray(app)?;
            Ok(())
        })
        .build(context)
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                local_executor::stop(app_handle);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn execution_nonce_is_random_and_has_expected_entropy() {
        let first = generate_api_token().unwrap();
        let second = generate_api_token().unwrap();
        assert_eq!(first.len(), 64);
        assert!(first.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_ne!(first, second);
    }
    #[cfg(all(windows, feature = "readiness-probe"))]
    #[test]
    fn readiness_windows_cannot_create_the_default_webview_data_directory() {
        let mut config: tauri::Config = serde_json::from_value(serde_json::json!({
            "identifier": "com.personal-assistant.desktop", "app": {"windows": [{"label": "main"}]}
        }))
        .unwrap();
        assert!(readiness_windows(&mut config, false).is_empty());
        assert!(config.app.windows[0].create);
        let isolated = readiness_windows(&mut config, true);
        assert_eq!(isolated.len(), 1);
        assert!(!config.app.windows[0].create);
        assert!(isolated[0].create);
    }
}
