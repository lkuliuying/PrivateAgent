//! 统一运行时的私有管道宿主；不监听端口，也不向网页暴露启动凭证。
use serde::Serialize;
use serde_json::{json, Value};
use zeroize::Zeroizing;
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}};
use std::time::{Duration, Instant};
use tauri::{ipc::Channel, AppHandle, Manager, State};

const MAX_FRAME: u64 = 8 * 1024 * 1024;
type Pending = Arc<Mutex<HashMap<String, Channel<Value>>>>;

struct Process {
    child: Arc<Mutex<Child>>,
    input: Arc<Mutex<ChildStdin>>,
    pending: Pending,
    broken: Arc<AtomicBool>,
    credentials: Arc<crate::mcp_credentials::CredentialBridge>,
    model_config_json: String,
}

#[derive(Default)]
pub(crate) struct LocalExecutorState(Mutex<Option<Process>>);

#[derive(Serialize)]
pub(crate) struct LocalConnection {
    transport: &'static str,
    protocol: u8,
}

fn fail_pending(pending: &Pending) {
    if let Ok(mut requests) = pending.lock() {
        for (id, channel) in requests.drain() {
            let _ = channel.send(json!({"id": id, "error": "本机运行时管道已关闭，请重新启动客户端"}));
        }
    }
}

fn write_frame(input: &Arc<Mutex<ChildStdin>>, mut frame: Value) -> Result<(), String> {
    if let Some(request) = frame.get_mut("params") {
        crate::model_save_credentials::hydrate_request(request)?;
    }
    let encoded = serde_json::to_vec(&frame);
    crate::mcp_credentials::erase_frame(&mut frame);
    let mut bytes = Zeroizing::new(encoded.map_err(|_| "管道请求无效")?);
    if bytes.len() as u64 >= MAX_FRAME { return Err("管道请求超过大小限制".into()); }
    bytes.push(b'\n');
    let mut pipe = input.lock().map_err(|_| "管道不可用")?;
    pipe.write_all(&bytes).and_then(|_| pipe.flush()).map_err(|_| "本机运行时管道已关闭".into())
}

