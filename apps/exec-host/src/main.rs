//! PrivateAgent Exec Host（专项计划 §11 / AD-T02 / CT-6）。
//!
//! 职责边界（红线）：
//! - 只接收 Python Agent Core 策略决议后的规范化执行请求；
//! - 负责进程创建、Job Object 进程树级联终止、MIC 降级受限启动、
//!   stdout/stderr 分流、超时、取消、进程退出事实；
//! - 不发现工具、不调用模型、不请求网络授权、不写任何数据库，
//!   不得把执行标记为业务"完成"——完成判定只属于 Python Core。
//!
//! 协议：stdin/stdout JSONL（`agent_v2/execution/contracts.py` 冻结）。
//! CT6-01+CT-6 沙箱闭环：initialize / health/read / execution/start
//! （mode=argv|pty；integrity_level=inherit|low；stdin_mode=closed|pipe）
//! / execution/stdin/write（execution id + session nonce 绑定，§11.4）
//! / execution/output/read（有界窗口续读）/ execution/cancel
//! / execution/status/read / shutdown。

use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufWriter, Read, Write};
use std::process::{Child, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

#[cfg(windows)]
mod sandbox;

const PROTOCOL_VERSION: &str = "1.0";
const MAX_MESSAGE_BYTES: usize = 1024 * 1024;
const POLL_INTERVAL_MS: u64 = 50;
const DELTA_LIMIT: usize = 64 * 1024;
const READ_CHUNK_SIZE: usize = 8 * 1024;
/// execution/output/read 滑动窗口上限（超限丢弃头部，§11.4 有界）。
const OUTPUT_WINDOW_CAP: usize = 1024 * 1024;
const STDIN_WRITE_MAX: usize = 262_144;

type SharedChild = Arc<Mutex<ChildSlot>>;

/// 双路径子进程控制面：std（inherit 完整性）/ 受限 Low MIC。
enum ChildSlot {
    Std(Box<Child>),
    #[cfg(windows)]
    Restricted(sandbox::RestrictedChild),
}

impl ChildSlot {
    #[cfg(windows)]
    fn resume(&self) {
        if let ChildSlot::Restricted(child) = self {
            child.resume();
        }
    }

    fn poll_exit(&mut self) -> std::io::Result<Option<i32>> {
        match self {
            ChildSlot::Std(child) => Ok(child.try_wait()?.map(|status| {
                // 非 Exit() 终止（TerminateProcess/Job kill）时 code() 为 None，
                // 以 1 报告失败事实，不伪造正常退出码。
                status.code().unwrap_or(1)
            })),
            #[cfg(windows)]
            ChildSlot::Restricted(child) => child.poll_exit().map(|code| {
                code.map(|c| if c == i32::MIN { 1 } else { c })
            }),
        }
    }

    fn pid(&self) -> u32 {
        match self {
            ChildSlot::Std(child) => child.id(),
            #[cfg(windows)]
            ChildSlot::Restricted(child) => {
                sandbox::pid_of_process_handle(child.process_handle)
            }
        }
    }

    fn kill(&mut self) {
        match self {
            ChildSlot::Std(child) => {
                let _ = child.kill();
            }
            #[cfg(windows)]
            ChildSlot::Restricted(child) => child.kill(),
        }
    }
}

/// stdin 写入端：std 路径 ChildStdin / 受限、AC、PTY 路径原生管道。
enum StdinSink {
    Std(std::process::ChildStdin),
    #[cfg(windows)]
    Raw(sandbox::PipeWriter),
}

impl StdinSink {
    fn write_all(&mut self, data: &[u8]) -> std::io::Result<()> {
        match self {
            StdinSink::Std(child) => {
                use std::io::Write;
                child.write_all(data)?;
                child.flush()
            }
            #[cfg(windows)]
            StdinSink::Raw(writer) => writer.write_all(data),
        }
    }
}

/// 输出滑动窗口：追加原始字节并记录累计偏移（供 output/read 续读）。
struct OutputTail {
    buffer: Vec<u8>,
    total: u64,
}

impl OutputTail {
    fn new() -> Self {
        Self { buffer: Vec::new(), total: 0 }
    }

    fn push(&mut self, data: &[u8]) {
        self.buffer.extend_from_slice(data);
        self.total += data.len() as u64;
        if self.buffer.len() > OUTPUT_WINDOW_CAP {
            let drop = self.buffer.len() - OUTPUT_WINDOW_CAP;
            self.buffer.drain(..drop);
        }
    }
}

struct ExecutionState {
    child: SharedChild,
    sequence: Arc<AtomicU64>,
    cancel_requested: Arc<AtomicBool>,
    stdin: Arc<Mutex<Option<StdinSink>>>,
    session_nonce: Option<String>,
    output_tail: Arc<Mutex<OutputTail>>,
    /// PTY 模式：持有伪控制台句柄直至执行移除（drop 即释放）。
    /// 仅作生命周期守卫，不被读取。
    #[cfg(windows)]
    #[allow(dead_code)]
    pty: Arc<Mutex<Option<sandbox::PseudoConsole>>>,
}

struct Host {
    writer: Mutex<BufWriter<std::io::Stdout>>,
    executions: Mutex<HashMap<String, ExecutionState>>,
}

fn host() -> &'static Host {
    static HOST: OnceLock<Host> = OnceLock::new();
    HOST.get_or_init(|| Host {
        writer: Mutex::new(BufWriter::new(std::io::stdout())),
        executions: Mutex::new(HashMap::new()),
    })
}

