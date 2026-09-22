use keyring::{Entry, Error as KeyringError};
use zeroize::Zeroize;

// 维持既有命名空间；候选包不能访问正式客户端的模型凭据。
const SERVICE: &str = if cfg!(feature = "qa") {
    "com.personal-assistant.desktop.candidate"
} else {
    "com.personal-assistant.desktop"
};
const MODEL_PROVIDER_ACCOUNT_PREFIX: &str = "model-provider.";

fn entry(account: &str) -> Result<Entry, String> {
    #[cfg(all(windows, feature = "readiness-probe"))]
    return readiness_entry(account, crate::readiness_probe::config().is_some());
    #[cfg(not(all(windows, feature = "readiness-probe")))]
    Entry::new(SERVICE, account).map_err(|_| credential_error("open"))
}

#[cfg(all(windows, feature = "readiness-probe"))]
fn readiness_entry(account: &str, active: bool) -> Result<Entry, String> {
    if active {
        return Err("探针模式禁止访问系统凭据库".into());
    }
    Entry::new(SERVICE, account).map_err(|_| credential_error("open"))
}

fn credential_error(operation: &str) -> String {
    format!("system credential store {operation} failed")
}

pub fn get(account: &str) -> Result<Option<String>, String> {
    match entry(account)?.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(KeyringError::NoEntry) => Ok(None),
        Err(_) => Err(credential_error("read")),
    }
}

pub fn exists(account: &str) -> Result<bool, String> {
    match get(account)? {
        Some(mut secret) => {
            secret.zeroize();
            Ok(true)
        }
        None => Ok(false),
    }
}

pub fn set(account: &str, secret: &str) -> Result<(), String> {
    if secret.is_empty() {
        return delete(account);
    }
    entry(account)?
        .set_password(secret)
        .map_err(|_| credential_error("write"))
}

pub fn delete(account: &str) -> Result<(), String> {
    match entry(account)?.delete_credential() {
        Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
        Err(_) => Err(credential_error("delete")),
    }
}

pub fn validate_secret_alias(alias: &str) -> Result<(), String> {
    if alias.is_empty()
        || alias.len() > 64
        || !alias.as_bytes()[0].is_ascii_alphanumeric()
        || !alias
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'.' | b'_' | b'-'))
    {
        return Err("invalid model provider credential alias".to_string());
    }
    Ok(())
}

pub fn model_provider_account(alias: &str) -> Result<String, String> {
    validate_secret_alias(alias)?;
    Ok(format!("{MODEL_PROVIDER_ACCOUNT_PREFIX}{alias}.api-key"))
}

pub fn model_provider_reference(alias: &str) -> Result<String, String> {
    validate_secret_alias(alias)?;
    Ok(format!("secret://os-keyring/model-provider/{alias}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(all(windows, feature = "readiness-probe"))]
    #[test]
    fn readiness_mode_refuses_the_system_credential_store() {
        assert!(
            matches!(readiness_entry("synthetic-no-secret", true), Err(error) if error == "探针模式禁止访问系统凭据库")
        );
    }

    #[test]
    fn model_provider_credentials_are_namespaced_by_safe_alias() {
        assert_eq!(
            model_provider_account("zhipu-prod").unwrap(),
            "model-provider.zhipu-prod.api-key"
        );
        assert_eq!(
            model_provider_reference("zhipu-prod").unwrap(),
            "secret://os-keyring/model-provider/zhipu-prod"
        );
        assert!(model_provider_account("bad/name").is_err());
    }
}
