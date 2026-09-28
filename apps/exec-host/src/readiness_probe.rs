//! 仅测试构建使用的只读边界探针；只登记合成编号和关联，不采集输出正文或凭据。
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

#[link(name = "kernel32")]
extern "system" {
    fn QueryPerformanceCounter(value: *mut i64) -> i32;
    fn QueryPerformanceFrequency(value: *mut i64) -> i32;
}

pub fn qpc() -> i64 {
    let mut value = 0;
    if unsafe { QueryPerformanceCounter(&mut value) } == 0 {
        return 0;
    }
    value
}

pub fn frequency() -> i64 {
    let mut value = 0;
    if unsafe { QueryPerformanceFrequency(&mut value) } == 0 {
        return 0;
    }
    value
}

pub struct Config {
    pub probe_id: String,
    pub root: PathBuf,
    pub drop_create_response_once: bool,
}

fn plain(path: &Path) -> Result<PathBuf, String> {
    use std::os::windows::fs::MetadataExt;
    if !path.is_absolute() {
        return Err("探针路径必须为绝对路径".into());
    }
    for ancestor in path.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor).map_err(|_| "探针路径不可读")?;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err("探针路径不允许重解析点".into());
        }
    }
    path.canonicalize().map_err(|_| "探针路径不可定位".into())
}

impl Config {
    fn parse(value: &Value, executable: &Path) -> Result<Self, String> {
        let map = value.as_object().ok_or("探针配置必须为对象")?;
        let keys = ["schema", "probe_id", "root", "drop_create_response_once"];
        if map.len() != keys.len()
            || !keys.iter().all(|key| map.contains_key(*key))
            || value["schema"] != 1
        {
            return Err("探针配置版本或字段不匹配".into());
        }
        let probe_id = value["probe_id"].as_str().ok_or("探针编号缺失")?;
        if probe_id.len() != 8 || !probe_id.bytes().all(|b| b.is_ascii_digit()) {
            return Err("探针编号必须为八位数字".into());
        }
        let root = plain(Path::new(value["root"].as_str().ok_or("隔离根目录缺失")?))?;
        if !root.components().any(|part| part.as_os_str() == ".run")
            || !plain(executable)?.starts_with(&root)
        {
            return Err("探针只能从 .run 隔离目录的副本启动".into());
        }
        Ok(Self {
            probe_id: probe_id.into(),
            root,
            drop_create_response_once: value["drop_create_response_once"]
                .as_bool()
                .ok_or("注入开关类型无效")?,
        })
    }
}

struct Log {
    file: File,
    rows: u64,
    failed: bool,
}
struct Probe {
    config: Config,
    log: Mutex<Log>,
}
static PROBE: OnceLock<Option<Probe>> = OnceLock::new();

pub fn initialize(role: &str) -> Result<(), String> {
    if PROBE.get().is_some() {
        return Ok(());
    }
    let executable = std::env::current_exe().map_err(|_| "探针无法定位进程")?;
    let config_path = executable.with_file_name("readiness-probe.json");
    if !config_path.try_exists().map_err(|_| "探针配置不可访问")? {
        let _ = PROBE.set(None);
        return Ok(());
    }
    let config_path = plain(&config_path)?;
    if std::fs::metadata(&config_path)
        .map_err(|_| "探针配置不可读取")?
        .len()
        > 4096
    {
        return Err("探针配置超限".into());
    }
    let settings = Config::parse(
        &serde_json::from_slice(&std::fs::read(config_path).map_err(|_| "探针配置读取失败")?)
            .map_err(|_| "探针配置 JSON 无效")?,
        &executable,
    )?;
    let directory = plain(&settings.root.join("trace"))?;
    let path = directory.join(format!("{role}-{}.jsonl", std::process::id()));
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| "探针记录已存在或不可写")?;
    if frequency() <= 0 || qpc() <= 0 {
        return Err("探针 QPC 不可用".into());
    }
    PROBE
        .set(Some(Probe {
            config: settings,
            log: Mutex::new(Log {
                file,
                rows: 0,
                failed: false,
            }),
        }))
        .map_err(|_| "探针重复初始化")?;
    if !record(
        json!({"event": "probe_started", "role": role, "probe_id": config().unwrap().probe_id,
                      "frequency": frequency(), "qpc": qpc()}),
    ) {
        return Err("探针记录失败".into());
    }
    Ok(())
}

pub fn config() -> Option<&'static Config> {
    PROBE
        .get()
        .and_then(|probe| probe.as_ref().map(|probe| &probe.config))
}

pub fn validate_profile() -> Result<(), String> {
    if let Some(config) = config() {
        for (key, relative) in [
            ("USERPROFILE", "profile"),
            ("APPDATA", "profile/AppData/Roaming"),
            ("LOCALAPPDATA", "profile/AppData/Local"),
            ("WEBVIEW2_USER_DATA_FOLDER", "webview"),
        ] {
            let actual = std::env::var_os(key).ok_or("探针隔离配置缺失")?;
            if plain(Path::new(&actual))? != plain(&config.root.join(relative))? {
                return Err("探针拒绝访问隔离目录之外的用户配置".into());
            }
        }
    }
    Ok(())
}

