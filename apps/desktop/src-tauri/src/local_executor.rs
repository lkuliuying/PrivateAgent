//! 统一运行时的私有管道宿主；不监听端口，也不向网页暴露启动凭证。
use serde::Serialize;
use serde_json::{json, Value};
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
    origin: String,
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

fn write_frame(input: &Arc<Mutex<ChildStdin>>, frame: Value) -> Result<(), String> {
    let mut bytes = serde_json::to_vec(&frame).map_err(|_| "管道请求无效")?;
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
    server_origin: String,
    connection_profile: Option<Value>,
) -> Result<LocalConnection, String> {
    let config = connection_profile.unwrap_or_else(|| json!({"mode": "cloud", "server_origin": server_origin}));
    let config_json = serde_json::to_string(&config).map_err(|_| "连接配置无效")?;
    if config_json.len() > 8192 { return Err("连接配置超过大小限制".into()); }
    let mut guard = state.0.lock().map_err(|_| "本机执行器状态不可用")?;
    if let Some(process) = guard.as_mut() {
        if process.child.lock().map_err(|_| "无法检查本机执行器")?.try_wait().map_err(|_| "无法检查本机执行器")?.is_none() {
            if process.origin != config_json || process.broken.load(Ordering::Acquire) {
                return Err("运行时状态已改变，请先停止或重启客户端".into());
            }
            return Ok(LocalConnection { transport: "stdio", protocol: 2 });
        }
    }
    *guard = None;
    let token = crate::generate_api_token()?;
    let data = app.path().app_local_data_dir().map_err(|_| "无法定位本机数据目录")?.join("local-projects");
    std::fs::create_dir_all(&data).map_err(|_| "无法创建本机数据目录")?;
    let executable = std::env::current_exe().map_err(|_| "无法定位客户端")?
        .with_file_name(if cfg!(windows) { "private-agent-local.exe" } else { "private-agent-local" });
    if !executable.is_file() {
        return Err("安装包缺少本机执行器，请重新安装完整客户端".into());
    }
    let mut command = Command::new(executable);
    command.args(["--stdio", "--connection-json", &config_json,
                  "--parent-pid", &std::process::id().to_string()])
        .arg("--data-dir").arg(&data).current_dir(&data)
        .env_clear().env("PRIVATEAGENT_LOCAL_NONCE", token)
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
    let (reader_pending, reader_broken, reader_child) = (pending.clone(), broken.clone(), child.clone());
    std::thread::spawn(move || {
        let mut reader = BufReader::new(output);
        loop {
            let mut bytes = Vec::new();
            if reader.by_ref().take(MAX_FRAME + 1).read_until(b'\n', &mut bytes).is_err()
                || bytes.is_empty() || bytes.len() as u64 > MAX_FRAME || bytes.last() != Some(&b'\n') { break; }
            let Ok(frame) = serde_json::from_slice::<Value>(&bytes) else { break };
            let Some(id) = frame.get("id").and_then(Value::as_str) else { break };
            let Ok(mut requests) = reader_pending.lock() else { break };
            if let Some(channel) = requests.get(id) {
                let closed = channel.send(frame.clone()).is_err();
                if closed || frame.get("done") == Some(&Value::Bool(true)) || frame.get("error").is_some() {
                    requests.remove(id);
                }
            }
        }
        reader_broken.store(true, Ordering::Release);
        fail_pending(&reader_pending);
        if let Ok(mut process) = reader_child.lock() { terminate_owned_tree(&mut process); }
    });
    *guard = Some(Process { child, input, pending, broken, origin: config_json });
    Ok(LocalConnection { transport: "stdio", protocol: 2 })
}

#[tauri::command]
pub(crate) async fn local_executor_request(
    state: State<'_, LocalExecutorState>, id: String, request: Value, on_event: Channel<Value>,
) -> Result<(), String> {
    if id.is_empty() || id.len() > 64 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
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
    let result = tauri::async_runtime::spawn_blocking(move || {
        write_frame(&input, json!({"id": request_id, "method": "request", "params": request}))
    }).await.map_err(|_| "本机管道写入失败".to_string())?;
    if result.is_err() {
        if let Ok(mut requests) = pending.lock() { requests.remove(&id); }
    }
    result
}

#[tauri::command]
pub(crate) async fn local_executor_cancel(state: State<'_, LocalExecutorState>, id: String) -> Result<(), String> {
    if id.is_empty() || id.len() > 64 || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') {
        return Err("请求标识无效".into());
    }
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

pub(crate) fn stop(app: &AppHandle) {
    let Some(state) = app.try_state::<LocalExecutorState>() else { return };
    let Some(process) = state.0.lock().ok().and_then(|mut guard| guard.take()) else { return };
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
