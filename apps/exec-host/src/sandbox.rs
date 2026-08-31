//! Windows 沙箱强制原语（专项计划 §11.5 / ADR-004 / CT-6）。
//!
//! 三层能力：
//! 1. **Job Object 级联终止**：每个 execution 一个 Job（KILL_ON_JOB_CLOSE），
//!    子进程整棵树继承；cancel/超时/host 退出 → `TerminateJobObject`/
//!    句柄关闭级联终止全部子孙（§19.2 p95 ≤ 2s 的机制基础）。
//! 2. **MIC 完整性级别降级**：复制当前进程 primary token 并
//!    `SetTokenIntegrityLevel(Low)`，经 `CreateProcessAsUserW` 启动——
//!    Low IL 子进程对默认 Medium IL 标签的用户目录**写入默认拒绝**。
//! 3. **AppContainer 网络强制**：零能力 profile + 属性表启动——
//!    `network_policy=none` 时内核 ACL 默认拒绝全部 outbound（含 loopback）。
//!    本机实证限制与 N1b/N1c 结论见
//!    `docs/releases/v1.0.0/adr/evidence/s4-network-enforcement-plan.md` §3.5。
//!
//! 实现注记：全部 Win32 调用经 `GetProcAddress` 动态解析，规避 SDK
//! `.lib` 导出差异（本机实测 userenv 缺少 DeriveAppContainerSidFromAppName
//! 导出；advapi32/kernel32 同口径统一处理）。

#![cfg(windows)]

use std::io;
use std::os::windows::io::RawHandle;

use windows_sys::Win32::Foundation::{CloseHandle, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::JobObjects::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
use windows_sys::Win32::System::Threading::{
    CreateProcessAsUserW, CreateProcessW, GetCurrentProcess, STARTF_USESTDHANDLES,
    STARTUPINFOW, STARTUPINFOEXW, PROCESS_INFORMATION,
    PROC_THREAD_ATTRIBUTE_HANDLE_LIST, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
    CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT,
};

// ---------------------------------------------------------------------------
// 动态解析辅助
// ---------------------------------------------------------------------------

fn load_module(name: &str) -> HANDLE {
    use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleW, LoadLibraryW};
    let name16: Vec<u16> = name.encode_utf16().chain(std::iter::once(0)).collect();
    unsafe {
        let module = GetModuleHandleW(name16.as_ptr());
        if module.is_null() {
            LoadLibraryW(name16.as_ptr())
        } else {
            module
        }
    }
}

fn get_proc(module: HANDLE, symbol: &str) -> io::Result<*mut core::ffi::c_void> {
    use windows_sys::Win32::System::LibraryLoader::GetProcAddress;
    let symbol_bytes: Vec<u8> = symbol.bytes().chain(std::iter::once(0)).collect();
    unsafe {
        let proc_addr: Option<unsafe extern "system" fn() -> isize> =
            GetProcAddress(module, symbol_bytes.as_ptr());
        match proc_addr {
            Some(addr) => Ok(addr as *mut core::ffi::c_void),
            None => Err(io::Error::new(
                io::ErrorKind::Unsupported,
                format!("符号不可用：{symbol}"),
            )),
        }
    }
}