impl Host {
    fn send(&self, value: &Value) {
        let mut line = value.to_string().into_bytes();
        if line.len() > MAX_MESSAGE_BYTES {
            return; // 超限拒绝发送（失败关闭）
        }
        line.push(b'\n');
        let mut writer = self.writer.lock().unwrap();
        let _ = writer.write_all(&line);
        let _ = writer.flush();
    }

    fn respond(&self, id: u64, result: Value) {
        self.send(&json!({"id": id, "result": result}));
    }

    fn respond_error(&self, id: u64, code: &str, message: &str) {
        self.send(&json!({"id": id, "error": {"code": code,
            "message": message, "retryable": false, "details": null,
            "trace_id": null}}));
    }

    fn notify(&self, event: Value) {
        self.send(&event);
    }

    fn health(&self) -> Value {
        let active = self.executions.lock().unwrap().len() as u64;
        json!({
            "protocol_version": PROTOCOL_VERSION,
            // Job Object 级联终止 + Low MIC 写拦截已落地；
            // 网络强制边界（ADR-004 S4）未闭环前仍如实上报 false。
            "sandbox_available": false,
            "modes": ["argv", "pty"],
            "active_sessions": active
        })
    }
}

fn main() {
    // 启动期自分配 Job：此后所有子进程经继承自动入 Job；
    // KILL_ON_JOB_CLOSE 在进程退出时兜底清理孤儿孙进程。
    // 自分配被拒（沙箱链嵌套限制）→ 降级 taskkill /T 树级联。
    #[cfg(windows)]
    {
        let _ = sandbox::host_job();
    }
    let host = host();
    let stdin = std::io::stdin();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() || line.len() > MAX_MESSAGE_BYTES {
            continue;
        }
        let Ok(message) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        let Some(request_id) = message.get("id").and_then(Value::as_u64) else {
            continue;
        };
        match message.get("method").and_then(Value::as_str) {
            Some("initialize") | Some("health/read") => {
                host.respond(request_id, host.health())
            }
            Some("execution/start") => handle_start(request_id, &message),
            Some("execution/cancel") => handle_cancel(request_id, &message),
            Some("execution/stdin/write") => handle_stdin_write(request_id, &message),
            Some("execution/output/read") => handle_output_read(request_id, &message),
            Some("execution/status/read") => {
                let running = host.executions.lock().unwrap().len() as u64;
                host.respond(request_id, json!({ "active": running }));
            }
            Some("shutdown") => {
                host.respond(request_id, json!({ "bye": true }));
                break;
            }
            Some(other) => host.respond_error(request_id, "unknown_method", other),
            None => {}
        }
    }
    // 退出前级联终止全部执行树（Drop 触发 KILL_ON_JOB_CLOSE 双保险）。
    host.executions.lock().unwrap().clear();
}

