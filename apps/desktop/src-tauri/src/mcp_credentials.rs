//! MCP 专用凭据空间与私有管道桥；系统库错误和令牌从不返回 WebView。
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{atomic::{AtomicBool, Ordering}, Mutex};
use std::time::{Duration, Instant};
use zeroize::{Zeroize, Zeroizing};

const MAX_SECRET_BYTES: usize = 64 * 1024;
const MAX_PARTS: usize = 128;
const INVALID: &str = "credential_scope_invalid";
const FAILED: &str = "credential_store_failed";
const CLOSED: &str = "credential_transport_closed";

#[derive(Clone, Deserialize, Serialize, Eq, PartialEq, Hash)]
#[serde(deny_unknown_fields)]
pub(crate) struct Binding {
    identity: String,
    service_id: String,
    version: String,
    slot: String,
}

fn hex(value: &str, size: usize) -> bool {
    value.len() == size && value.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

impl Binding {
    fn validate(&self) -> Result<(), String> {
        if !hex(&self.identity, 64) || !hex(&self.service_id, 32) || !hex(&self.version, 32)
            || !matches!(self.slot.as_str(), "static" | "oauth") { return Err(INVALID.into()); }
        Ok(())
    }

    fn account(&self) -> Result<String, String> {
        self.validate()?;
        Ok(format!("mcp.{}.{}.{}.{}", self.identity, self.service_id, self.version, self.slot))
    }

    fn reference(&self) -> Result<String, String> {
        self.validate()?;
        Ok(format!("secret://os-keyring/mcp/{}/{}/{}/{}", self.identity, self.service_id, self.version, self.slot))
    }
}

trait SecretStore {
    fn read(&mut self, account: &str) -> Result<Option<String>, String>;
    fn write(&mut self, account: &str, value: &str) -> Result<(), String>;
    fn remove(&mut self, account: &str) -> Result<(), String>;
}

struct KeyringStore;
impl SecretStore for KeyringStore {
    fn read(&mut self, account: &str) -> Result<Option<String>, String> { crate::credentials::get(account).map_err(|_| FAILED.into()) }
    fn write(&mut self, account: &str, value: &str) -> Result<(), String> { crate::credentials::set(account, value).map_err(|_| FAILED.into()) }
    fn remove(&mut self, account: &str) -> Result<(), String> { crate::credentials::delete(account).map_err(|_| FAILED.into()) }
}

#[derive(Clone, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
struct Manifest { generation: String, parts: usize, bytes: usize }
impl Manifest {
    fn validate(&self) -> Result<(), String> {
        if !hex(&self.generation, 32) || !(1..=MAX_PARTS).contains(&self.parts)
            || !(1..=MAX_SECRET_BYTES).contains(&self.bytes) { return Err(FAILED.into()); }
        Ok(())
    }
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Journal { old: Option<Manifest>, new: Option<Manifest> }

struct Vault<S: SecretStore> { store: S }
impl<S: SecretStore> Vault<S> {
    fn set_bound(&mut self, binding: &Binding, value: &str) -> Result<(), String> {
        if binding.slot == "static" {
            if let Some(previous) = self.get(binding)? {
                let previous = Zeroizing::new(previous);
                // 静态配置版本一旦写入不能被旧窗口改写；同值重试用于恢复结果未确认的保存。
                return if previous.as_str() == value { Ok(()) } else { Err(INVALID.into()) };
            }
        }
        self.set(binding, value)
    }

    fn manifest(&mut self, account: &str) -> Result<Option<Manifest>, String> {
        let Some(raw) = self.store.read(account)? else { return Ok(None) };
        let raw = Zeroizing::new(raw);
        let value: Manifest = serde_json::from_str(&raw).map_err(|_| FAILED)?;
        value.validate()?;
        Ok(Some(value))
    }

    fn recover(&mut self, account: &str) -> Result<(), String> {
        let journal_account = format!("{account}.pending");
        let Some(raw) = self.store.read(&journal_account)? else { return Ok(()) };
        let raw = Zeroizing::new(raw);
        let journal: Journal = serde_json::from_str(&raw).map_err(|_| FAILED)?;
        for entry in [&journal.old, &journal.new].into_iter().flatten() { entry.validate()?; }
        let active = self.manifest(account)?;
        if active.is_some() && active != journal.old && active != journal.new { return Err(FAILED.into()); }
        // manifest 是唯一提交点；崩溃后只清除未激活的分片，旧活动值保持完整。
        for entry in [journal.old, journal.new].into_iter().flatten() {
            if active.as_ref() != Some(&entry) {
                for index in 0..entry.parts {
                    self.store.remove(&format!("{account}.{}.{}", entry.generation, index))?;
                }
            }
        }
        self.store.remove(&journal_account)
    }

    fn get(&mut self, binding: &Binding) -> Result<Option<String>, String> {
        let account = binding.account()?;
        self.recover(&account)?;
        let Some(active) = self.manifest(&account)? else { return Ok(None) };
        let mut value = Zeroizing::new(String::new());
        for index in 0..active.parts {
            let part = Zeroizing::new(self.store.read(&format!("{account}.{}.{}", active.generation, index))?.ok_or(FAILED)?);
            if value.len() + part.len() > MAX_SECRET_BYTES { return Err(FAILED.into()); }
            value.push_str(&part);
        }
        if value.len() != active.bytes { return Err(FAILED.into()); }
        Ok(Some(value.to_string()))
    }

    fn set(&mut self, binding: &Binding, value: &str) -> Result<(), String> {
        let account = binding.account()?;
        if value.is_empty() || value.len() > MAX_SECRET_BYTES || value.contains('\0') { return Err(INVALID.into()); }
        self.recover(&account)?;
        let old = self.manifest(&account)?;
        let mut random = [0_u8; 16];
        getrandom::getrandom(&mut random).map_err(|_| FAILED)?;
        let generation = random.iter().map(|byte| format!("{byte:02x}")).collect();
        // Windows 的密码项按 UTF-16 字节限长；每片最多 1000 个码元，兼容较长 OAuth JWT。
        let mut parts: Vec<Zeroizing<String>> = Vec::new();
        let mut part = Zeroizing::new(String::new());
        let mut units = 0;
        for character in value.chars() {
            if units + character.len_utf16() > 1000 {
                parts.push(part);
                part = Zeroizing::new(String::new());
                units = 0;
            }
            part.push(character);
            units += character.len_utf16();
        }
        if !part.is_empty() { parts.push(part); }
        let next = Manifest { generation, parts: parts.len(), bytes: value.len() };
        next.validate()?;
        let journal = Journal { old, new: Some(next.clone()) };
        self.store.write(&format!("{account}.pending"), &serde_json::to_string(&journal).map_err(|_| FAILED)?)?;
        for (index, part) in parts.iter().enumerate() {
            self.store.write(&format!("{account}.{}.{}", next.generation, index), part)?;
        }
        self.store.write(&account, &serde_json::to_string(&next).map_err(|_| FAILED)?)?;
        self.recover(&account)
    }

    fn delete(&mut self, binding: &Binding) -> Result<(), String> {
        let account = binding.account()?;
        self.recover(&account)?;
        let Some(old) = self.manifest(&account)? else { return Ok(()) };
        self.store.write(&format!("{account}.pending"), &serde_json::to_string(&Journal { old: Some(old), new: None }).map_err(|_| FAILED)?)?;
        self.store.remove(&account)?;
        self.recover(&account)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request { operation: String, binding: Binding, value: Option<String> }

pub(crate) struct CredentialBridge {
    vault: Mutex<Vault<KeyringStore>>,
    allowed: Mutex<HashMap<Binding, Instant>>,
    identity: Mutex<Option<String>>,
    closed: AtomicBool,
}

#[derive(Serialize)]
pub(crate) struct CredentialStatus { reference: String, configured: bool }

impl CredentialBridge {
    pub(crate) fn new() -> Self {
        Self { vault: Mutex::new(Vault { store: KeyringStore }), allowed: Mutex::new(HashMap::new()),
            identity: Mutex::new(None), closed: AtomicBool::new(false) }
    }

    fn guard(&self, binding: &Binding) -> Result<(), String> {
        if self.closed.load(Ordering::Acquire) { return Err(CLOSED.into()); }
        binding.validate()?;
        let mut identity = self.identity.lock().map_err(|_| FAILED)?;
        if identity.as_ref().is_some_and(|value| value != &binding.identity) { return Err(INVALID.into()); }
        if identity.is_none() { *identity = Some(binding.identity.clone()); }
        Ok(())
    }

    fn register(&self, binding: &Binding) -> Result<(), String> {
        self.guard(binding)?;
        let mut allowed = self.allowed.lock().map_err(|_| FAILED)?;
        allowed.retain(|_, time| time.elapsed() < Duration::from_secs(600));
        if allowed.len() >= 128 && !allowed.contains_key(binding) { return Err("credential_busy".into()); }
        allowed.insert(binding.clone(), Instant::now());
        Ok(())
    }

    pub(crate) fn save_static(&self, binding: Binding, value: String) -> Result<CredentialStatus, String> {
        let value = Zeroizing::new(value);
        binding.validate()?;
        let mut vault = self.vault.lock().map_err(|_| FAILED)?;
        if self.closed.load(Ordering::Acquire) { return Err(CLOSED.into()); }
        // 和删除共用操作锁；已取消的准备引用不能在等待锁之后被旧窗口重新写回。
        if binding.slot != "static" || !self.allowed.lock().map_err(|_| FAILED)?.get(&binding)
            .is_some_and(|time| time.elapsed() < Duration::from_secs(600)) { return Err(INVALID.into()); }
        self.guard(&binding)?;
        vault.set_bound(&binding, &value)?;
        Ok(CredentialStatus { reference: binding.reference()?, configured: true })
    }

    pub(crate) fn handle(&self, mut frame: Value) -> Value {
        let id = frame.get("id").and_then(Value::as_str).unwrap_or("").to_owned();
        let result = (|| {
            if !id.starts_with("mcp-") || !hex(&id[4..], 32) || frame.get("method").and_then(Value::as_str) != Some("mcp_credential")
                || frame.as_object().map(|object| object.len()) != Some(3) { return Err(INVALID.to_string()); }
            let request: Request = serde_json::from_value(frame.get_mut("params").map(Value::take).ok_or(INVALID)?).map_err(|_| INVALID)?;
            let secret = request.value.map(Zeroizing::new);
            self.guard(&request.binding)?;
            if secret.is_some() != (request.operation == "set") { return Err(INVALID.into()); }
            match request.operation.as_str() {
                "bind" => { self.register(&request.binding)?; Ok(json!({})) }
                "get" => {
                    let mut vault = self.vault.lock().map_err(|_| FAILED)?;
                    if self.closed.load(Ordering::Acquire) { return Err(CLOSED.into()); }
                    let value = vault.get(&request.binding)?;
                    let mut result = serde_json::Map::new();
                    result.insert("value".into(), value.map(Value::String).unwrap_or(Value::Null));
                    Ok(Value::Object(result))
                }
                "set" => {
                    let mut vault = self.vault.lock().map_err(|_| FAILED)?;
                    if self.closed.load(Ordering::Acquire) { return Err(CLOSED.into()); }
                    vault.set_bound(&request.binding, secret.as_ref().ok_or(INVALID)?.as_str())?;
                    Ok(json!({"reference": request.binding.reference()?}))
                }
                "delete" => {
                    let mut vault = self.vault.lock().map_err(|_| FAILED)?;
                    if self.closed.load(Ordering::Acquire) { return Err(CLOSED.into()); }
                    vault.delete(&request.binding)?;
                    self.allowed.lock().map_err(|_| FAILED)?.remove(&request.binding);
                    Ok(json!({}))
                }
                _ => Err(INVALID.into()),
            }
        })();
        erase_frame(&mut frame);
        let mut response = serde_json::Map::new();
        response.insert("id".into(), Value::String(id));
        response.insert("method".into(), Value::String("mcp_credential_result".into()));
        match result {
            Ok(value) => { response.insert("result".into(), value); }
            Err(code) => { response.insert("error".into(), Value::String(code)); }
        }
        Value::Object(response)
    }

    pub(crate) fn close(&self) {
        self.closed.store(true, Ordering::Release);
        if let Ok(mut allowed) = self.allowed.lock() { allowed.clear(); }
    }
}

pub(crate) fn erase_frame(frame: &mut Value) {
    match frame {
        Value::String(text) => text.zeroize(),
        Value::Array(values) => { for value in values { erase_frame(value); } }
        Value::Object(values) => { for value in values.values_mut() { erase_frame(value); } }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct MemoryStore { values: HashMap<String, String>, fail_after: Option<usize>, writes: usize,
        fail_remove: Option<usize>, removes: usize }
    impl SecretStore for MemoryStore {
        fn read(&mut self, account: &str) -> Result<Option<String>, String> { Ok(self.values.get(account).cloned()) }
        fn write(&mut self, account: &str, value: &str) -> Result<(), String> {
            self.writes += 1;
            if self.fail_after == Some(self.writes) { return Err(FAILED.into()); }
            assert!(value.encode_utf16().count() <= 1000);
            self.values.insert(account.into(), value.into()); Ok(())
        }
        fn remove(&mut self, account: &str) -> Result<(), String> {
            self.removes += 1;
            if self.fail_remove == Some(self.removes) { return Err(FAILED.into()); }
            self.values.remove(account); Ok(())
        }
    }
    fn binding() -> Binding {
        Binding { identity: "a".repeat(64), service_id: "b".repeat(32), version: "c".repeat(32), slot: "static".into() }
    }

    #[test]
    fn namespaces_bind_identity_service_version_and_slot() {
        let base = binding();
        assert!(base.account().unwrap().starts_with("mcp."));
        let mut changed = base.clone(); changed.slot = "oauth".into();
        assert_ne!(base.account().unwrap(), changed.account().unwrap());
        changed.identity = "d".repeat(64);
        assert_ne!(base.reference().unwrap(), changed.reference().unwrap());
        for value in ["../account", "model-provider.alias.api-key", ""] {
            changed.service_id = value.into(); assert!(changed.account().is_err());
        }
    }

    #[test]
    fn long_unicode_credentials_roundtrip_and_delete_without_plaintext_files() {
        let mut vault = Vault { store: MemoryStore::default() };
        let value = "测试😀token".repeat(500);
        vault.set(&binding(), &value).unwrap();
        assert_eq!(vault.get(&binding()).unwrap().as_deref(), Some(value.as_str()));
        vault.set(&binding(), "replacement").unwrap();
        assert_eq!(vault.store.values.len(), 2);
        vault.delete(&binding()).unwrap();
        assert!(vault.store.values.is_empty());
        assert_eq!(vault.get(&binding()).unwrap(), None);
    }

    #[test]
    fn failed_staging_preserves_previous_value_and_recovery_cleans_partial_parts() {
        for fail in 1..=5 {
            let mut vault = Vault { store: MemoryStore::default() };
            vault.set(&binding(), "previous").unwrap();
            vault.store.fail_after = Some(vault.store.writes + fail);
            let result = vault.set(&binding(), &"x".repeat(2500));
            vault.store.fail_after = None;
            let restored = vault.get(&binding()).unwrap().unwrap();
            if result.is_err() { assert_eq!(restored, "previous"); }
            else { assert_eq!(restored, "x".repeat(2500)); }
            assert!(!vault.store.values.keys().any(|key| key.ends_with(".pending")));
            assert_eq!(vault.store.values.len(), if result.is_err() { 2 } else { 4 });
        }
    }

    #[test]
    fn missing_or_corrupt_parts_fail_without_returning_partial_secrets() {
        let mut vault = Vault { store: MemoryStore::default() };
        vault.set(&binding(), "synthetic-secret").unwrap();
        let account = binding().account().unwrap();
        let manifest = vault.manifest(&account).unwrap().unwrap();
        vault.store.values.remove(&format!("{account}.{}.0", manifest.generation));
        assert_eq!(vault.get(&binding()).unwrap_err(), FAILED);
        assert_eq!(vault.set(&binding(), &"x".repeat(MAX_SECRET_BYTES + 1)).unwrap_err(), INVALID);
    }

    #[test]
    fn failure_after_commit_and_interrupted_delete_are_recoverable() {
        let mut vault = Vault { store: MemoryStore::default() };
        vault.set(&binding(), "previous").unwrap();
        vault.store.fail_remove = Some(vault.store.removes + 1);
        assert_eq!(vault.set(&binding(), "replacement").unwrap_err(), FAILED);
        vault.store.fail_remove = None;
        // 模拟重新打开系统库：只保留持久化条目，不依赖上个对象的内存状态。
        let mut reopened = Vault { store: MemoryStore { values: vault.store.values, ..MemoryStore::default() } };
        assert_eq!(reopened.get(&binding()).unwrap().as_deref(), Some("replacement"));
        assert_eq!(reopened.store.values.len(), 2);
        reopened.store.fail_remove = Some(reopened.store.removes + 2);
        assert_eq!(reopened.delete(&binding()).unwrap_err(), FAILED);
        reopened.store.fail_remove = None;
        assert_eq!(reopened.get(&binding()).unwrap(), None);
        assert!(reopened.store.values.is_empty());
    }

    #[test]
    fn static_versions_are_immutable_but_same_value_retry_and_oauth_refresh_work() {
        let mut vault = Vault { store: MemoryStore::default() };
        let static_binding = binding();
        vault.set_bound(&static_binding, "synthetic-first").unwrap();
        vault.set_bound(&static_binding, "synthetic-first").unwrap();
        assert_eq!(vault.set_bound(&static_binding, "synthetic-other").unwrap_err(), INVALID);
        let mut oauth = binding(); oauth.slot = "oauth".into();
        vault.set_bound(&oauth, "synthetic-initial-token").unwrap();
        vault.set_bound(&oauth, "synthetic-refreshed-token").unwrap();
        assert_eq!(vault.get(&oauth).unwrap().as_deref(), Some("synthetic-refreshed-token"));
        assert_eq!(vault.get(&static_binding).unwrap().as_deref(), Some("synthetic-first"));
    }

    #[test]
    fn renderer_cannot_read_or_write_an_unregistered_or_oauth_binding() {
        let bridge = CredentialBridge::new();
        assert!(bridge.save_static(binding(), "never-written".into()).is_err());
        let mut oauth = binding(); oauth.slot = "oauth".into();
        bridge.register(&oauth).unwrap();
        assert!(bridge.save_static(oauth, "never-written".into()).is_err());
        let mut other = binding(); other.identity = "f".repeat(64);
        assert!(bridge.register(&other).is_err());
        bridge.close();
        assert!(bridge.register(&binding()).is_err());
    }

    #[test]
    fn malformed_private_requests_return_only_a_stable_error() {
        let bridge = CredentialBridge::new();
        let frame = json!({"id": format!("mcp-{}", "a".repeat(32)), "method": "mcp_credential",
            "params": {"operation":"get", "binding":binding(), "account":"model-provider.test.api-key", "value":"synthetic-secret"}});
        let response = bridge.handle(frame).to_string();
        assert!(response.contains(INVALID));
        assert!(!response.contains("synthetic-secret") && !response.contains("model-provider"));
    }
}