fn terminate_owned_tree(child: &mut Child) {
    if child.try_wait().ok().flatten().is_some() { return; }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // PyInstaller 单文件进程还有一个引导父进程；仅 kill 直接子进程会遗留运行时。
        let system_root = std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
        let executable = std::path::PathBuf::from(system_root).join("System32").join("taskkill.exe");
        if let Ok(mut killer) = Command::new(executable).args(["/T", "/F", "/PID", &child.id().to_string()])
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).creation_flags(0x08000000).spawn() {
            let deadline = Instant::now() + Duration::from_secs(2);
            while Instant::now() < deadline && killer.try_wait().ok().flatten().is_none() {
                std::thread::sleep(Duration::from_millis(20));
            }
            let _ = killer.kill();
            let _ = killer.wait();
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[tauri::command]
pub(crate) fn start_local_executor(
    app: AppHandle,
    state: State<'_, LocalExecutorState>,
    model_config: Value,
) -> Result<LocalConnection, String> {
    let model_json = serde_json::to_string(&model_config).map_err(|_| "模型配置无效")?;
    if !model_config.is_object() || model_json.len() > 4096 { return Err("模型配置无效".into()); }
    let mut guard = state.0.lock().map_err(|_| "本机执行器状态不可用")?;
    if let Some(process) = guard.as_mut() {
        if process.child.lock().map_err(|_| "无法检查本机执行器")?.try_wait().map_err(|_| "无法检查本机执行器")?.is_none() {
            if process.model_config_json != model_json || process.broken.load(Ordering::Acquire) {
                return Err("运行时状态已改变，请先停止或重启客户端".into());
            }
            return Ok(LocalConnection { transport: "stdio", protocol: 2 });
        }
    }
    *guard = None;
    let token = crate::generate_api_token()?;
    let data = app.path().app_local_data_dir().map_err(|_| "无法定位本机数据目录")?.join("local-projects");
    #[cfg(all(windows, feature = "readiness-probe"))]
    let data = crate::readiness_probe::local_data_directory(data, &app.config().identifier)?;
    #[cfg(all(windows, feature = "readiness-probe"))]
    crate::readiness_probe::validate_data_directory(&data)?;
    std::fs::create_dir_all(&data).map_err(|_| "无法创建本机数据目录")?;
    let executable = std::env::current_exe().map_err(|_| "无法定位客户端")?
        .with_file_name(if cfg!(windows) { "private-agent-local.exe" } else { "private-agent-local" });
    if !executable.is_file() {
        return Err("安装包缺少本机执行器，请重新安装完整客户端".into());
    }
    let mut command = Command::new(executable);
    // 仅从系统凭据库向受控本机执行器注入密钥，执行器启动后立即移除环境变量。
    let model_provider_secrets = crate::collect_model_provider_secrets_for_sidecar()?;
    command.args(["--stdio", "--model-json", &model_json,
                  "--parent-pid", &std::process::id().to_string()])
        .arg("--data-dir").arg(&data).current_dir(&data)
        .env_clear().env("PRIVATEAGENT_LOCAL_NONCE", token)
        .env("PA_MODEL_PROVIDER_SECRETS_JSON", model_provider_secrets.as_str())
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    for (key, value) in std::env::vars_os() {
        let name = key.to_string_lossy().to_ascii_uppercase();
        if ["PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "NUMBER_OF_PROCESSORS"].contains(&name.as_str()) {
            command.env(key, value);
        }
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // 隐藏本机后台进程窗口。
    }
    let mut child = command.spawn().map_err(|_| "无法启动本机执行器，请检查安装完整性")?;
    let input = Arc::new(Mutex::new(child.stdin.take().ok_or("运行时缺少输入管道")?));
    let output = child.stdout.take().ok_or("运行时缺少输出管道")?;
    let child = Arc::new(Mutex::new(child));
    let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
    let broken = Arc::new(AtomicBool::new(false));
    let credentials = Arc::new(crate::mcp_credentials::CredentialBridge::new());
    let (credential_sender, credential_receiver) = std::sync::mpsc::sync_channel::<Value>(16);
    let (credential_input, credential_bridge) = (input.clone(), credentials.clone());
    // 系统凭据库可能阻塞；独立有界队列避免阻塞普通响应读取，也不生成 WebView channel。
    std::thread::spawn(move || {
        while let Ok(frame) = credential_receiver.recv() {
            let reply = credential_bridge.handle(frame);
            if write_frame(&credential_input, reply).is_err() { break; }
        }
    });
    let (reader_pending, reader_broken, reader_child) = (pending.clone(), broken.clone(), child.clone());
    let (reader_input, reader_credentials) = (input.clone(), credentials.clone());
    std::thread::spawn(move || {
        let mut reader = BufReader::new(output);
        loop {
            let mut bytes = Zeroizing::new(Vec::new());
            if reader.by_ref().take(MAX_FRAME + 1).read_until(b'\n', &mut bytes).is_err()
                || bytes.is_empty() || bytes.len() as u64 > MAX_FRAME || bytes.last() != Some(&b'\n') { break; }
            let Ok(frame) = serde_json::from_slice::<Value>(&bytes) else { break };
            if frame.get("method").and_then(Value::as_str) == Some("mcp_credential") {
                match credential_sender.try_send(frame) {
                    Ok(()) => {}
                    Err(std::sync::mpsc::TrySendError::Full(mut frame)) => {
                        let id = frame.get("id").cloned().unwrap_or(Value::Null);
                        crate::mcp_credentials::erase_frame(&mut frame);
                        if write_frame(&reader_input, json!({"id":id, "method":"mcp_credential_result", "error":"credential_busy"})).is_err() { break; }
                    }
                    Err(std::sync::mpsc::TrySendError::Disconnected(mut frame)) => {
                        crate::mcp_credentials::erase_frame(&mut frame);
                        break;
                    }
                }
                continue;
            }
            let Some(id) = frame.get("id").and_then(Value::as_str) else { break };
            if id.starts_with("mcp-") || frame.get("method").is_some() { break; }
            #[cfg(all(windows, feature = "readiness-probe"))]
            let drop_frame = crate::readiness_transport::drop_frame(&frame);
            #[cfg(not(all(windows, feature = "readiness-probe")))]
            let drop_frame = false;
            let Ok(mut requests) = reader_pending.lock() else { break };
            if let Some(channel) = requests.get(id) {
                let closed = !drop_frame && channel.send(frame.clone()).is_err();
                if closed || frame.get("done") == Some(&Value::Bool(true)) || frame.get("error").is_some() {
                    requests.remove(id);
                }
            }
        }
        reader_broken.store(true, Ordering::Release);
        reader_credentials.close();
        fail_pending(&reader_pending);
        if let Ok(mut process) = reader_child.lock() { terminate_owned_tree(&mut process); }
    });
    *guard = Some(Process { child, input, pending, broken, credentials, model_config_json: model_json });
    Ok(LocalConnection { transport: "stdio", protocol: 2 })
}

#[tauri::command]
pub(crate) async fn local_executor_request(
    state: State<'_, LocalExecutorState>, id: String, request: Value, on_event: Channel<Value>,
) -> Result<(), String> {
    if id.is_empty() || id.starts_with("mcp-") || id.len() > 64 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
        return Err("请求标识无效".into());
    }
    let (input, pending) = {
        let guard = state.0.lock().map_err(|_| "运行时状态不可用")?;
        let process = guard.as_ref().ok_or("本机运行时尚未启动")?;
        if process.broken.load(Ordering::Acquire) { return Err("本机运行时已断开".into()); }
        (process.input.clone(), process.pending.clone())
    };
    {
        let mut requests = pending.lock().map_err(|_| "运行时状态不可用")?;
        if requests.len() >= 64 || requests.contains_key(&id) { return Err("本机请求并发数超出限制".into()); }
        requests.insert(id.clone(), on_event);
    }
    let request_id = id.clone();
    #[cfg(all(windows, feature = "readiness-probe"))]
    crate::readiness_transport::request(&id, &request);
    let result = tauri::async_runtime::spawn_blocking(move || {
        write_frame(&input, json!({"id": request_id, "method": "request", "params": request}))
    }).await.map_err(|_| "本机管道写入失败".to_string())?;
    if result.is_err() {
        if let Ok(mut requests) = pending.lock() { requests.remove(&id); }
        #[cfg(all(windows, feature = "readiness-probe"))]
        crate::readiness_transport::cancel(&id);
    }
    result
}