fn handle_start(request_id: u64, message: &Value) {
    let host = host();
    let fail = |code: &str, msg: &str| -> () {
        host.respond_error(request_id, code, msg);
    };
    let Some(params) = message.get("params") else {
        return fail("bad_params", "缺少 params");
    };
    let Some(execution_id_value) = params.get("execution_id").and_then(Value::as_str)
    else {
        return fail("bad_params", "缺少 execution_id");
    };
    let execution_id = execution_id_value.to_string();
    let mode = params.get("mode").and_then(Value::as_str).unwrap_or("argv");
    if mode != "argv" && mode != "pty" {
        return fail("unsupported_mode", "仅支持 argv/pty 模式");
    }
    let stdin_mode = params.get("stdin_mode").and_then(Value::as_str).unwrap_or("closed");
    if stdin_mode != "closed" && stdin_mode != "pipe" {
        return fail("bad_params", "stdin_mode 非法");
    }
    let session_nonce = params
        .get("session_nonce")
        .and_then(Value::as_str)
        .map(str::to_string);
    // §11.4：write_stdin 必须绑定 execution id + session nonce——
    // 开启 stdin 管道时 nonce 必填，缺失即拒绝，不隐式放行。
    if stdin_mode == "pipe" {
        match session_nonce.as_deref() {
            Some(nonce) if (8..=128).contains(&nonce.len()) => {}
            _ => {
                return fail(
                    "bad_params",
                    "stdin_mode=pipe 需要 8..128 字符的 session_nonce",
                )
            }
        }
    }
    let want_stdin = stdin_mode == "pipe";
    let integrity_raw = params.get("integrity_level").and_then(Value::as_str);

    #[cfg(windows)]
    {
        let integrity = match sandbox::IntegrityLevel::parse(integrity_raw) {
            Some(level) => level,
            None => return fail("bad_params", "integrity_level 非法"),
        };
        let Some(argv) = params.get("argv").and_then(Value::as_array) else {
            return fail("bad_params", "缺少 argv");
        };
        if argv.is_empty() || argv.len() > 64 {
            return fail("bad_params", "argv 长度必须 1..64");
        }
        let mut program: Vec<String> = Vec::with_capacity(argv.len());
        for item in argv {
            match item.as_str() {
                Some(entry) if !entry.is_empty() && entry.len() <= 4096 => {
                    program.push(entry.to_string());
                }
                _ => return fail("bad_params", "argv 每项必须是非空字符串"),
            }
        }
        let cwd = params.get("cwd").and_then(Value::as_str).unwrap_or(".");
        let timeout_ms = params
            .get("timeout_ms")
            .and_then(Value::as_u64)
            .unwrap_or(120_000)
            .min(600_000);
        // 红线（§22.3）：环境变量 allowlist + explicit diff——不继承 host 环境。
        let mut env_pairs: Vec<(String, String)> = Vec::new();
        if let Some(env_diff) = params.get("env_diff").and_then(Value::as_object) {
            for (key, value) in env_diff {
                if key.is_empty() || key.len() > 256 {
                    continue;
                }
                if let Some(value) = value.as_str() {
                    env_pairs.push((key.clone(), value.to_string()));
                }
            }
        }
        env_pairs.sort();

        let appcontainer =
            params.get("appcontainer").and_then(Value::as_bool).unwrap_or(false);
        let network_policy = params
            .get("network_policy")
            .and_then(Value::as_str)
            .unwrap_or("none");
        if appcontainer && network_policy != "none" {
            // N3 失败关闭：capability 授予未实现，非 none 一律拒绝。
            return fail(
                "unsupported_network_policy",
                "AppContainer 仅支持 network_policy=none（能力授予尚未开放）",
            );
        }
        if mode == "pty" && appcontainer {
            // 失败关闭：AC + ConPTY 组合未经验证，不降级不猜测（§11.5）。
            return fail(
                "unsupported_mode",
                "appcontainer 不支持 pty 模式",
            );
        }

        #[cfg(windows)]
        sandbox::ac_trace_public(&format!(
            "handle_start appcontainer={appcontainer} integrity={:?}",
            params.get("integrity_level").and_then(Value::as_str),
        ));
        // 运行时根：调用方声明（解释器/依赖目录）+ exe 目录自动推导。
        let mut roots: Vec<String> = Vec::new();
        if let Some(paths) = params.get("ac_grant_paths").and_then(Value::as_array) {
            for path in paths.iter().take(16) {
                if let Some(path) = path.as_str() {
                    if !path.is_empty() && path.len() <= 2048 {
                        roots.push(path.to_string());
                    }
                }
            }
        }
        let exe_dir = std::path::Path::new(&program[0])
            .parent()
            .map(|p| p.to_string_lossy().to_string());
        if let Some(dir) = exe_dir {
            roots.push(dir);
        }
        roots.sort();
        roots.dedup();

        #[cfg(windows)]
        sandbox::ac_trace_public(&format!("ac roots={roots:?}"));
        if appcontainer {
            // host 级稳定 profile + 常驻 RX 基线；失败 → 失败关闭。
            if let Err(err) = sandbox::ensure_ac_runtime("pa.exec.host.default", &roots)
            {
                return fail(
                    "sandbox_policy_unavailable",
                    &format!("appcontainer 准备失败：{err}"),
                );
            }
        }
        #[cfg(windows)]
        sandbox::ac_trace_public("spawn begin");
        // 顺序修正（N1b 实证）：本机内核/EDR 对"进程持有 KILL_ON_JOB_CLOSE
        // Job 句柄期间调用 CreateProcess"返回 ACCESS_DENIED——Job 改为
        // 进程创建成功后立即创建并分配。std 路径存在微秒级窗口（子进程尚未
        // 入 Job 即可能派生孙进程）；受限/AC 路径以挂起态创建后分配再恢复，
        // 零窗口。任一沙箱原语失败 → 失败关闭，绝不降级（§11.5）。
        let spawn_result = if mode == "pty" {
            // 失败关闭：ConPTY 附着环境不可用（实证探针）→ 结构化拒绝，
            // 绝不交付无法回显的伪会话（与 §11.5 沙箱失败关闭同语义）。
            if !sandbox::pty_environment_ready() {
                return fail(
                    "pty_environment_unavailable",
                    "ConPTY 附着在当前环境不可用（探针未通过），pty 模式失败关闭",
                );
            }
            // 受控 PTY（§11.3）：ConPTY 接管 stdio；stderr 合流属终端语义。
            let pty_env_block = sandbox::build_environment_block(&env_pairs);
            sandbox::spawn_pty(&program, cwd, &pty_env_block,
                integrity == sandbox::IntegrityLevel::Low, want_stdin)
                .map(|pty_spawned| {
                    let slot = ChildSlot::Restricted(sandbox::RestrictedChild::from_parts(
                        pty_spawned.process_handle,
                        pty_spawned.main_thread_handle,
                    ));
                    Spawned {
                        slot: Some(slot),
                        stdout: Some(Box::new(pty_spawned.output_read)),
                        stderr: None,
                        stdin: if want_stdin {
                            Some(StdinSink::Raw(pty_spawned.input_write))
                        } else {
                            None
                        },
                        pty_console: Some(pty_spawned.console),
                    }
                })
        } else if appcontainer {
            match sandbox::ensure_ac_runtime("pa.exec.host.default", &roots) {
                Ok(runtime) => {
                    // AC 语义下忽略请求 cwd（不授权工作区），使用 profile AC 目录。
                    let ac_cwd = runtime.working_dir().to_string_lossy().to_string();
                    spawn_appcontainer(
                        &program,
                        &ac_cwd,
                        &env_pairs,
                        &runtime.guard,
                        want_stdin,
                    )
                }
                Err(err) => Err(std::io::Error::other(format!(
                    "sandbox_policy_unavailable: {err}"
                ))),
            }
        } else if integrity == sandbox::IntegrityLevel::Low {
            spawn_restricted(&program, cwd, &env_pairs, want_stdin)
        } else {
            spawn_std(&program, cwd, &env_pairs, want_stdin)
        };

        let mut spawned = match spawn_result {
            Ok(spawned) => spawned,
            Err(err) if appcontainer && err.kind() == std::io::ErrorKind::PermissionDenied => {
                // 仅 AC 路径：创建失败 → 沙箱策略不可用，失败关闭（§11.5），零降级。
                return fail("sandbox_policy_unavailable", &err.to_string());
            }
            Err(err) => {
                #[cfg(windows)]
                sandbox::ac_trace_public(&format!(
                    "spawn FAILED err={err} program={}", program[0]
                ));
                return fail("spawn_failed", &err.to_string());
            }
        };

        // 子进程经继承自动加入宿主 Job（启动期自分配），无需逐次 Assign；
        // 此处仅恢复挂起子进程（Std 路径 no-op）。级联终止由 cancel/超时
        // 路径的 taskkill /T 承担（terminate_tree 会连宿主一起终止，禁用）。
        if let Some(slot) = spawned.slot.as_mut() {
            slot.resume();
        }

        let state = ExecutionState {
            child: Arc::new(Mutex::new(spawned.slot.take().unwrap())),
            sequence: Arc::new(AtomicU64::new(0)),
            cancel_requested: Arc::new(AtomicBool::new(false)),
            stdin: Arc::new(Mutex::new(spawned.stdin.take())),
            session_nonce: session_nonce.clone(),
            output_tail: Arc::new(Mutex::new(OutputTail::new())),
            pty: Arc::new(Mutex::new(spawned.pty_console.take())),
        };
        let sequence = Arc::clone(&state.sequence);
        let cancel_requested = Arc::clone(&state.cancel_requested);
        let child_slot = Arc::clone(&state.child);
        let output_tail = Arc::clone(&state.output_tail);
        host.executions
            .lock()
            .unwrap()
            .insert(execution_id.clone(), state);

        host.notify(json!({
            "notification": "execution/started",
            "execution_id": execution_id,
            "sequence": sequence.fetch_add(1, Ordering::SeqCst),
        }));
        host.respond(request_id, json!({ "accepted": true }));

        for (stream, reader) in spawned.drain_streams() {
            spawn_stream_reader(
                execution_id.clone(),
                stream,
                reader,
                Arc::clone(&sequence),
                Arc::clone(&output_tail),
            );
        }
        spawn_waiter(
            execution_id,
            child_slot,
            cancel_requested,
            sequence,
            Instant::now() + Duration::from_millis(timeout_ms),
        );
    }
}

