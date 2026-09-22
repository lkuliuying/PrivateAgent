//! 仅隔离探针构建使用；保留真实创建结果，单次丢弃指定用例的响应帧。
use crate::readiness_probe::{config, qpc, record};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};

#[derive(Default)]
struct Attempt {
    case: String,
    client_request_id: String,
    selected: bool,
    dropped: bool,
    status: Option<u64>,
    body: String,
    overflow: bool,
}

#[derive(Default)]
struct ProbeTransport {
    attempts: HashMap<String, Attempt>,
    injected: bool,
}

fn identifier(value: &Value) -> Option<&str> {
    value.as_str().filter(|s| {
        !s.is_empty() && s.len() <= 64 && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
    })
}

impl ProbeTransport {
    fn request(
        &mut self,
        id: &str,
        request: &Value,
        probe: &str,
        drop_once: bool,
    ) -> Option<Value> {
        if request["method"] != "POST"
            || request["path"] != "/agent-runs"
            || self.attempts.len() >= 64
        {
            return None;
        }
        let body = request["body"].as_str()?;
        if body.len() > 8192 {
            return None;
        }
        let body: Value = serde_json::from_str(body).ok()?;
        let message = body["message"].as_str()?;
        let case = ["LATENCY", "ACTIVE", "CONFLICT", "LOSS"]
            .into_iter()
            .find(|case| {
                message.split_whitespace().next() == Some(format!("PRE_E_{case}_{probe}").as_str())
            })?;
        let client_request_id = identifier(&body["client_request_id"])?;
        let selected = case == "LOSS"
            && drop_once
            && !self.injected
            && !self.attempts.values().any(|attempt| attempt.selected);
        self.attempts.insert(
            id.into(),
            Attempt {
                case: case.into(),
                client_request_id: client_request_id.into(),
                selected,
                ..Attempt::default()
            },
        );
        Some(
            json!({"event": "create_request", "qpc": qpc(), "ipc_request_id": id,
            "client_request_id": client_request_id, "case": case, "selected_for_loss": selected}),
        )
    }

    fn response(&mut self, frame: &Value) -> (bool, Option<Value>) {
        let Some(id) = frame["id"].as_str() else {
            return (false, None);
        };
        let Some(attempt) = self.attempts.get_mut(id) else {
            return (false, None);
        };
        if let Some(status) = frame["status"].as_u64() {
            attempt.status = Some(status);
            if attempt.selected && (200..300).contains(&status) {
                attempt.dropped = true;
                self.injected = true;
            }
        }
        if let Some(data) = frame["data"].as_str() {
            if !attempt.overflow && attempt.body.len() + data.len() <= 65536 {
                attempt.body.push_str(data);
            } else {
                attempt.overflow = true;
                attempt.body.clear();
            }
        }
        let dropped = attempt.dropped;
        if frame["done"] == true || frame.get("error").is_some() {
            let attempt = self.attempts.remove(id).unwrap();
            let body = serde_json::from_str::<Value>(&attempt.body).unwrap_or(Value::Null);
            return (
                dropped,
                Some(
                    json!({"event": "create_response", "qpc": qpc(), "ipc_request_id": id,
                "client_request_id": attempt.client_request_id, "case": attempt.case, "status": attempt.status,
                "run_id": identifier(&body["id"]), "dropped": dropped, "body_overflow": attempt.overflow,
                "transport_error": frame.get("error").is_some()}),
                ),
            );
        }
        (dropped, None)
    }
}

static TRANSPORT: OnceLock<Mutex<ProbeTransport>> = OnceLock::new();

pub fn request(id: &str, request: &Value) {
    let Some(config) = config() else {
        return;
    };
    if let Ok(mut state) = TRANSPORT.get_or_init(Default::default).lock() {
        if let Some(event) = state.request(
            id,
            request,
            &config.probe_id,
            config.drop_create_response_once,
        ) {
            record(event);
        }
    }
}

pub fn drop_frame(frame: &Value) -> bool {
    let Some(state) = TRANSPORT.get() else {
        return false;
    };
    let Ok(mut state) = state.lock() else {
        return false;
    };
    let (drop, event) = state.response(frame);
    if let Some(event) = event {
        record(event);
    }
    drop
}

pub fn cancel(id: &str) {
    if let Some(state) = TRANSPORT.get() {
        if let Ok(mut state) = state.lock() {
            let remaining = state.attempts.remove(id).is_some();
            record(
                json!({"event": "transport_cancel", "ipc_request_id": id, "qpc": qpc(), "pending_attempt": remaining}),
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn create(case: &str, key: &str) -> Value {
        json!({"method": "POST", "path": "/agent-runs", "headers": {"authorization": "never-log"},
            "body": json!({"message": format!("PRE_E_{case}_12345678 合成用例"), "client_request_id": key}).to_string()})
    }
    #[test]
    fn accepted_loss_drops_all_frames_and_explicit_retry_keeps_original_identity() {
        let mut state = ProbeTransport::default();
        let request = create("LOSS", "client-1");
        assert!(
            state.request("ipc-1", &request, "12345678", true).unwrap()["selected_for_loss"]
                == true
        );
        assert!(state.response(&json!({"id":"ipc-1","status":200})).0);
        assert!(
            state
                .response(&json!({"id":"ipc-1","data":"{\"id\":\"run-1\""}))
                .0
        );
        assert!(state.response(&json!({"id":"ipc-1","data":"}"})).0);
        let (dropped, event) = state.response(&json!({"id":"ipc-1","done":true}));
        assert!(dropped);
        assert_eq!(event.unwrap()["run_id"], "run-1");
        assert!(
            state.request("ipc-2", &request, "12345678", true).unwrap()["selected_for_loss"]
                == false
        );
        assert!(!state.response(&json!({"id":"ipc-2","status":200})).0);
        assert!(
            !state
                .response(&json!({"id":"ipc-2","data":"{\"id\":\"run-1\"}","done":true}))
                .0
        );
        assert!(state.attempts.is_empty());
    }
    #[test]
    fn rejection_and_unrelated_calls_are_not_dropped_or_logged_as_success() {
        let mut state = ProbeTransport::default();
        assert!(state
            .request("a", &create("LOSS", "key"), "87654321", true)
            .is_none());
        let request = create("LOSS", "key");
        state.request("b", &request, "12345678", true);
        assert!(!state.response(&json!({"id":"b","status":422})).0);
        let (_, row) =
            state.response(&json!({"id":"b","data":"{\"detail\":\"private\"}","done":true}));
        assert_eq!(row.as_ref().unwrap()["run_id"], Value::Null);
        assert!(!row.unwrap().to_string().contains("private"));
        assert!(
            state.request("c", &request, "12345678", true).unwrap()["selected_for_loss"] == true
        );
        assert!(!state.response(&json!({"id":"other","status":200})).0);
    }
    #[test]
    fn disabled_loss_and_bounded_invalid_body_never_produce_false_identity() {
        let mut state = ProbeTransport::default();
        let row = state
            .request("a", &create("LOSS", "key"), "12345678", false)
            .unwrap();
        assert!(!row.to_string().contains("never-log"));
        assert!(!state.response(&json!({"id":"a","status":200})).0);
        state.response(&json!({"id":"a","data":"x".repeat(65537)}));
        let (_, row) = state.response(&json!({"id":"a","done":true}));
        let row = row.unwrap();
        assert_eq!(row["body_overflow"], true);
        assert_eq!(row["run_id"], Value::Null);
    }
}
