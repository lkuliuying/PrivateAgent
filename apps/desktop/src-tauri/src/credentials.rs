use keyring::{Entry, Error as KeyringError};
use zeroize::Zeroize;

const SERVICE: &str = "com.personal-assistant.desktop";
pub const DATABASE_PASSWORD_ACCOUNT: &str = "database.password";
pub const OPENAI_API_KEY_ACCOUNT: &str = "provider.openai.api-key";
pub const CLAUDE_API_KEY_ACCOUNT: &str = "provider.claude.api-key";
const MCP_ACCOUNT_PREFIX: &str = "mcp.";
const HTTP_PROFILE_ACCOUNT_PREFIX: &str = "http.";
const SQL_PROFILE_ACCOUNT_PREFIX: &str = "sql.";

fn entry(account: &str) -> Result<Entry, String> {
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

pub fn provider_account(provider: &str) -> Result<&'static str, String> {
    match provider {
        "openai" => Ok(OPENAI_API_KEY_ACCOUNT),
        "claude" => Ok(CLAUDE_API_KEY_ACCOUNT),
        _ => Err("unsupported provider secret".to_string()),
    }
}

pub fn validate_mcp_secret_alias(alias: &str) -> Result<(), String> {
    if alias.is_empty()
        || alias.len() > 64
        || !alias.as_bytes()[0].is_ascii_alphanumeric()
        || !alias
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'.' | b'_' | b'-'))
    {
        return Err("invalid MCP credential alias".to_string());
    }
    Ok(())
}

pub fn mcp_account(alias: &str) -> Result<String, String> {
    validate_mcp_secret_alias(alias)?;
    Ok(format!("{MCP_ACCOUNT_PREFIX}{alias}"))
}

pub fn mcp_reference(alias: &str) -> Result<String, String> {
    validate_mcp_secret_alias(alias)?;
    Ok(format!("secret://os-keyring/mcp/{alias}"))
}

pub fn validate_http_profile_secret_slot(slot: &str) -> Result<(), String> {
    if slot.is_empty()
        || slot.len() > 64
        || !slot.as_bytes()[0].is_ascii_alphanumeric()
        || !slot
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'.' | b'_' | b'-'))
    {
        return Err("invalid HTTP profile credential slot".to_string());
    }
    Ok(())
}

pub fn http_profile_account(name: &str, slot: &str) -> Result<String, String> {
    validate_mcp_secret_alias(name)?;
    validate_http_profile_secret_slot(slot)?;
    Ok(format!("{HTTP_PROFILE_ACCOUNT_PREFIX}{name}.{slot}"))
}

pub fn http_profile_reference(name: &str, slot: &str) -> Result<String, String> {
    validate_mcp_secret_alias(name)?;
    validate_http_profile_secret_slot(slot)?;
    Ok(format!("secret://os-keyring/http/{name}/{slot}"))
}

pub fn sql_profile_account(name: &str) -> Result<String, String> {
    validate_mcp_secret_alias(name)?;
    Ok(format!("{SQL_PROFILE_ACCOUNT_PREFIX}{name}.password"))
}

pub fn sql_profile_reference(name: &str) -> Result<String, String> {
    validate_mcp_secret_alias(name)?;
    Ok(format!("secret://os-keyring/sql/{name}/password"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_accounts_are_fixed_and_unknown_values_are_rejected() {
        assert_eq!(provider_account("openai").unwrap(), OPENAI_API_KEY_ACCOUNT);
        assert_eq!(provider_account("claude").unwrap(), CLAUDE_API_KEY_ACCOUNT);
        assert!(provider_account("other").is_err());
    }

    #[test]
    fn mcp_aliases_are_bounded_and_cannot_escape_the_reference_namespace() {
        assert_eq!(mcp_account("github-prod").unwrap(), "mcp.github-prod");
        assert_eq!(
            mcp_reference("github-prod").unwrap(),
            "secret://os-keyring/mcp/github-prod"
        );
        for value in ["", "/escape", "two/slashes", "line\nbreak", " white"] {
            assert!(
                mcp_account(value).is_err(),
                "accepted unsafe alias: {value:?}"
            );
        }
    }

    #[test]
    fn http_profile_references_are_bounded_and_namespaced() {
        assert_eq!(
            http_profile_account("weather", "api-key").unwrap(),
            "http.weather.api-key"
        );
        assert_eq!(
            http_profile_reference("weather", "api-key").unwrap(),
            "secret://os-keyring/http/weather/api-key"
        );
        for name in ["", "/x", "a b", "x/y"] {
            assert!(http_profile_account(name, "slot").is_err(), "{name:?}");
            assert!(http_profile_reference(name, "slot").is_err(), "{name:?}");
        }
        for slot in ["", "/x", "a b", "x/y", "line\nbreak"] {
            assert!(http_profile_account("name", slot).is_err(), "{slot:?}");
            assert!(http_profile_reference("name", slot).is_err(), "{slot:?}");
        }
    }

    #[test]
    fn sql_profile_accounts_are_fixed_and_bounded() {
        assert_eq!(
            sql_profile_account("reports").unwrap(),
            "sql.reports.password"
        );
        assert_eq!(
            sql_profile_reference("reports").unwrap(),
            "secret://os-keyring/sql/reports/password"
        );
        for name in ["", "/x", "a b", "x/y", "line\nbreak"] {
            assert!(sql_profile_account(name).is_err(), "{name:?}");
            assert!(sql_profile_reference(name).is_err(), "{name:?}");
        }
    }
}
