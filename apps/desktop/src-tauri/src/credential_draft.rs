//! 未提交的模型密钥只以当前 Windows 用户可解密的快照落盘。
use std::fs;
use std::io::Write;
use std::path::Path;
use zeroize::Zeroizing;

const MAX_DRAFT_BYTES: usize = 256 * 1024;

pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let directory = path.parent().ok_or("存储目录无效")?;
    fs::create_dir_all(directory).map_err(|_| "无法创建凭据存储目录")?;
    let mut random = [0_u8; 16];
    getrandom::getrandom(&mut random).map_err(|_| "无法生成临时文件标识")?;
    let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
    let temporary = directory.join(format!(".credential-{suffix}.tmp"));
    let result = (|| {
        let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&temporary)
            .map_err(|_| "无法创建凭据临时文件")?;
        file.write_all(bytes).and_then(|_| file.sync_all()).map_err(|_| "凭据写入未完成")?;
        drop(file);
        fs::rename(&temporary, path).map_err(|_| "凭据原子替换未完成")?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(windows)]
fn crypt(bytes: &[u8], decrypt: bool) -> Result<Zeroizing<Vec<u8>>, String> {
    use windows_sys::Win32::Foundation::LocalFree;
    use windows_sys::Win32::Security::Cryptography::{
        CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
    };
    let input = CRYPT_INTEGER_BLOB { cbData: bytes.len() as u32, pbData: bytes.as_ptr() as *mut u8 };
    // 用应用通道作为附加熵，候选包与正式包不能互相恢复草稿。
    let entropy = if cfg!(feature = "qa") { b"privateagent.candidate.draft.v1".as_slice() }
                  else { b"privateagent.desktop.draft.v1".as_slice() };
    let extra = CRYPT_INTEGER_BLOB { cbData: entropy.len() as u32, pbData: entropy.as_ptr() as *mut u8 };
    let mut output = CRYPT_INTEGER_BLOB { cbData: 0, pbData: std::ptr::null_mut() };
    unsafe {
        let success = if decrypt {
            CryptUnprotectData(&input, std::ptr::null_mut(), &extra, std::ptr::null(), std::ptr::null(), CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        } else {
            CryptProtectData(&input, std::ptr::null(), &extra, std::ptr::null(), std::ptr::null(), CRYPTPROTECT_UI_FORBIDDEN, &mut output)
        };
        if success == 0 { return Err("Windows 加密凭据存储不可用；输入仍保留在当前窗口".into()); }
        let buffer = std::slice::from_raw_parts_mut(output.pbData, output.cbData as usize);
        let value = Zeroizing::new(buffer.to_vec());
        if decrypt {
            use zeroize::Zeroize;
            buffer.zeroize();
        }
        LocalFree(output.pbData as _);
        Ok(value)
    }
}

#[cfg(not(windows))]
fn crypt(_bytes: &[u8], _decrypt: bool) -> Result<Zeroizing<Vec<u8>>, String> {
    Err("当前平台暂不支持密钥草稿的加密恢复，请点击保存后退出".into())
}

pub fn write(path: &Path, payload: String) -> Result<(), String> {
    let payload = Zeroizing::new(payload);
    if payload.is_empty() || payload.len() > MAX_DRAFT_BYTES {
        return Err("模型草稿超过安全存储容量".into());
    }
    let encrypted = crypt(payload.as_bytes(), false)?;
    atomic_write(path, &encrypted)
}

pub fn read(path: &Path) -> Result<Option<String>, String> {
    let size = match fs::metadata(path) {
        Ok(metadata) => metadata.len(),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("无法读取加密模型草稿".into()),
    };
    if size > (MAX_DRAFT_BYTES + 4096) as u64 { return Err("加密模型草稿大小无效".into()); }
    let encrypted = fs::read(path).map_err(|_| "无法读取加密模型草稿")?;
    let decrypted = crypt(&encrypted, true)?;
    let text = std::str::from_utf8(&decrypted).map_err(|_| "加密模型草稿格式无效")?;
    Ok(Some(text.to_owned()))
}

pub fn clear(path: &Path) -> Result<(), String> {
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("加密模型草稿未能清除，请重试后再离开".into()),
    }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    #[test]
    #[ignore = "仅由强制结束进程的隔离测试启动"]
    fn draft_writer_child() {
        let Ok(directory) = std::env::var("PA_TEST_DRAFT_DIRECTORY") else { return; };
        let account = std::env::var("PA_TEST_DRAFT_ACCOUNT").unwrap();
        assert!(account.starts_with("synthetic-draft-test-"));
        crate::credentials::set(&account, "synthetic-saved-value").unwrap();
        write(&Path::new(&directory).join("draft.bin"), "synthetic-unsaved-value".into()).unwrap();
        fs::write(Path::new(&directory).join("ready"), b"ready").unwrap();
        loop { std::thread::sleep(std::time::Duration::from_secs(1)); }
    }

    #[test]
    fn saved_key_and_encrypted_draft_survive_a_forced_process_stop() {
        let mut random = [0_u8; 16];
        getrandom::getrandom(&mut random).unwrap();
        let suffix: String = random.iter().map(|byte| format!("{byte:02x}")).collect();
        let account = format!("synthetic-draft-test-{suffix}");
        let directory = std::env::temp_dir().join(&account);
        fs::create_dir(&directory).unwrap();
        let mut child = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "credential_draft::tests::draft_writer_child", "--ignored"])
            .env("PA_TEST_DRAFT_DIRECTORY", &directory).env("PA_TEST_DRAFT_ACCOUNT", &account)
            .stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null())
            .spawn().unwrap();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        while !directory.join("ready").exists() && std::time::Instant::now() < deadline {
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        let ready = directory.join("ready").exists();
        let _ = child.kill();
        let _ = child.wait();
        let saved = crate::credentials::get(&account);
        let draft = read(&directory.join("draft.bin"));
        crate::credentials::delete(&account).unwrap();
        clear(&directory.join("draft.bin")).unwrap();
        let _ = fs::remove_file(directory.join("ready"));
        fs::remove_dir(&directory).unwrap();
        assert!(ready, "隔离子进程未完成测试凭据写入");
        assert_eq!(saved.unwrap().as_deref(), Some("synthetic-saved-value"));
        assert_eq!(draft.unwrap().as_deref(), Some("synthetic-unsaved-value"));
    }

    #[test]
    fn encrypted_draft_survives_reopening_and_detects_damage() {
        let directory = std::env::temp_dir().join(format!("pa-draft-test-{}", std::process::id()));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("draft.bin");
        let fixture = r#"{"apiKey":"synthetic-draft-value"}"#;
        write(&path, fixture.into()).unwrap();
        assert!(!fs::read(&path).unwrap().windows(fixture.len()).any(|value| value == fixture.as_bytes()));
        assert_eq!(read(&path).unwrap().as_deref(), Some(fixture));
        write(&path, r#"{"apiKey":"synthetic-replacement"}"#.into()).unwrap();
        assert!(read(&path).unwrap().unwrap().contains("synthetic-replacement"));
        fs::write(&path, b"damaged").unwrap();
        assert!(read(&path).is_err());
        clear(&path).unwrap();
        assert_eq!(read(&path).unwrap(), None);
        fs::remove_dir(&directory).unwrap();
    }
}
