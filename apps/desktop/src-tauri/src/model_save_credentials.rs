//! 只向固定的配置暂存接口注入系统凭据，密钥不返回 WebView。
use serde::Serialize;
use serde_json::Value;
use zeroize::Zeroizing;

pub(crate) fn hydrate_request(request: &mut Value) -> Result<(), String> {
    hydrate_with(request, |alias| {
        crate::check_draft_store_access()?;
        if !crate::read_model_provider_secret_status(alias)?.configured {
            return Err("待保存配置尚无系统凭据，请回到模型设置输入密钥".into());
        }
        crate::credentials::get(&crate::model_provider_account(alias)?)?
            .ok_or_else(|| "已保存凭据无法读取，请重新输入密钥".into())
    })
}

fn hydrate_with<F>(request: &mut Value, read: F) -> Result<(), String>
where F: FnOnce(&str) -> Result<String, String> {
    let Some(body) = request.get("body").and_then(Value::as_str) else { return Ok(()) };
    if body.len() > 4096 { return Ok(()) }
    let Ok(input) = serde_json::from_str::<Value>(body) else { return Ok(()) };
    let Some(alias) = input.get("stored_alias").and_then(Value::as_str) else { return Ok(()) };
    let parts: Vec<_> = request.get("path").and_then(Value::as_str).unwrap_or("").split('/').collect();
    if request.get("method").and_then(Value::as_str) != Some("PUT") || parts.len() != 4
        || parts[0] != "" || parts[1] != "model-save-operations" || parts[3] != "credential"
        || parts[2].len() != 32 || !parts[2].bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || alias.len() != 64 || !alias.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        || input.as_object().map(|object| object.len()) != Some(1) {
        return Err("凭据恢复请求的范围无效".into());
    }
    let secret = Zeroizing::new(read(alias)?);
    #[derive(Serialize)]
    struct Credential<'a> { alias: &'a str, secret: &'a str }
    request["body"] = Value::String(serde_json::to_string(&Credential { alias, secret: secret.as_str() })
        .map_err(|_| "凭据恢复请求格式无效")?);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn only_the_fixed_staging_route_receives_credentials() {
        let mut request = json!({"path": format!("/model-save-operations/{}/credential", "a".repeat(32)), "method": "PUT",
            "body": json!({"stored_alias": "b".repeat(64)}).to_string()});
        hydrate_with(&mut request, |_| Ok("synthetic-vault-value".into())).unwrap();
        let body: Value = serde_json::from_str(request["body"].as_str().unwrap()).unwrap();
        assert_eq!(body["secret"], "synthetic-vault-value");
        assert!(body.get("stored_alias").is_none());
    }
    #[test]
    fn invalid_targets_never_read_the_vault() {
        for path in ["/agent-runs", "https://untrusted.test/credential", "/model-save-operations/../credential", "/model-save-operations/aaaa/credential?x=1"] {
            let mut request = json!({"path": path, "method": "PUT", "body": json!({"stored_alias": "b".repeat(64)}).to_string()});
            assert!(hydrate_with(&mut request, |_| panic!("错误路径不应读取凭据")).is_err());
        }
    }
}