struct Spawned {
    slot: Option<ChildSlot>,
    stdout: Option<Box<dyn Read + Send>>,
    stderr: Option<Box<dyn Read + Send>>,
    stdin: Option<StdinSink>,
    #[cfg(windows)]
    pty_console: Option<sandbox::PseudoConsole>,
}

impl Spawned {
    fn drain_streams(&mut self) -> Vec<(&'static str, Box<dyn Read + Send>)> {
        let mut streams = Vec::with_capacity(2);
        if let Some(reader) = self.stdout.take() {
            streams.push(("stdout", reader));
        }
        if let Some(reader) = self.stderr.take() {
            streams.push(("stderr", reader));
        }
        streams
    }
}

fn spawn_std(
    program: &[String],
    cwd: &str,
    env_pairs: &[(String, String)],
    want_stdin: bool,
) -> std::io::Result<Spawned> {
    let mut command = std::process::Command::new(&program[0]);
    command.args(&program[1..]).current_dir(cwd);
    // 环境变量显式集合（allowlist），不继承 host 环境。
    command.env_clear();
    for (key, value) in env_pairs {
        command.env(key, value);
    }
    if want_stdin {
        command.stdin(Stdio::piped());
    } else {
        command.stdin(Stdio::null());
    }
    command.stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout: Option<Box<dyn Read + Send>> =
        child.stdout.take().map(|p| Box::new(p) as _);
    let stderr: Option<Box<dyn Read + Send>> =
        child.stderr.take().map(|p| Box::new(p) as _);
    let stdin = child.stdin.take().map(StdinSink::Std);
    Ok(Spawned {
        slot: Some(ChildSlot::Std(Box::new(child))),
        stdout,
        stderr,
        stdin,
        #[cfg(windows)]
        pty_console: None,
    })
}