pub fn validate_data_directory(path: &Path) -> Result<(), String> {
    if let Some(config) = config() {
        let expected = config.root.join("profile").join("AppData").join("Local");
        validate_directory_under(path, &expected)?;
    }
    Ok(())
}

pub fn local_data_directory(default: PathBuf, identifier: &str) -> Result<PathBuf, String> {
    select_local_data_directory(config(), default, identifier)
}

fn select_local_data_directory(
    config: Option<&Config>,
    default: PathBuf,
    identifier: &str,
) -> Result<PathBuf, String> {
    let Some(config) = config else { return Ok(default) };
    if identifier.is_empty()
        || identifier.starts_with('.')
        || identifier.ends_with('.')
        || !identifier.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-'))
    {
        return Err("探针应用标识不能包含路径片段".into());
    }
    // Known Folder 不随进程环境变量重定向，探针必须显式选择已校验的隔离根。
    let local = config.root.join("profile/AppData/Local");
    let selected = local.join(identifier).join("local-projects");
    validate_directory_under(&selected, &local)?;
    Ok(selected)
}

fn validate_directory_under(path: &Path, expected: &Path) -> Result<(), String> {
    if !path.is_absolute()
        || path
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err("探针数据路径必须是无父目录跳转的绝对路径".into());
    }
    let mut existing = path;
    let mut missing = Vec::new();
    loop {
        match std::fs::symlink_metadata(existing) {
            Ok(_) => break,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                missing.push(existing.file_name().ok_or("探针数据路径无效")?);
                existing = existing.parent().ok_or("探针数据路径无父目录")?;
            }
            Err(_) => return Err("探针数据路径不可核验".into()),
        }
    }
    let mut resolved = plain(existing)?;
    for part in missing.into_iter().rev() {
        resolved.push(part);
    }
    if !resolved.starts_with(plain(expected)?) {
        return Err("探针拒绝访问隔离目录之外的数据".into());
    }
    Ok(())
}

pub fn record(mut value: Value) -> bool {
    let Some(probe) = PROBE.get().and_then(Option::as_ref) else {
        return false;
    };
    let Ok(mut log) = probe.log.lock() else {
        return false;
    };
    if log.failed {
        return false;
    }
    if log.rows >= 4096 {
        log.failed = true;
        return false;
    }
    value["row"] = json!(log.rows);
    value["pid"] = json!(std::process::id());
    let mut bytes = value.to_string().into_bytes();
    if bytes.len() > 8192 {
        log.failed = true;
        return false;
    }
    bytes.push(b'\n');
    if log.file.write_all(&bytes).is_err() {
        log.failed = true;
        return false;
    }
    log.rows += 1;
    true
}

pub struct MarkerReader {
    prefix: Vec<u8>,
    tail: Vec<u8>,
    total: u64,
    emitted_end: u64,
}
impl MarkerReader {
    pub fn new(probe_id: &str) -> Self {
        Self {
            prefix: format!("PAE {probe_id} ").into_bytes(),
            tail: Vec::new(),
            total: 0,
            emitted_end: 0,
        }
    }
    pub fn observe(&mut self, chunk: &[u8]) -> Vec<(u16, u64, bool)> {
        let length = self.prefix.len() + 7;
        let old_total = self.total;
        let base = old_total - self.tail.len() as u64;
        self.tail.extend_from_slice(chunk);
        self.total += chunk.len() as u64;
        let mut result = Vec::new();
        for (offset, bytes) in self.tail.windows(length).enumerate() {
            let end = base + offset as u64 + length as u64;
            let digits = &bytes[self.prefix.len()..self.prefix.len() + 3];
            if end <= self.emitted_end
                || !bytes.starts_with(&self.prefix)
                || !digits.iter().all(u8::is_ascii_digit)
                || &bytes[length - 4..] != b" END"
            {
                continue;
            }
            let index = digits
                .iter()
                .fold(0_u16, |value, digit| value * 10 + (digit - b'0') as u16);
            if index >= 100 {
                continue;
            }
            result.push((index, end, base + (offset as u64) < old_total));
            self.emitted_end = end;
        }
        let keep = self.tail.len().saturating_sub(length - 1);
        self.tail.drain(..keep);
        result
    }
}