fn wide0(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

// ---------------------------------------------------------------------------
// 完整性级别
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum IntegrityLevel {
    Inherit,
    Low,
}

impl IntegrityLevel {
    pub fn parse(value: Option<&str>) -> Option<Self> {
        match value.unwrap_or("inherit") {
            "inherit" => Some(Self::Inherit),
            "low" => Some(Self::Low),
            _ => None,
        }
    }

    const LOW_SID: &'static str = "S-1-16-4096";
}

fn duplicate_primary_token() -> io::Result<HANDLE> {
    unsafe {
        let mut token: HANDLE = std::ptr::null_mut();
        // QUERY | DUPLICATE | ASSIGN_PRIMARY | IMPERSONATE | ADJUST_DEFAULT
        let access = 0x0008u32 | 0x0002 | 0x0001 | 0x0004 | 0x0080;
        let open_token: unsafe extern "system" fn(
            HANDLE,
            u32,
            *mut HANDLE,
        ) -> i32 = std::mem::transmute(get_proc(
            load_module("advapi32.dll"),
            "OpenProcessToken",
        )?);
        if open_token(GetCurrentProcess(), access, &mut token) == 0 {
            return Err(io::Error::last_os_error());
        }
        type DuplicateFn = unsafe extern "system" fn(
            HANDLE,
            u32,
            *const SECURITY_ATTRIBUTES,
            i32,
            i32,
            *mut HANDLE,
        ) -> i32;
        let duplicate: DuplicateFn =
            std::mem::transmute(get_proc(load_module("advapi32.dll"), "DuplicateTokenEx")?);
        let mut duplicated: HANDLE = std::ptr::null_mut();
        if duplicate(
            token,
            access,
            std::ptr::null(),
            2, /* SecurityImpersonation */
            1, /* TokenPrimary */
            &mut duplicated,
        ) == 0
        {
            CloseHandle(token);
            return Err(io::Error::last_os_error());
        }
        CloseHandle(token);
        Ok(duplicated)
    }
}

fn set_low_integrity(token: HANDLE) -> io::Result<()> {
    unsafe {
        let advapi = load_module("advapi32.dll");
        let convert_sid: unsafe extern "system" fn(*const u16, *mut PSID) -> i32 =
            std::mem::transmute(get_proc(advapi, "ConvertStringSidToSidW")?);
        let get_sid_len: unsafe extern "system" fn(PSID) -> u32 =
            std::mem::transmute(get_proc(advapi, "GetLengthSid")?);
        let set_info: unsafe extern "system" fn(
            HANDLE,
            i32,
            *const core::ffi::c_void,
            u32,
        ) -> i32 = std::mem::transmute(get_proc(advapi, "SetTokenInformation")?);

        let mut sid_wide: Vec<u16> =
            IntegrityLevel::LOW_SID.encode_utf16().collect();
        sid_wide.push(0);
        let mut sid: PSID = std::ptr::null_mut();
        if convert_sid(sid_wide.as_ptr(), &mut sid) == 0 {
            return Err(io::Error::last_os_error());
        }
        #[repr(C)]
        struct SidAndAttributes {
            sid: PSID,
            attributes: u32,
        }
        #[repr(C)]
        struct MandatoryLabel {
            label: SidAndAttributes,
            padding: u32,
        }
        let label = MandatoryLabel {
            label: SidAndAttributes { sid, attributes: 0x20 },
            padding: 0,
        };
        // TokenIntegrityLevel = 25
        let ok = set_info(
            token,
            25,
            &label as *const _ as *const core::ffi::c_void,
            (std::mem::size_of::<MandatoryLabel>() + get_sid_len(sid) as usize) as u32,
        );
        free_local(sid);
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}

type PSID = *mut core::ffi::c_void;

unsafe fn free_local(ptr: *mut core::ffi::c_void) {
    let Ok(free) = (|| -> io::Result<
        unsafe extern "system" fn(*mut core::ffi::c_void) -> HANDLE,
    > {
        Ok(std::mem::transmute(get_proc(
            load_module("kernel32.dll"),
            "LocalFree",
        )?))
    })() else {
        return;
    };
    free(ptr);
}

unsafe fn resume_thread(handle: HANDLE) {
    if let Ok(p) = get_proc(load_module("kernel32.dll"), "ResumeThread") {
        let f: unsafe extern "system" fn(HANDLE) -> u32 = std::mem::transmute(p);
        f(handle);
    }
}

unsafe fn terminate_process(handle: HANDLE, code: u32) {
    if let Ok(p) = get_proc(load_module("kernel32.dll"), "TerminateProcess") {
        let f: unsafe extern "system" fn(HANDLE, u32) -> i32 = std::mem::transmute(p);
        f(handle, code);
    }
}

// ---------------------------------------------------------------------------
// Job Object（进程树级联终止）
// ---------------------------------------------------------------------------

pub struct JobObject {
    handle: HANDLE,
}

unsafe impl Send for JobObject {}
unsafe impl Sync for JobObject {}

impl JobObject {
    pub fn new_kill_on_close() -> io::Result<Self> {
        unsafe {
            let create_job: unsafe extern "system" fn(
                *const SECURITY_ATTRIBUTES,
                *const u16,
            ) -> HANDLE = std::mem::transmute(get_proc(
                load_module("kernel32.dll"),
                "CreateJobObjectW",
            )?);
            let handle = create_job(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let set_info: unsafe extern "system" fn(
                HANDLE,
                i32,
                *const core::ffi::c_void,
                u32,
            ) -> i32 = std::mem::transmute(get_proc(
                load_module("kernel32.dll"),
                "SetInformationJobObject",
            )?);
            let mut limits: windows_sys::Win32::System::JobObjects::JOBOBJECT_EXTENDED_LIMIT_INFORMATION =
                std::mem::zeroed();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            // JobObjectExtendedLimitInformation = 9
            if set_info(handle, 9, &limits as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<windows_sys::Win32::System::JobObjects::JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32) == 0
            {
                CloseHandle(handle);
                return Err(io::Error::last_os_error());
            }
            Ok(Self { handle })
        }
    }

    /// 对宿主进程自身分配——启动期一次，子进程经继承自动入 Job。
    pub fn assign_self(&self) -> io::Result<()> {
        unsafe {
            let assign: unsafe extern "system" fn(HANDLE, HANDLE) -> i32 =
                std::mem::transmute(get_proc(
                    load_module("kernel32.dll"),
                    "AssignProcessToJobObject",
                )?);
            let get_current: unsafe extern "system" fn() -> HANDLE =
                std::mem::transmute(get_proc(
                    load_module("kernel32.dll"),
                    "GetCurrentProcess",
                )?);
            if assign(self.handle, get_current()) == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(())
    }

    #[allow(dead_code)]
    pub fn assign(&self, child_handle: RawHandle) -> io::Result<()> {
        unsafe {
            let assign: unsafe extern "system" fn(HANDLE, HANDLE) -> i32 =
                std::mem::transmute(get_proc(
                    load_module("kernel32.dll"),
                    "AssignProcessToJobObject",
                )?);
            if assign(self.handle, child_handle) == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(())
    }

    #[allow(dead_code)]
    pub fn terminate_tree(&self, exit_code: u32) {
        unsafe {
            let Ok(terminate) = (|| -> io::Result<unsafe extern "system" fn(HANDLE, u32) -> i32> {
                Ok(std::mem::transmute(get_proc(
                    load_module("kernel32.dll"),
                    "TerminateJobObject",
                )?))
            })() else {
                return;
            };
            terminate(self.handle, exit_code);
        }
    }
}

impl Drop for JobObject {
    fn drop(&mut self) {
        // 自分配模式：TerminateJobObject 会连宿主一起杀——只关闭句柄；
        // KILL_ON_JOB_CLOSE 在 host 进程退出时由内核兜底级联。
        unsafe {
            CloseHandle(self.handle);
        }
    }
}

// Host 级 Job：启动时对自身 Assign 一次，之后所有子进程经继承自动
// 入 Job——消除对子进程的逐次 Assign（N1b/N1c 实证：本机沙箱链拒绝
// 嵌套分配且会终止被分配子进程）。自分配被拒则由宿主在握手前失败关闭。
static HOST_JOB: std::sync::OnceLock<Option<JobObject>> = std::sync::OnceLock::new();

pub fn host_job() -> &'static Option<JobObject> {
    HOST_JOB.get_or_init(|| {
        match JobObject::new_kill_on_close() {
            Ok(job) => {
                if job.assign_self().is_ok() {
                    Some(job)
                } else {
                    None
                }
            }
            Err(_) => None,
        }
    })
}


// ---------------------------------------------------------------------------
// 共享管道读取器与子进程控制面
// ---------------------------------------------------------------------------

pub struct PipeReader {
    handle: HANDLE,
}

unsafe impl Send for PipeReader {}

impl io::Read for PipeReader {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        unsafe {
            let read_file: unsafe extern "system" fn(
                HANDLE,
                *mut u8,
                u32,
                *mut u32,
                *mut core::ffi::c_void,
            ) -> i32 = std::mem::transmute(get_proc(
                load_module("kernel32.dll"),
                "ReadFile",
            )?);
            let mut read_bytes = 0u32;
            let ok = read_file(
                self.handle,
                buf.as_mut_ptr(),
                buf.len().min(u32::MAX as usize) as u32,
                &mut read_bytes,
                std::ptr::null_mut(),
            );
            if ok == 0 {
                let err = io::Error::last_os_error();
                if err.raw_os_error() == Some(109) {
                    return Ok(0); // 断开的管道 → EOF
                }
                return Err(err);
            }
            Ok(read_bytes as usize)
        }
    }
}

impl Drop for PipeReader {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}

/// 管道写入端（子进程 stdin / PTY 输入）；drop 即关闭。
pub struct PipeWriter {
    handle: HANDLE,
}

unsafe impl Send for PipeWriter {}

impl PipeWriter {
    pub fn write_all(&mut self, data: &[u8]) -> io::Result<()> {
        if data.is_empty() {
            return Ok(());
        }
        unsafe {
            let write_file: unsafe extern "system" fn(
                HANDLE,
                *const u8,
                u32,
                *mut u32,
                *mut core::ffi::c_void,
            ) -> i32 = std::mem::transmute(get_proc(
                load_module("kernel32.dll"),
                "WriteFile",
            )?);
            let mut written = 0u32;
            if write_file(
                self.handle,
                data.as_ptr(),
                data.len().min(u32::MAX as usize) as u32,
                &mut written,
                std::ptr::null_mut(),
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        }
    }
}

impl Drop for PipeWriter {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}

/// 受限/AppContainer 子进程最小控制面。
pub struct RestrictedChild {
    pub process_handle: HANDLE,
    pub main_thread_handle: HANDLE,
    exited: bool,
}

unsafe impl Send for RestrictedChild {}
unsafe impl Sync for RestrictedChild {}

impl RestrictedChild {
    #[allow(dead_code)]
    pub fn from_parts(process_handle: HANDLE, main_thread_handle: HANDLE) -> Self {
        Self { process_handle, main_thread_handle, exited: false }
    }

    #[allow(dead_code)]
    pub fn resume(&self) {
        unsafe {
            resume_thread(self.main_thread_handle);
        }
    }

    /// Some(exit_code) 已退出（i32::MIN 表示 wait 失败）；None 运行中。
    pub fn poll_exit(&mut self) -> io::Result<Option<i32>> {
        unsafe {
            let get_code: unsafe extern "system" fn(HANDLE, *mut u32) -> i32 =
                std::mem::transmute(get_proc(
                    load_module("kernel32.dll"),
                    "GetExitCodeProcess",
                )?);
            let mut code = 0u32;
            if get_code(self.process_handle, &mut code) == 0 {
                return Err(io::Error::last_os_error());
            }
            const STILL_ACTIVE: u32 = 259;
            if code == STILL_ACTIVE {
                return Ok(None);
            }
            self.exited = true;
            CloseHandle(self.main_thread_handle);
            Ok(Some(code as i32))
        }
    }

    pub fn kill(&mut self) {
        unsafe {
            terminate_process(self.process_handle, 1);
        }
    }
}

impl Drop for RestrictedChild {
    fn drop(&mut self) {
        unsafe {
            let terminate: Option<unsafe extern "system" fn(HANDLE, u32) -> i32> =
                (|| -> io::Result<unsafe extern "system" fn(HANDLE, u32) -> i32> {
                    Ok(std::mem::transmute(get_proc(
                        load_module("kernel32.dll"),
                        "TerminateProcess",
                    )?))
                })()
                .ok();
            if !self.exited {
                if let Some(terminate) = terminate {
                    terminate(self.process_handle, 1);
                }
            }
            CloseHandle(self.process_handle);
        }
    }
}

pub struct RestrictedSpawn {
    pub process_handle: HANDLE,
    pub main_thread_handle: HANDLE,
    pub stdout_read: PipeReader,
    pub stderr_read: PipeReader,
    /// stdin_mode=pipe 时保留的写入端；否则创建后立即关闭（None）。
    pub stdin_write: Option<PipeWriter>,
}

impl RestrictedSpawn {
    pub fn resume(&self) {
        unsafe {
            resume_thread(self.main_thread_handle);
        }
    }

}

// ---------------------------------------------------------------------------
// 环境/命令行构造
// ---------------------------------------------------------------------------

pub fn build_environment_block(env_diff: &[(String, String)]) -> Vec<u16> {
    let mut block: Vec<u16> = Vec::new();
    for (key, value) in env_diff {
        block.extend(format!("{key}={value}").encode_utf16());
        block.push(0);
    }
    block.push(0);
    block
}

pub fn build_command_line(argv: &[String]) -> String {
    argv.iter()
        .map(|arg| format!("\"{}\"", arg.replace('"', "\"\"")))
        .collect::<Vec<_>>()
        .join(" ")
}

// ---------------------------------------------------------------------------
// 受限启动（Low MIC）
// ---------------------------------------------------------------------------

pub fn spawn_restricted_low_il(
    argv: &[String],
    cwd: &str,
    env_block: &[u16],
    want_stdin: bool,
) -> io::Result<RestrictedSpawn> {
    unsafe {
        let token = duplicate_primary_token()?;
        if let Err(err) = set_low_integrity(token) {
            CloseHandle(token);
            return Err(err);
        }

        let sa = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        let make_pipe = || -> io::Result<(HANDLE, HANDLE)> {
            let create_pipe: unsafe extern "system" fn(
                *mut HANDLE,
                *mut HANDLE,
                *const SECURITY_ATTRIBUTES,
                u32,
            ) -> i32 = std::mem::transmute(get_proc(
                load_module("kernel32.dll"),
                "CreatePipe",
            )?);
            let mut r: HANDLE = std::ptr::null_mut();
            let mut w: HANDLE = std::ptr::null_mut();
            if create_pipe(&mut r, &mut w, &sa, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok((r, w))
        };
        let (out_r, out_w) = make_pipe()?;
        let (err_r, err_w) = make_pipe()?;
        let (in_stdin_read_end, in_w) = make_pipe()?;
        SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0);
        SetHandleInformation(err_r, HANDLE_FLAG_INHERIT, 0);

        let mut command_line: Vec<u16> =
            build_command_line(argv).encode_utf16().collect();
        command_line.push(0);
        let mut cwd_utf16: Vec<u16> = cwd.encode_utf16().collect();
        cwd_utf16.push(0);

        let mut startup: STARTUPINFOW = std::mem::zeroed();
        startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = in_stdin_read_end;
        startup.hStdOutput = out_w;
        startup.hStdError = err_w;

        let mut proc_info: PROCESS_INFORMATION = std::mem::zeroed();
        let ok = CreateProcessAsUserW(
            token,
            std::ptr::null(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
            CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,
            env_block.as_ptr() as *const core::ffi::c_void,
            cwd_utf16.as_ptr(),
            &startup,
            &mut proc_info,
        );
        CloseHandle(out_w);
        CloseHandle(err_w);
        let stdin_write = if want_stdin {
            Some(PipeWriter { handle: in_w })
        } else {
            CloseHandle(in_w);
            None
        };
        CloseHandle(in_stdin_read_end);
        if ok == 0 {
            let err = io::Error::last_os_error();
            CloseHandle(token);
            CloseHandle(out_r);
            CloseHandle(err_r);
            return Err(err);
        }
        CloseHandle(token);
        Ok(RestrictedSpawn {
            process_handle: proc_info.hProcess,
            main_thread_handle: proc_info.hThread,
            stdout_read: PipeReader { handle: out_r },
            stderr_read: PipeReader { handle: err_r },
            stdin_write,
        })
    }
}

// ---------------------------------------------------------------------------
// AppContainer（零能力 → 内核级网络默认拒绝）
// ---------------------------------------------------------------------------

fn ac_trace(msg: &str) {
    if std::env::var_os("PA_EXEC_HOST_DEBUG").is_some() {
        eprintln!("[ac] {msg}");
    }
}

pub struct AppContainerGuard {
    pub sid: PSID,
    profile_name: Vec<u16>,
}

unsafe impl Send for AppContainerGuard {}

impl AppContainerGuard {
    pub fn profile_name_utf8_lossy(&self) -> String {
        let bytes: Vec<u8> = self
            .profile_name
            .iter()
            .filter(|&&c| c != 0)
            .map(|&c| c as u8)
            .collect();
        String::from_utf8_lossy(&bytes).into_owned()
    }

    /// 创建零能力 AppContainer；已存在则删除重建（本机 userenv 缺少
    /// DeriveAppContainerSidFromAppName 导出，实测无法派生既有 SID）。
    pub fn create_zero_capability(profile_name: &str) -> io::Result<Self> {
        unsafe {
            ac_trace("create_profile begin");
            let mut name16 = wide0(profile_name);
            let create_profile: unsafe extern "system" fn(
                *const u16,
                *mut u16,
                *mut u16,
                *const core::ffi::c_void,
                u32,
                *mut PSID,
            ) -> i32 = std::mem::transmute(get_proc(
                load_module("userenv.dll"),
                "CreateAppContainerProfile",
            )?);
            let delete_profile: unsafe extern "system" fn(*const u16) -> i32 =
                std::mem::transmute(get_proc(
                    load_module("userenv.dll"),
                    "DeleteAppContainerProfile",
                )?);
            let mut sid: PSID = std::ptr::null_mut();
            let hr = create_profile(
                name16.as_mut_ptr(),
                name16.as_mut_ptr(),
                name16.as_mut_ptr(),
                std::ptr::null(), // 零 capability
                0,
                &mut sid,
            );
            if hr == -2147024713 {
                // ERROR_ALREADY_EXISTS：删除陈旧 profile 后重建（启动期无
                // 附着进程）。SID 随新 profile 变化，授权在之后统一执行。
                ac_trace("create_profile exists → delete & recreate");
                if delete_profile(name16.as_mut_ptr()) == 0 {
                    return Err(io::Error::last_os_error());
                }
                let hr_retry = create_profile(
                    name16.as_mut_ptr(),
                    name16.as_mut_ptr(),
                    name16.as_mut_ptr(),
                    std::ptr::null(),
                    0,
                    &mut sid,
                );
                if hr_retry < 0 {
                    ac_trace(&format!("recreate hr={hr_retry:#x}"));
                    return Err(io::Error::from_raw_os_error(hr_retry));
                }
            } else if hr < 0 {
                ac_trace(&format!("create_profile hr={hr:#x}"));
                return Err(io::Error::from_raw_os_error(hr));
            }
            ac_trace("create_profile ok");
            Ok(Self { sid, profile_name: name16 })
        }
    }
}

impl Drop for AppContainerGuard {
    fn drop(&mut self) {
        unsafe {
            if let Ok(delete_profile) = (|| -> io::Result<
                unsafe extern "system" fn(*const u16) -> i32,
            > {
                Ok(std::mem::transmute(get_proc(
                    load_module("userenv.dll"),
                    "DeleteAppContainerProfile",
                )?))
            })() {
                delete_profile(self.profile_name.as_ptr());
            }
            free_local(self.sid);
        }
    }
}

/// AC 运行时：profile + 解释器根常驻 RX 基线（host 级一次性复用；
/// 不随 execution 撤销——DACL 重写触发整树继承重算，巨目录卡死）。
pub struct AcRuntime {
    pub guard: AppContainerGuard,
    #[allow(dead_code)]
    granted_roots: Vec<String>,
}

unsafe impl Send for AcRuntime {}
unsafe impl Sync for AcRuntime {}

static AC_RUNTIME: std::sync::OnceLock<Result<AcRuntime, String>> =
    std::sync::OnceLock::new();

/// 获取（或首次创建）host 级 AC 运行时；失败被缓存并持续失败关闭。
pub fn ensure_ac_runtime(
    profile_name: &str,
    grant_roots: &[String],
) -> Result<&'static AcRuntime, String> {
    let runtime = AC_RUNTIME.get_or_init(|| {
        let guard = AppContainerGuard::create_zero_capability(profile_name)
            .map_err(|err| format!("profile: {err}"))?;
        let granted = guard
            .grant_runtime_paths(grant_roots)
            .map_err(|err| format!("grant: {err}"))?;
        Ok(AcRuntime { guard, granted_roots: granted })
    });
    runtime.as_ref().map_err(|err| err.clone())
}

impl AcRuntime {
    /// AC 进程专用 cwd：%LOCALAPPDATA%\Packages\<profile>\AC。
    /// （系统默认对该 SID 开放；绝不触碰工作区 DACL。）
    pub fn working_dir(&self) -> std::path::PathBuf {
        let base = std::env::var_os("LOCALAPPDATA")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(|| {
                std::env::var_os("USERPROFILE")
                    .map(|u| {
                        std::path::PathBuf::from(u).join("AppData").join("Local")
                    })
                    .unwrap_or_else(|| std::path::PathBuf::from("."))
            });
        let dir = base
            .join("Packages")
            .join(self.guard.profile_name_utf8_lossy())
            .join("AC");
        let _ = std::fs::create_dir_all(&dir);
        dir
    }
}

impl AppContainerGuard {
    /// N1b：为该 AC SID 授予一组运行时目录的读/执行权限（继承到子树）。
    pub fn grant_runtime_paths(&self, paths: &[String]) -> io::Result<Vec<String>> {
        let advapi = load_module("advapi32.dll");
        unsafe {
            let get_dacl: unsafe extern "system" fn(
                *const u16,
                i32,
                u32,
                *mut PSID,
                *mut PSID,
                *mut *mut windows_sys::Win32::Security::ACL,
                *mut *mut windows_sys::Win32::Security::ACL,
                *mut *mut core::ffi::c_void,
            ) -> u32 = std::mem::transmute(get_proc(
                advapi,
                "GetNamedSecurityInfoW",
            )?);
            let set_dacl: unsafe extern "system" fn(
                *mut u16,
                i32,
                u32,
                PSID,
                PSID,
                *const windows_sys::Win32::Security::ACL,
                *const windows_sys::Win32::Security::ACL,
            ) -> u32 = std::mem::transmute(get_proc(
                advapi,
                "SetNamedSecurityInfoW",
            )?);
            let set_entries: unsafe extern "system" fn(
                u32,
                *const ExplicitAccessW,
                *const windows_sys::Win32::Security::ACL,
                *mut *mut windows_sys::Win32::Security::ACL,
            ) -> u32 = std::mem::transmute(get_proc(
                advapi,
                "SetEntriesInAclW",
            )?);

            #[repr(C)]
            struct TrusteeW {
                multiple_trustee: *mut core::ffi::c_void,
                multiple_trustee_operation: i32,
                trustee_form: i32,
                trustee_type: i32,
                ptstr_name: *mut u16,
            }
            #[repr(C)]
            struct ExplicitAccessW {
                grf_access_permissions: u32,
                grf_access_mode: i32,
                grf_inheritance: u32,
                trustee: TrusteeW,
            }

            let mut granted = Vec::new();
            for path in paths {
                ac_trace(&format!("grant begin {path}"));
                let mut path16 = wide0(path);
                let mut old_dacl: *mut windows_sys::Win32::Security::ACL =
                    std::ptr::null_mut();
                let mut sd: *mut core::ffi::c_void = std::ptr::null_mut();
                // SE_FILE_OBJECT=1, DACL_SECURITY_INFORMATION=4
                if get_dacl(
                    path16.as_ptr(),
                    1,
                    4,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    &mut old_dacl,
                    std::ptr::null_mut(),
                    &mut sd,
                ) != 0
                {
                    let err = io::Error::last_os_error();
                    ac_trace(&format!("grant FAIL {path}: {err}"));
                    return Err(io::Error::new(
                        err.kind(),
                        format!("ac:grant {path}: {err}"),
                    ));
                }
                let ea = ExplicitAccessW {
                    grf_access_permissions: 0x8000_0000 | 0x2000_0000,
                    grf_access_mode: 1,  // GRANT_ACCESS
                    grf_inheritance: 3,  // OBJECT | CONTAINER
                    trustee: TrusteeW {
                        multiple_trustee: std::ptr::null_mut(),
                        multiple_trustee_operation: 0,
                        trustee_form: 0, // TRUSTEE_IS_SID
                        trustee_type: 1, // TRUSTEE_IS_UNKNOWN
                        ptstr_name: self.sid as *mut u16,
                    },
                };
                let mut new_dacl: *mut windows_sys::Win32::Security::ACL =
                    std::ptr::null_mut();
                if set_entries(1, &ea, old_dacl, &mut new_dacl) != 0 {
                    let err = io::Error::last_os_error();
                    free_local(sd);
                    ac_trace(&format!("grant FAIL {path}: {err}"));
                    return Err(io::Error::new(
                        err.kind(),
                        format!("ac:grant {path}: {err}"),
                    ));
                }
                let ok = set_dacl(
                    path16.as_mut_ptr(),
                    1,
                    4,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    new_dacl,
                    std::ptr::null(),
                );
                free_local(new_dacl as *mut core::ffi::c_void);
                free_local(sd);
                if ok != 0 {
                    let err = io::Error::last_os_error();
                    ac_trace(&format!("grant FAIL {path}: {err}"));
                    return Err(io::Error::new(
                        err.kind(),
                        format!("ac:grant {path}: {err}"),
                    ));
                }
                granted.push(path.clone());
                ac_trace(&format!("grant ok {path}"));
            }
            Ok(granted)
        }
    }
}

// ---------------------------------------------------------------------------
// ConPTY 环境就绪探针（失败关闭：附着不可用时不开放 pty 模式）
// ---------------------------------------------------------------------------

static PTY_READY: std::sync::OnceLock<bool> = std::sync::OnceLock::new();

/// 首次调用时以 cmd 回显探针实证 ConPTY 附着：
/// 附着有效 → 管道内出现回显标记；环境受限（本机实证：属性表附着不生效，
/// 与 AC 加载链限制同源）→ false，pty 请求一律结构化拒绝。
pub fn pty_environment_ready() -> bool {
    *PTY_READY.get_or_init(probe_pty_attachment)
}

fn probe_pty_attachment() -> bool {
    let argv = vec![
        "C:\\Windows\\System32\\cmd.exe".to_string(),
        "/d".to_string(),
        "/c".to_string(),
        "echo PTYPROBE-OK".to_string(),
    ];
    let cwd = std::env::var_os("SystemRoot")
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());
    let env_block = build_environment_block(&[]);
    let spawned = match spawn_pty(&argv, &cwd, &env_block, false, false) {
        Ok(spawned) => spawned,
        Err(_) => return false,
    };
    let mut child = RestrictedChild::from_parts(
        spawned.process_handle,
        spawned.main_thread_handle,
    );
    let console = spawned.console; // 保持会话存活至探针结束
    drop(spawned.input_write); // 探针不写入，立即关闭输入端
    let mut reader = spawned.output_read;
    let (tx, rx) = std::sync::mpsc::channel::<bool>();
    std::thread::spawn(move || {
        let mut buf = [0u8; 4096];
        let mut acc: Vec<u8> = Vec::new();
        loop {
            match io::Read::read(&mut reader, &mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    acc.extend_from_slice(&buf[..n]);
                    if acc.windows(11).any(|win| win == b"PTYPROBE-OK") {
                        let _ = tx.send(true);
                        return;
                    }
                    if acc.len() > 65_536 {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = tx.send(false);
    });
    let ready = rx
        .recv_timeout(std::time::Duration::from_secs(3))
        .unwrap_or(false);
    child.kill();
    drop(console);
    ac_trace(&format!("pty:probe ready={ready}"));
    ready
}

// ---------------------------------------------------------------------------
// AppContainer 启动（属性表：SECURITY_CAPABILITIES + 继承句柄白名单）
// ---------------------------------------------------------------------------

pub fn spawn_appcontainer(
    argv: &[String],
    cwd: &str,
    env_block: &[u16],
    guard: &AppContainerGuard,
    want_stdin: bool,
) -> io::Result<RestrictedSpawn> {
    unsafe {
        let kernel32 = load_module("kernel32.dll");
        let init_attr: unsafe extern "system" fn(
            *mut core::ffi::c_void,
            u32,
            u32,
            *mut usize,
        ) -> i32 = std::mem::transmute(get_proc(kernel32, "InitializeProcThreadAttributeList")?);
        let update_attr: unsafe extern "system" fn(
            *mut core::ffi::c_void,
            u32,
            usize,
            *const core::ffi::c_void,
            usize,
            *mut core::ffi::c_void,
            *const core::ffi::c_void,
        ) -> i32 = std::mem::transmute(get_proc(kernel32, "UpdateProcThreadAttribute")?);
        let delete_attr: unsafe extern "system" fn(*mut core::ffi::c_void) =
            std::mem::transmute(get_proc(kernel32, "DeleteProcThreadAttributeList")?);

        let mut size: usize = 0;
        let _ = init_attr(std::ptr::null_mut(), 2, 0, &mut size);
        let mut attr_buf: Vec<u8> = vec![0u8; size];
        let attr_list = attr_buf.as_mut_ptr() as *mut core::ffi::c_void;
        if init_attr(attr_list, 2, 0, &mut size) == 0 {
            return Err(io::Error::last_os_error());
        }

        let sec_caps = windows_sys::Win32::Security::SECURITY_CAPABILITIES {
            AppContainerSid: guard.sid,
            Capabilities: std::ptr::null_mut(),
            CapabilityCount: 0, // 零能力 = 全网禁
            Reserved: 0,
        };
        if update_attr(
            attr_list,
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES as usize,
            &sec_caps as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<windows_sys::Win32::Security::SECURITY_CAPABILITIES>(),
            std::ptr::null_mut(),
            std::ptr::null(),
        ) == 0
        {
            let err = io::Error::new(
                io::ErrorKind::Other,
                format!("ac:update_attr_caps: {}", io::Error::last_os_error()),
            );
            delete_attr(attr_list);
            return Err(err);
        }

        let sa = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        let make_pipe = || -> io::Result<(HANDLE, HANDLE)> {
            let create_pipe: unsafe extern "system" fn(
                *mut HANDLE,
                *mut HANDLE,
                *const SECURITY_ATTRIBUTES,
                u32,
            ) -> i32 = std::mem::transmute(get_proc(kernel32, "CreatePipe")?);
            let mut r: HANDLE = std::ptr::null_mut();
            let mut w: HANDLE = std::ptr::null_mut();
            if create_pipe(&mut r, &mut w, &sa, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok((r, w))
        };
        let (out_r, out_w) = make_pipe()?;
        let (err_r, err_w) = make_pipe()?;
        let (in_stdin_read_end, in_w) = make_pipe()?;
        SetHandleInformation(out_r, HANDLE_FLAG_INHERIT, 0);
        SetHandleInformation(err_r, HANDLE_FLAG_INHERIT, 0);

        // 继承句柄白名单：AC + bInheritHandles=TRUE 组合必须显式列举
        //（ctypes 最小复现定位的必要条件之一）。
        let inherit_list: [HANDLE; 3] = [in_stdin_read_end, out_w, err_w];
        if update_attr(
            attr_list,
            0,
            PROC_THREAD_ATTRIBUTE_HANDLE_LIST as usize,
            inherit_list.as_ptr() as *const core::ffi::c_void,
            std::mem::size_of::<[HANDLE; 3]>(),
            std::ptr::null_mut(),
            std::ptr::null(),
        ) == 0
        {
            let err = io::Error::new(
                io::ErrorKind::Other,
                format!("ac:update_attr_handles: {}", io::Error::last_os_error()),
            );
            delete_attr(attr_list);
            return Err(err);
        }

        let mut command_line: Vec<u16> =
            build_command_line(argv).encode_utf16().collect();
        command_line.push(0);
        let mut cwd_utf16: Vec<u16> = cwd.encode_utf16().collect();
        cwd_utf16.push(0);

        let mut startup_ex: STARTUPINFOEXW = std::mem::zeroed();
        startup_ex.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
        startup_ex.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup_ex.StartupInfo.hStdInput = in_stdin_read_end;
        startup_ex.StartupInfo.hStdOutput = out_w;
        startup_ex.StartupInfo.hStdError = err_w;
        startup_ex.lpAttributeList = attr_list;

        let mut app_name: Vec<u16> = argv[0].encode_utf16().collect();
        app_name.push(0);
        let minimal = std::env::var_os("PA_AC_MINIMAL").is_some();
        ac_trace(&format!("create_process begin minimal={minimal}"));
        let mut proc_info: PROCESS_INFORMATION = std::mem::zeroed();
        let (app_ptr, cmd_ptr, env_ptr, cwd_ptr): (
            *const u16,
            *mut u16,
            *const core::ffi::c_void,
            *const u16,
        ) = if minimal {
            // ctypes 成功形态：全部 None/空，仅属性表生效。
            (std::ptr::null(), std::ptr::null_mut(), std::ptr::null(), std::ptr::null())
        } else {
            (
                app_name.as_ptr(),
                command_line.as_mut_ptr(),
                env_block.as_ptr() as *const core::ffi::c_void,
                cwd_utf16.as_ptr(),
            )
        };
        let mut app_name: Vec<u16> = argv[0].encode_utf16().collect();
        app_name.push(0);
        let ok = CreateProcessW(
            app_ptr,
            cmd_ptr,
            std::ptr::null(),
            std::ptr::null(),
            1,
            CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
            env_ptr,
            cwd_ptr,
            &startup_ex.StartupInfo,
            &mut proc_info,
        );
        ac_trace(&format!("create_process returned ok={ok}"));
        CloseHandle(out_w);
        CloseHandle(err_w);
        let stdin_write = if want_stdin {
            Some(PipeWriter { handle: in_w })
        } else {
            CloseHandle(in_w);
            None
        };
        CloseHandle(in_stdin_read_end);
        delete_attr(attr_list);
        if ok == 0 {
            // 失败关闭：绝不降级为无沙箱执行（§11.5 / N1b 实证记录）。
            let err = io::Error::new(
                io::ErrorKind::PermissionDenied,
                format!("ac:create_process: {}", io::Error::last_os_error()),
            );
            CloseHandle(out_r);
            CloseHandle(err_r);
            return Err(err);
        }
        Ok(RestrictedSpawn {
            process_handle: proc_info.hProcess,
            main_thread_handle: proc_info.hThread,
            stdout_read: PipeReader { handle: out_r },
            stderr_read: PipeReader { handle: err_r },
            stdin_write,
        })
    }
}

// ---------------------------------------------------------------------------
// 受控 PTY（ConPTY；§11.3 argv + 受控 PTY 首个生产形态）
// ---------------------------------------------------------------------------

#[repr(C)]
struct Coord {
    x: i16,
    y: i16,
}

type HPC = *mut core::ffi::c_void;

/// 伪控制台句柄；drop 即释放（执行移除时随状态一起回收）。
pub struct PseudoConsole {
    handle: HPC,
}

unsafe impl Send for PseudoConsole {}

impl Drop for PseudoConsole {
    fn drop(&mut self) {
        if self.handle.is_null() {
            return;
        }
        if let Ok(proc) = get_proc(load_module("kernel32.dll"), "ClosePseudoConsole") {
            let close: unsafe extern "system" fn(HPC) = unsafe { std::mem::transmute(proc) };
            unsafe { close(self.handle) };
        }
    }
}

pub struct PtySpawn {
    pub process_handle: HANDLE,
    pub main_thread_handle: HANDLE,
    /// ConPTY 合流输出（stdout/stderr 不区分，终端语义）。
    pub output_read: PipeReader,
    /// PTY 输入写入端（受 stdin_mode 控制）。
    pub input_write: PipeWriter,
    pub console: PseudoConsole,
}

/// ConPTY 启动：inherit 经 CreateProcessW；Low IL 经 CreateProcessAsUserW。
/// 管道全部非继承（bInheritHandles=FALSE），会话经属性表挂载。
/// 任一原语不可用/失败 → 结构化错误，失败关闭。
pub fn spawn_pty(
    argv: &[String],
    cwd: &str,
    env_block: &[u16],
    low_integrity: bool,
    _want_stdin: bool,
) -> io::Result<PtySpawn> {
    unsafe {
        let kernel32 = load_module("kernel32.dll");
        type CreatePtyFn =
            unsafe extern "system" fn(Coord, HANDLE, HANDLE, u32, *mut HPC) -> i32;
        let create_pty: CreatePtyFn =
            std::mem::transmute(get_proc(kernel32, "CreatePseudoConsole")?);

        let sa = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: std::ptr::null_mut(),
            bInheritHandle: 1,
        };
        let make_pipe = || -> io::Result<(HANDLE, HANDLE)> {
            let create_pipe: unsafe extern "system" fn(
                *mut HANDLE,
                *mut HANDLE,
                *const SECURITY_ATTRIBUTES,
                u32,
            ) -> i32 = std::mem::transmute(get_proc(kernel32, "CreatePipe")?);
            let mut r: HANDLE = std::ptr::null_mut();
            let mut w: HANDLE = std::ptr::null_mut();
            if create_pipe(&mut r, &mut w, &sa, 0) == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok((r, w))
        };
        let (pty_in_r, pty_in_w) = make_pipe()?;
        let (pty_out_r, pty_out_w) = make_pipe().map_err(|err| {
            CloseHandle(pty_in_r);
            CloseHandle(pty_in_w);
            err
        })?;
        // ConPTY 会话接管两端；主机侧只留写入端与读取端。
        let mut hpc: HPC = std::ptr::null_mut();
        let hr = create_pty(Coord { x: 120, y: 30 }, pty_in_r, pty_out_w, 0, &mut hpc);
        ac_trace(&format!("pty:create hr={hr:#x} hpc_null={}", hpc.is_null()));
        CloseHandle(pty_in_r);
        CloseHandle(pty_out_w);
        if hr < 0 {
            CloseHandle(pty_in_w);
            CloseHandle(pty_out_r);
            return Err(io::Error::new(
                io::ErrorKind::Unsupported,
                format!("pty:create_console: HRESULT {hr:#x}"),
            ));
        }
        // 主机侧句柄一律非继承（会话经属性表传递，不靠句柄继承）。
        SetHandleInformation(pty_in_w, HANDLE_FLAG_INHERIT, 0);
        SetHandleInformation(pty_out_r, HANDLE_FLAG_INHERIT, 0);

        let init_attr: unsafe extern "system" fn(
            *mut core::ffi::c_void,
            u32,
            u32,
            *mut usize,
        ) -> i32 = std::mem::transmute(get_proc(
            kernel32,
            "InitializeProcThreadAttributeList",
        )?);
        let update_attr: unsafe extern "system" fn(
            *mut core::ffi::c_void,
            u32,
            usize,
            *const core::ffi::c_void,
            usize,
            *mut core::ffi::c_void,
            *const core::ffi::c_void,
        ) -> i32 = std::mem::transmute(get_proc(kernel32, "UpdateProcThreadAttribute")?);
        let delete_attr: unsafe extern "system" fn(*mut core::ffi::c_void) =
            std::mem::transmute(get_proc(kernel32, "DeleteProcThreadAttributeList")?);

        let mut size: usize = 0;
        let _ = init_attr(std::ptr::null_mut(), 1, 0, &mut size);
        let mut attr_buf: Vec<u8> = vec![0u8; size];
        let attr_list = attr_buf.as_mut_ptr() as *mut core::ffi::c_void;
        if init_attr(attr_list, 1, 0, &mut size) == 0 {
            CloseHandle(pty_in_w);
            CloseHandle(pty_out_r);
            CloseHandle(hpc);
            return Err(io::Error::last_os_error());
        }
        // PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
        if update_attr(
            attr_list,
            0,
            0x0002_0016usize,
            hpc,
            std::mem::size_of::<HPC>(),
            std::ptr::null_mut(),
            std::ptr::null(),
        ) == 0
        {
            let err = io::Error::last_os_error();
            delete_attr(attr_list);
            CloseHandle(pty_in_w);
            CloseHandle(pty_out_r);
            CloseHandle(hpc);
            return Err(err);
        }

        let mut command_line: Vec<u16> = build_command_line(argv).encode_utf16().collect();
        command_line.push(0);
        let mut cwd_utf16: Vec<u16> = cwd.encode_utf16().collect();
        cwd_utf16.push(0);

        let mut startup_ex: STARTUPINFOEXW = std::mem::zeroed();
        startup_ex.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
        startup_ex.lpAttributeList = attr_list;

        let mut app_name: Vec<u16> = argv[0].encode_utf16().collect();
        app_name.push(0);
        let mut proc_info: PROCESS_INFORMATION = std::mem::zeroed();
        let token = if low_integrity {
            let token = duplicate_primary_token().map_err(|err| {
                delete_attr(attr_list);
                CloseHandle(pty_in_w);
                CloseHandle(pty_out_r);
                CloseHandle(hpc);
                err
            })?;
            if let Err(err) = set_low_integrity(token) {
                CloseHandle(token);
                delete_attr(attr_list);
                CloseHandle(pty_in_w);
                CloseHandle(pty_out_r);
                CloseHandle(hpc);
                return Err(err);
            }
            Some(token)
        } else {
            None
        };
        let ok = match token {
            Some(token) => CreateProcessAsUserW(
                token,
                std::ptr::null(),
                command_line.as_mut_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                0,
                // 注意：ConPTY 子进程不得 CREATE_SUSPENDED——控制台附着在进程
                // 初始化期完成，挂起会导致与 conhost 的连接死锁（实证：挂起态下
                // 子进程永久无输出）。Job 成员经宿主自分配继承，无窗口风险。
                CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
                env_block.as_ptr() as *const core::ffi::c_void,
                cwd_utf16.as_ptr(),
                &startup_ex.StartupInfo,
                &mut proc_info,
            ),
            None => CreateProcessW(
                app_name.as_ptr(),
                command_line.as_mut_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                0,
                CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
                env_block.as_ptr() as *const core::ffi::c_void,
                cwd_utf16.as_ptr(),
                &startup_ex.StartupInfo,
                &mut proc_info,
            ),
        };
        delete_attr(attr_list);
        if let Some(token) = token {
            CloseHandle(token);
        }
        ac_trace(&format!(
            "pty:create_process ok={ok} err={} pid={}",
            if ok == 0 { io::Error::last_os_error().raw_os_error().unwrap_or(-1) } else { 0 },
            proc_info.dwProcessId,
        ));
        if ok == 0 {
            let err = io::Error::last_os_error();
            CloseHandle(pty_in_w);
            CloseHandle(pty_out_r);
            CloseHandle(hpc);
            return Err(err);
        }
        Ok(PtySpawn {
            process_handle: proc_info.hProcess,
            main_thread_handle: proc_info.hThread,
            output_read: PipeReader { handle: pty_out_r },
            input_write: PipeWriter { handle: pty_in_w },
            console: PseudoConsole { handle: hpc },
        })
    }
}

/// main.rs 使用的诊断入口（PA_EXEC_HOST_DEBUG 门控）。
pub fn ac_trace_public(msg: &str) {
    ac_trace(msg);
}

/// 树级联兜底：Job 不可用时经 taskkill /T /F 终止整棵进程树。
pub fn taskkill_tree(pid: u32) -> io::Result<()> {
    use std::os::windows::process::CommandExt;

    let status = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
        .output();
    match status {
        Ok(_) => Ok(()),
        Err(err) => Err(err),
    }
}

pub fn pid_of_process_handle(handle: HANDLE) -> u32 {
    use windows_sys::Win32::System::Threading::GetProcessId;
    unsafe { GetProcessId(handle) }
}