#[cfg(windows)]
fn spawn_appcontainer(
    program: &[String],
    cwd: &str,
    env_pairs: &[(String, String)],
    ac: &sandbox::AppContainerGuard,
    want_stdin: bool,
) -> std::io::Result<Spawned> {
    let env_block = sandbox::build_environment_block(env_pairs);
    // 挂起态创建：调用方建 Job 分配后再 resume（零窗口受控）。
    let spawned = sandbox::spawn_appcontainer(program, cwd, &env_block, ac, want_stdin)?;
    spawned.resume();
    let slot = ChildSlot::Restricted(sandbox::RestrictedChild::from_parts(
        spawned.process_handle,
        spawned.main_thread_handle,
    ));
    Ok(Spawned {
        slot: Some(slot),
        stdout: Some(Box::new(spawned.stdout_read)),
        stderr: Some(Box::new(spawned.stderr_read)),
        stdin: spawned.stdin_write.map(StdinSink::Raw),
        pty_console: None,
    })
}

#[cfg(windows)]
fn spawn_restricted(
    program: &[String],
    cwd: &str,
    env_pairs: &[(String, String)],
    want_stdin: bool,
) -> std::io::Result<Spawned> {
    let env_block = sandbox::build_environment_block(env_pairs);
    // 挂起态创建（sandbox 内部 CREATE_SUSPENDED）：调用方建 Job 分配后
    // 再 resume——树从首个进程起即受控，零窗口。
    let spawned = sandbox::spawn_restricted_low_il(program, cwd, &env_block, want_stdin)?;
    let slot = ChildSlot::Restricted(sandbox::RestrictedChild::from_parts(
        spawned.process_handle,
        spawned.main_thread_handle,
    ));
    Ok(Spawned {
        slot: Some(slot),
        stdout: Some(Box::new(spawned.stdout_read)),
        stderr: Some(Box::new(spawned.stderr_read)),
        stdin: spawned.stdin_write.map(StdinSink::Raw),
        pty_console: None,
    })
}