pub struct Receipt {
    reader: MarkerReader,
    execution_id: String,
    stream: &'static str,
    reads: VecDeque<(u64, i64)>,
}
impl Receipt {
    pub fn new(execution_id: &str, stream: &'static str) -> Option<Self> {
        config().map(|config| Self {
            reader: MarkerReader::new(&config.probe_id),
            execution_id: execution_id.into(),
            stream,
            reads: VecDeque::new(),
        })
    }
    pub fn observe(&mut self, chunk: &[u8], received: i64) {
        self.reads
            .push_back((self.reader.total + chunk.len() as u64, received));
        // 一个标记至多占二十个非空读取；保留边界时间，跨读取时使用首字节时间。
        if self.reads.len() > 32 {
            self.reads.pop_front();
        }
        let length = (self.reader.prefix.len() + 7) as u64;
        for (index, byte_end, fragmented) in self.reader.observe(chunk) {
            let started = self
                .reads
                .iter()
                .find(|(end, _)| *end > byte_end - length)
                .map(|(_, at)| *at)
                .unwrap_or(0);
            let saved = record(
                json!({"event": "host_received", "qpc": started, "complete_qpc": received, "index": index,
                "execution_id": self.execution_id, "stream": self.stream, "byte_end": byte_end, "fragmented": fragmented}),
            );
            if saved {
                record(
                    json!({"event": "probe_cost", "index": index, "execution_id": self.execution_id,
                "start_qpc": received, "end_qpc": qpc()}),
                );
            }
        }
    }
    pub fn finish(&self) {
        record(
            json!({"event": "reader_finished", "execution_id": self.execution_id, "stream": self.stream, "qpc": qpc()}),
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn split_markers_use_the_last_read_without_recounting_old_bytes() {
        let mut reader = MarkerReader::new("12345678");
        assert!(reader.observe(b"secret PAE 12345678 0").is_empty());
        let found = reader.observe(b"00 END\nPAE 12345678 001 END\n");
        assert_eq!(
            found.iter().map(|row| (row.0, row.2)).collect::<Vec<_>>(),
            vec![(0, true), (1, false)]
        );
        assert!(reader.observe(b"nothing").is_empty());
        assert_eq!(reader.observe(b"PAE 12345678 001 END")[0].0, 1);
    }
    #[test]
    fn unrelated_or_invalid_markers_are_not_logged_and_tail_is_bounded() {
        let mut reader = MarkerReader::new("12345678");
        assert!(reader
            .observe(b"PAE 12345679 001 END PAE 12345678 100 END PAE 12345678 xxx END")
            .is_empty());
        assert!(reader.observe(&vec![b'x'; 1_000_000]).is_empty());
        assert!(reader.tail.len() < 25);
    }
    #[test]
    fn clock_is_monotonic_and_shared_frequency_is_available() {
        assert!(frequency() > 0);
        let before = qpc();
        assert!(before > 0 && qpc() >= before);
    }

    #[test]
    fn isolation_is_checked_before_creating_a_new_application_directory() {
        let root = std::env::temp_dir().join(format!("readiness-uncreated-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let missing = root.join("application").join("local-projects");
        let outside = root.parent().unwrap().join("must-not-create");
        let result = validate_directory_under(&missing, &root);
        assert!(!missing.exists() && !outside.exists());
        assert!(validate_directory_under(&outside, &root).is_err());
        assert!(validate_directory_under(&root.join("..").join("escape"), &root).is_err());
        std::fs::remove_dir(root).unwrap();
        assert!(
            result.is_ok(),
            "新隔离目录必须可在创建前完成校验：{result:?}"
        );
    }

    #[test]
    fn readiness_data_path_does_not_inherit_the_windows_known_folder() {
        let root = std::env::temp_dir().join(format!("readiness-data-{}", std::process::id()));
        let local = root.join("profile/AppData/Local");
        std::fs::create_dir_all(&local).unwrap();
        let settings = Config { probe_id: "12345678".into(), root: root.clone(), drop_create_response_once: false };
        let ordinary = root.parent().unwrap().join("formal-data-must-not-use");
        assert_eq!(select_local_data_directory(None, ordinary.clone(), "com.personal-assistant.desktop").unwrap(), ordinary);
        let selected = select_local_data_directory(Some(&settings), ordinary.clone(), "com.personal-assistant.desktop").unwrap();
        assert_eq!(selected, local.join("com.personal-assistant.desktop/local-projects"));
        assert!(select_local_data_directory(Some(&settings), ordinary.clone(), "../escape").is_err());
        assert!(!selected.exists() && !ordinary.exists());
    }

    #[test]
    fn configuration_rejects_wrong_identity_outside_paths_and_reparse_points() {
        let root = std::env::temp_dir().join(format!("readiness-config-{}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let executable = root.join("probe.exe");
        std::fs::write(&executable, b"test").unwrap();
        let value =
            json!({"schema":1,"probe_id":"12345678","root":root,"drop_create_response_once":true});
        assert!(
            root.components().any(|part| part.as_os_str() == ".run"),
            "测试必须运行在隔离 .run 目录"
        );
        assert!(Config::parse(&value, &executable).is_ok());
        let mut invalid = value.clone();
        invalid["probe_id"] = json!("1234567x");
        assert!(Config::parse(&invalid, &executable).is_err());
        assert!(Config::parse(&value, &std::env::current_exe().unwrap()).is_err());
        invalid = value.clone();
        invalid["root"] = json!("relative");
        assert!(Config::parse(&invalid, &executable).is_err());
        invalid = value;
        invalid["unexpected"] = json!(true);
        assert!(Config::parse(&invalid, &executable).is_err());
        std::fs::remove_file(executable).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