#[tauri::command]
pub(crate) async fn local_executor_cancel(state: State<'_, LocalExecutorState>, id: String) -> Result<(), String> {
    if id.is_empty() || id.starts_with("mcp-") || id.len() > 64 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
        return Err("请求标识无效".into());
    }
    #[cfg(all(windows, feature = "readiness-probe"))]
    crate::readiness_transport::cancel(&id);
    let input = {
        let guard = state.0.lock().map_err(|_| "运行时状态不可用")?;
        let Some(process) = guard.as_ref() else { return Ok(()) };
        if let Ok(mut requests) = process.pending.lock() { requests.remove(&id); }
        process.input.clone()
    };
    tauri::async_runtime::spawn_blocking(move || write_frame(&input, json!({"id": id, "method": "cancel"})))
        .await.map_err(|_| "本机管道取消失败".to_string())?
}

#[tauri::command]
pub(crate) fn stop_local_executor(app: AppHandle) { stop(&app); }

#[tauri::command]
pub(crate) async fn set_mcp_credential(
    state: State<'_, LocalExecutorState>, binding: crate::mcp_credentials::Binding, value: String,
) -> Result<crate::mcp_credentials::CredentialStatus, String> {
    let value = Zeroizing::new(value);
    let bridge = {
        let guard = state.0.lock().map_err(|_| "本机运行时状态不可用")?;
        let process = guard.as_ref().ok_or("本机运行时尚未启动")?;
        if process.broken.load(Ordering::Acquire) { return Err("MCP 凭据连接已关闭，请重新连接".into()); }
        process.credentials.clone()
    };
    tauri::async_runtime::spawn_blocking(move || bridge.save_static(binding, value.to_string()))
        .await.map_err(|_| "MCP 凭据操作未完成，请重新连接后核对配置".to_string())?
        .map_err(|_| "MCP 凭据未确认保存；请重新准备配置后重试，输入无需重建".to_string())
}

pub(crate) fn stop(app: &AppHandle) {
    let Some(state) = app.try_state::<LocalExecutorState>() else { return };
    let Some(process) = state.0.lock().ok().and_then(|mut guard| guard.take()) else { return };
    process.credentials.close();
    let shutdown_input = process.input.clone();
    // 不能让阻塞的管道写入阻止退出超时与最终进程回收。
    std::thread::spawn(move || { let _ = write_frame(&shutdown_input, json!({"method": "shutdown"})); });
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if let Ok(mut child) = process.child.lock() {
            if child.try_wait().ok().flatten().is_some() { fail_pending(&process.pending); return; }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    // 正常关闭未完成时，按当前持有句柄的进程回收其引导进程和后代。
    if let Ok(mut child) = process.child.lock() {
        terminate_owned_tree(&mut child);
    }
    fail_pending(&process.pending);
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use std::os::windows::process::CommandExt;

    #[test]
    #[ignore = "仅由进程树验证测试启动"]
    fn sleeper() {
        if let Some(path) = std::env::var_os("PRIVATEAGENT_TREE_TEST_PID") {
            let descendant = Command::new(std::env::current_exe().unwrap())
                .args(["--exact", "local_executor::tests::sleeper", "--ignored"])
                .env_remove("PRIVATEAGENT_TREE_TEST_PID").creation_flags(0x08000000)
                .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
            std::fs::write(path, descendant.id().to_string()).unwrap();
        }
        std::thread::sleep(Duration::from_secs(60));
    }

    #[test]
    fn forced_stop_reaps_bootloader_descendants() {
        let path = std::env::temp_dir().join(format!("privateagent-tree-test-{}.pid", std::process::id()));
        assert!(!path.exists());
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "local_executor::tests::sleeper", "--ignored"])
            .env("PRIVATEAGENT_TREE_TEST_PID", &path).creation_flags(0x08000000)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
        let deadline = Instant::now() + Duration::from_secs(10);
        while !path.exists() && Instant::now() < deadline { std::thread::sleep(Duration::from_millis(20)); }
        let pid = std::fs::read_to_string(&path).ok().and_then(|value| value.parse::<u32>().ok());
        terminate_owned_tree(&mut child);
        let _ = std::fs::remove_file(&path);
        let pid = pid.expect("测试后代未启动");
        unsafe {
            use windows_sys::Win32::Foundation::{CloseHandle, WAIT_TIMEOUT};
            use windows_sys::Win32::System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE};
            let handle = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            if !handle.is_null() {
                let result = WaitForSingleObject(handle, 2000);
                CloseHandle(handle);
                assert_ne!(result, WAIT_TIMEOUT, "后代进程仍在运行");
            }
        }
        assert!(child.try_wait().unwrap().is_some());
    }
}