fn spawn_stream_reader(
    execution_id: String,
    stream: &'static str,
    mut pipe: Box<dyn Read + Send>,
    sequence: Arc<AtomicU64>,
    output_tail: Arc<Mutex<OutputTail>>,
) {
    std::thread::spawn(move || {
        let mut pending: Vec<u8> = Vec::with_capacity(DELTA_LIMIT);
        let mut chunk = [0u8; READ_CHUNK_SIZE];
        loop {
            match pipe.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => {
                    pending.extend_from_slice(&chunk[..n]);
                    // 续读窗口每次读取即入环（不等分帧边界，§11.4 实时性）。
                    output_tail.lock().unwrap().push(&chunk[..n]);
                    while pending.len() >= DELTA_LIMIT {
                        let rest = pending.split_off(DELTA_LIMIT);
                        emit_delta(&execution_id, stream, &pending, &sequence);
                        pending = rest;
                    }
                }
                Err(_) => break,
            }
        }
        if !pending.is_empty() {
            emit_delta(&execution_id, stream, &pending, &sequence);
        }
    });
}

fn emit_delta(execution_id: &str, stream: &str, data: &[u8], sequence: &AtomicU64) {
    let text = String::from_utf8_lossy(data);
    host().notify(json!({
        "notification": format!("execution/{stream}/delta"),
        "execution_id": execution_id,
        "sequence": sequence.fetch_add(1, Ordering::SeqCst),
        "stream": stream,
        "data": text,
    }));
}

