use serde::Serialize;
use tauri::{Config, Url};

#[derive(Serialize)]
pub struct UpdateConfiguration {
    pub version: String,
    pub endpoint: Option<String>,
    pub target: String,
}

pub fn update_target(identifier: &str) -> Result<&'static str, String> {
    match identifier {
        "com.personal-assistant.desktop" => Ok("unified-windows-x86_64"),
        "com.personal-assistant.desktop.remote" => Ok("remote-windows-x86_64"),
        _ => Err("此客户端不支持自动更新，请安装正式版客户端".into()),
    }
}

pub fn validate_endpoint(value: &str) -> Result<Url, String> {
    let invalid =
        || "更新地址须为 HTTPS 的 JSON 清单地址，不能包含凭据、查询参数或片段".to_string();
    let value = value.trim();
    if value.len() > 2048 || value.chars().any(char::is_control) {
        return Err(invalid());
    }
    let url = Url::parse(value).map_err(|_| invalid())?;
    if url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || !url.path().ends_with(".json")
    {
        return Err(invalid());
    }
    Ok(url)
}

pub fn validate_release_target(release: &serde_json::Value, target: &str) -> Result<(), String> {
    // 动态清单可绕过插件的目标选择；此项目只接受带明确安装目标的静态清单。
    if release
        .get("platforms")
        .and_then(|value| value.get(target))
        .is_none()
    {
        return Err("更新清单不包含此客户端的安装目标，请核对更新源".into());
    }
    Ok(())
}

pub fn configuration(config: &Config) -> Result<UpdateConfiguration, String> {
    let target = update_target(&config.identifier)?.to_string();
    let endpoint = config
        .plugins
        .0
        .get("updater")
        .and_then(|value| value.get("endpoints"))
        .and_then(|value| value.as_array())
        .and_then(|values| values.first())
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(str::to_owned);
    Ok(UpdateConfiguration {
        version: config
            .version
            .clone()
            .unwrap_or_else(|| env!("CARGO_PKG_VERSION").into()),
        endpoint,
        target,
    })
}

pub fn resolve_endpoints(config: &Config, endpoint: Option<&str>) -> Result<Vec<Url>, String> {
    update_target(&config.identifier)?;
    if let Some(value) = endpoint.filter(|value| !value.trim().is_empty()) {
        return Ok(vec![validate_endpoint(value)?]);
    }
    let values = config
        .plugins
        .0
        .get("updater")
        .and_then(|value| value.get("endpoints"))
        .and_then(|value| value.as_array());
    let endpoints: Vec<Url> = values
        .into_iter()
        .flatten()
        .map(|value| validate_endpoint(value.as_str().ok_or("更新地址配置无效")?))
        .collect::<Result<_, String>>()?;
    if endpoints.is_empty() {
        return Err("未配置更新源，请在关于与更新中填写此客户端的更新清单地址".into());
    }
    Ok(endpoints)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(identifier: &str, endpoints: Vec<&str>) -> Config {
        serde_json::from_value(serde_json::json!({
            "identifier": identifier, "version": "1.0.2",
            "plugins": {"updater": {"endpoints": endpoints}}
        }))
        .unwrap()
    }

    #[test]
    fn empty_build_can_use_an_explicit_source_without_changing_target() {
        let config = config("com.personal-assistant.desktop", vec![]);
        assert!(resolve_endpoints(&config, None)
            .unwrap_err()
            .contains("未配置更新源"));
        let source = "https://updates.example.test/unified/latest.json";
        assert_eq!(
            resolve_endpoints(&config, Some(source)).unwrap()[0].as_str(),
            source
        );
        assert_eq!(
            configuration(&config).unwrap().target,
            "unified-windows-x86_64"
        );
    }

    #[test]
    fn embedded_sources_are_preserved_and_candidates_cannot_switch_channels() {
        let source = "https://updates.example.test/remote/latest.json";
        let remote = config("com.personal-assistant.desktop.remote", vec![source]);
        assert_eq!(
            resolve_endpoints(&remote, None).unwrap()[0].as_str(),
            source
        );
        assert_eq!(
            configuration(&remote).unwrap().target,
            "remote-windows-x86_64"
        );
        let candidate = config("com.personal-assistant.desktop.candidate", vec![]);
        assert!(resolve_endpoints(&candidate, Some(source)).is_err());
    }

    #[test]
    fn invalid_sources_are_rejected_without_echoing_the_input() {
        for value in [
            "",
            "http://updates.example.test/latest.json",
            "https://user:private@example.test/latest.json",
            "https://example.test/latest.json?token=private",
            "https://example.test/latest.json#private",
            "https://example.test/installer.exe",
            "https://exam\nple.test/latest.json",
        ] {
            let error = validate_endpoint(value).unwrap_err();
            assert!(!error.contains("private"));
        }
    }

    #[test]
    fn release_must_explicitly_match_the_client_target() {
        let release = serde_json::json!({"platforms": {"unified-windows-x86_64": {
            "url": "https://updates.example.test/setup.exe", "signature": "fixture"
        }}});
        assert!(validate_release_target(&release, "unified-windows-x86_64").is_ok());
        assert!(validate_release_target(&release, "remote-windows-x86_64").is_err());
        let dynamic = serde_json::json!({"url": "https://updates.example.test/setup.exe", "signature": "fixture"});
        assert!(validate_release_target(&dynamic, "unified-windows-x86_64").is_err());
    }
}
