use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use std::{env, fs, process};

fn fail(message: &str) -> ! {
    eprintln!("[updater-signature] FAILED: {message}");
    process::exit(1);
}

fn verify_installer(
    installer: &[u8],
    encoded_signature: &str,
    encoded_public_key: &str,
) -> Result<(), &'static str> {
    // 与 tauri-plugin-updater 保持一致：配置公钥和 .sig 均为 minisign 文本的 base64 包装。
    let public_key_text = STANDARD
        .decode(encoded_public_key.trim())
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .ok_or("tauri.conf updater public key is not valid base64 UTF-8")?;
    let signature_text = STANDARD
        .decode(encoded_signature.trim())
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .ok_or("updater signature is not valid base64 UTF-8")?;

    let public_key =
        PublicKey::decode(&public_key_text).map_err(|_| "decoded updater public key is invalid")?;
    let signature =
        Signature::decode(&signature_text).map_err(|_| "decoded updater signature is invalid")?;
    public_key
        .verify(installer, &signature, true)
        .map_err(|_| "signature does not match installer bytes and embedded public key")
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        fail("usage: verifier <installer> <installer.sig> <tauri-config-pubkey-file>");
    }

    let installer = fs::read(&args[1]).unwrap_or_else(|_| fail("cannot read installer"));
    let encoded_signature =
        fs::read_to_string(&args[2]).unwrap_or_else(|_| fail("cannot read updater signature"));
    let encoded_public_key =
        fs::read_to_string(&args[3]).unwrap_or_else(|_| fail("cannot read updater public key"));
    verify_installer(&installer, &encoded_signature, &encoded_public_key)
        .unwrap_or_else(|message| fail(message));

    println!("[updater-signature] OK: signature matches installer and embedded public key");
}

#[cfg(test)]
mod tests {
    use super::*;

    // 公开向量来自 minisign-verify 0.2.5 的 src/lib.rs 文档；仅签署 b"test"，不代表发布安装器。
    const PUBLIC_KEY: &str = "untrusted comment: minisign public key E7620F1842B4E81F\n\
RWQf6LRCGA9i53mlYecO4IzT51TGPpvWucNSCh1CBM0QTaLn73Y7GFO3\n";
    const SIGNATURE: &str = "untrusted comment: signature from minisign secret key\n\
RUQf6LRCGA9i559r3g7V1qNyJDApGip8MfqcadIgT9CuhV3EMhHoN1mGTkUidF/\
z7SrlQgXdy8ofjb7bNJJylDOocrCo8KLzZwo=\n\
trusted comment: timestamp:1633700835\tfile:test\tprehashed\n\
wLMDjy9FLAuxZ3q4NlEvkgtyhrr0gtTu6KC4KBJdITbbOeAi1zBIYo0v4iTgt8jJpIidRJnp94ABQkJAgAooBQ==\n";
    // 仓库正式客户端的公开公钥，用于验证不同签名密钥不会被误接受。
    const OTHER_PUBLIC_KEY: &str = "untrusted comment: minisign public key: 5E15775F7276641F\n\
RWQfZHZyX3cVXhcwCA/u58QxKL5yuv7s0JqbQ8C7HSmtxhaLbK15Xn+a\n";

    #[test]
    fn accepts_public_vector_with_tauri_base64_wrappers() {
        let signature = format!(" {}\r\n", STANDARD.encode(SIGNATURE));
        let public_key = format!("\n{}\n", STANDARD.encode(PUBLIC_KEY));
        assert_eq!(verify_installer(b"test", &signature, &public_key), Ok(()));
    }

    #[test]
    fn rejects_changed_installer_bytes() {
        assert_eq!(
            verify_installer(
                b"Test",
                &STANDARD.encode(SIGNATURE),
                &STANDARD.encode(PUBLIC_KEY)
            ),
            Err("signature does not match installer bytes and embedded public key")
        );
    }

    #[test]
    fn rejects_valid_signature_from_another_public_key() {
        assert_eq!(
            verify_installer(
                b"test",
                &STANDARD.encode(SIGNATURE),
                &STANDARD.encode(OTHER_PUBLIC_KEY)
            ),
            Err("signature does not match installer bytes and embedded public key")
        );
    }

    #[test]
    fn rejects_invalid_base64_and_non_utf8_wrappers() {
        for invalid in ["not-base64!".to_owned(), STANDARD.encode([0xff])] {
            assert_eq!(
                verify_installer(b"test", &invalid, &STANDARD.encode(PUBLIC_KEY)),
                Err("updater signature is not valid base64 UTF-8")
            );
            assert_eq!(
                verify_installer(b"test", &STANDARD.encode(SIGNATURE), &invalid),
                Err("tauri.conf updater public key is not valid base64 UTF-8")
            );
        }
    }

    #[test]
    fn rejects_empty_signature() {
        assert_eq!(
            verify_installer(b"test", " \r\n", &STANDARD.encode(PUBLIC_KEY)),
            Err("decoded updater signature is invalid")
        );
    }

    #[test]
    fn rejects_invalid_minisign_text_inside_valid_base64() {
        let invalid = STANDARD.encode("not a minisign document");
        assert_eq!(
            verify_installer(b"test", &invalid, &STANDARD.encode(PUBLIC_KEY)),
            Err("decoded updater signature is invalid")
        );
        assert_eq!(
            verify_installer(b"test", &STANDARD.encode(SIGNATURE), &invalid),
            Err("decoded updater public key is invalid")
        );
    }
}