/// 终态监视：轮询 poll_exit；用户取消/超时 → Job 级联 kill 整棵树，
/// cancelled/exited/failed 事件按协议顺序发出。
fn spawn_waiter(
    execution_id: String,
    child: SharedChild,
    cancel_requested: Arc<AtomicBool>,
    sequence: Arc<AtomicU64>,
    deadline: Instant,
) {
    std::thread::spawn(move || {
        let mut timed_out = false;
        loop {
            let outcome = {
                let mut guard = child.lock().unwrap();
                match guard.poll_exit() {
                    Ok(Some(code)) => Some(Ok(code)),
                    Ok(None) => {
                        if !timed_out && Instant::now() >= deadline {
                            timed_out = true;
                            cancel_requested.store(true, Ordering::SeqCst);
                            guard.kill();
                        }
                        None
                    }
                    Err(_) => Some(Err(())),
                }
            };
            match outcome {
                Some(Ok(exit_code)) => {
                    let was_cancelled = cancel_requested.load(Ordering::SeqCst);
                    if was_cancelled {
                        host().notify(json!({
                            "notification": "execution/cancelled",
                            "execution_id": execution_id,
                            "sequence": sequence.fetch_add(1, Ordering::SeqCst),
                            "processes_remaining": 0,
                        }));
                    }
                    host().notify(json!({
                        "notification": "execution/exited",
                        "execution_id": execution_id,
                        "sequence": sequence.fetch_add(1, Ordering::SeqCst),
                        "exit_code": exit_code,
                        "cancelled_by_timeout": timed_out,
                        "processes_remaining": 0,
                    }));
                    // 移除 → ExecutionState.job Drop → KILL_ON_JOB_CLOSE 兜底。
                    host().executions.lock().unwrap().remove(&execution_id);
                    break;
                }
                Some(Err(())) => {
                    host().notify(json!({
                        "notification": "execution/failed",
                        "execution_id": execution_id,
                        "sequence": sequence.fetch_add(1, Ordering::SeqCst),
                        "error": {"code": "wait_failed", "message": "wait error",
                            "retryable": false, "details": null, "trace_id": null},
                    }));
                    host().executions.lock().unwrap().remove(&execution_id);
                    break;
                }
                None => {}
            }
            std::thread::sleep(Duration::from_millis(POLL_INTERVAL_MS));
        }
    });
}

/// stdin 写入（§11.4）：绑定 execution id + session nonce + 当前状态；
/// nonce 不匹配/写入端已关闭 → 结构化错误，不静默丢弃。
fn handle_stdin_write(request_id: u64, message: &Value) {
    let host = host();
    let fail = |code: &str, msg: &str| {
        host.respond_error(request_id, code, msg);
    };
    let Some(params) = message.get("params") else {
        return fail("bad_params", "缺少 params");
    };
    let Some(execution_id) = params.get("execution_id").and_then(Value::as_str) else {
        return fail("bad_params", "缺少 execution_id");
    };
    let Some(nonce) = params.get("session_nonce").and_then(Value::as_str) else {
        return fail("bad_params", "缺少 session_nonce");
    };
    let data = params.get("data").and_then(Value::as_str).unwrap_or("");
    let close = params.get("close").and_then(Value::as_bool).unwrap_or(false);
    if data.len() > STDIN_WRITE_MAX {
        return fail("bad_params", "stdin 单次写入超限");
    }
    let found = host.executions.lock().unwrap().get(execution_id).map(|state| {
        (Arc::clone(&state.stdin), state.session_nonce.clone())
    });
    let Some((stdin, expected)) = found else {
        return fail("unknown_execution", "执行不存在或已结束");
    };
    match expected.as_deref() {
        Some(expected) if expected == nonce => {}
        _ => return fail("bad_nonce", "session_nonce 不匹配"),
    }
    let mut guard = stdin.lock().unwrap();
    let Some(sink) = guard.as_mut() else {
        return fail("stdin_closed", "stdin 已关闭或未开启管道");
    };
    if let Err(err) = sink.write_all(data.as_bytes()) {
        *guard = None;
        return fail("stdin_write_failed", &err.to_string());
    }
    if close {
        *guard = None; // drop → 关闭管道（EOF）
    }
    host.respond(request_id, json!({ "written": data.len() }));
}

