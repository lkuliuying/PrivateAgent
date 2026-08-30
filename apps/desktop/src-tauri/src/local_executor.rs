//! Isolated lifecycle for the connected edition's desktop-only executor.
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, State};

struct Process {
    child: Child,
    port: u16,
    token: String,
    origin: String,
}

#[derive(Default)]
pub(crate) struct LocalExecutorState(Mutex<Option<Process>>);

#[tauri::command]
pub(crate) fn start_local_executor(
    app: AppHandle,
    state: State<'_, LocalExecutorState>,
    server_origin: String,
) -> Result<crate::ApiConnection, String> {
    // Python additionally validates the URL before making any network request.
    if !server_origin.starts_with("https://") || server_origin.contains(['\r', '\n', '@', '?', '#']) {
        return Err("服务器地址必须是 HTTPS 源站".into());
    }
    let mut guard = state.0.lock().map_err(|_| "本机执行器状态不可用")?;
    if let Some(process) = guard.as_mut() {
        if process.child.try_wait().map_err(|_| "无法检查本机执行器")?.is_none() {
            if process.origin != server_origin {
                return Err("切换服务器前请重新启动客户端".into());
            }
            return Ok(crate::ApiConnection { port: process.port, token: process.token.clone() });
        }
    }
    *guard = None;
    let port = crate::pick_free_port().ok_or("无法分配本机端口")?;
    let token = crate::generate_api_token()?;
    let data = app.path().app_local_data_dir().map_err(|_| "无法定位本机数据目录")?.join("local-projects");
    std::fs::create_dir_all(&data).map_err(|_| "无法创建本机数据目录")?;
    let executable = std::env::current_exe().map_err(|_| "无法定位客户端")?
        .with_file_name(if cfg!(windows) { "private-agent-local.exe" } else { "private-agent-local" });
    if !executable.is_file() {
        return Err("安装包缺少本机执行器，请重新安装完整客户端".into());
    }
    let mut command = Command::new(executable);
    command.args(["--port", &port.to_string(), "--server", &server_origin,
                  "--parent-pid", &std::process::id().to_string()])
        .arg("--data-dir").arg(&data).current_dir(&data)
        .env_clear().env("PRIVATEAGENT_LOCAL_NONCE", &token)
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
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
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let child = command.spawn().map_err(|_| "无法启动本机执行器，请检查安装完整性")?;
    *guard = Some(Process { child, port, token: token.clone(), origin: server_origin });
    Ok(crate::ApiConnection { port, token })
}

pub(crate) fn stop(app: &AppHandle) {
    let Some(state) = app.try_state::<LocalExecutorState>() else { return };
    let Some(mut process) = state.0.lock().ok().and_then(|mut guard| guard.take()) else { return };
    if process.child.try_wait().ok().flatten().is_some() { return; }
    let address = SocketAddr::from(([127, 0, 0, 1], process.port));
    if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) {
        let _ = stream.set_read_timeout(Some(Duration::from_secs(3)));
        let _ = stream.set_write_timeout(Some(Duration::from_secs(1)));
        let request = format!("POST /internal/shutdown HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nX-PrivateAgent-Local: {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n", process.port, process.token);
        let _ = stream.write_all(request.as_bytes());
        let mut response = [0_u8; 1024];
        let _ = stream.read(&mut response);
    }
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if process.child.try_wait().ok().flatten().is_some() { return; }
        std::thread::sleep(Duration::from_millis(100));
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        let _ = Command::new("taskkill").args(["/PID", &process.child.id().to_string(), "/T", "/F"])
            .creation_flags(0x08000000).stdout(Stdio::null()).stderr(Stdio::null()).status();
    }
    let _ = process.child.kill();
    let _ = process.child.wait();
}