/// 输出续读（§11.4）：字节偏移语义的有界滑动窗口；执行移除后不再可读，
/// 持久化输出由 Python Core 以 artifact 承担。
fn handle_output_read(request_id: u64, message: &Value) {
    let host = host();
    let fail = |code: &str, msg: &str| {
        host.respond_error(request_id, code, msg);
    };
    let Some(params) = message.get("params") else {
        return fail("bad_params", "缺少 params");
    };
    let Some(execution_id) = params.get("execution_id").and_then(Value::as_str) else {
        return fail("bad_params", "缺少 execution_id");
    };
    let from_offset = params
        .get("from_offset")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    let limit = params
        .get("limit")
        .and_then(Value::as_u64)
        .unwrap_or(64 * 1024)
        .min(256 * 1024) as usize;
    let tail = host
        .executions
        .lock()
        .unwrap()
        .get(execution_id)
        .map(|state| Arc::clone(&state.output_tail));
    let Some(tail) = tail else {
        return fail("unknown_execution", "执行不存在或已结束");
    };
    let ring = tail.lock().unwrap();
    if from_offset > ring.total {
        return fail("bad_offset", "from_offset 超出累计输出");
    }
    let window_start = ring.total - ring.buffer.len() as u64;
    let start = from_offset.max(window_start);
    let index = (start - window_start) as usize;
    let take = limit.min(ring.buffer.len() - index);
    let data = String::from_utf8_lossy(&ring.buffer[index..index + take]).to_string();
    host.respond(request_id, json!({
        "data": data,
        "next_offset": start + take as u64,
        "total": ring.total,
        "window_start": window_start,
    }));
}

fn handle_cancel(request_id: u64, message: &Value) {
    let host = host();
    let execution_id = message
        .get("params")
        .and_then(|p| p.get("execution_id"))
        .and_then(Value::as_str)
        .map(str::to_string);
    let found = execution_id.and_then(|id| {
        host.executions.lock().unwrap().get(&id).map(|state| {
            state.cancel_requested.store(true, Ordering::SeqCst);
            // 级联终止：Job 树 kill 覆盖全部子孙；kill() 兜底主进程。
            // 自分配模式下 host 亦为 Job 成员：禁用 terminate_tree（会连宿主
            // 一起终止），改用 taskkill /T /F 仅级联目标子树。
            #[cfg(windows)]
            {
                #[cfg(windows)]
                sandbox::ac_trace_public("cancel: taskkill begin");
                if let Ok(guard) = state.child.lock() {
                    let pid = guard.pid();
                    drop(guard);
                    sandbox::ac_trace_public(&format!("cancel: taskkill pid={pid}"));
                    let _ = sandbox::taskkill_tree(pid);
                    sandbox::ac_trace_public("cancel: taskkill done");
                }
            }
            if let Ok(mut guard) = state.child.lock() {
                guard.kill();
            }
        })
    });
    match found {
        Some(()) => host.respond(request_id, json!({ "cancelling": true })),
        None => host.respond_error(request_id, "unknown_execution",
            "执行不存在或已结束"),
    }
}
