use base64::{engine::general_purpose::STANDARD, Engine as _};
use minisign_verify::{PublicKey, Signature};
use std::{env, fs, process};

fn fail(message: &str) -> ! {
    eprintln!("[updater-signature] FAILED: {message}");
    process::exit(1);
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 {
        fail("usage: verifier <installer> <installer.sig> <tauri-config-pubkey-file>");
    }

    let installer = fs::read(&args[1]).unwrap_or_else(|_| fail("cannot read installer"));
    let encoded_signature = fs::read_to_string(&args[2])
        .unwrap_or_else(|_| fail("cannot read updater signature"));
    let encoded_public_key = fs::read_to_string(&args[3])
        .unwrap_or_else(|_| fail("cannot read updater public key"));

    // This intentionally mirrors tauri-plugin-updater: both the tauri.conf
    // public key and the .sig payload are base64 wrappers around minisign text.
    let public_key_text = STANDARD
        .decode(encoded_public_key.trim())
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .unwrap_or_else(|| fail("tauri.conf updater public key is not valid base64 UTF-8"));
    let signature_text = STANDARD
        .decode(encoded_signature.trim())
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .unwrap_or_else(|| fail("updater signature is not valid base64 UTF-8"));

    let public_key = PublicKey::decode(&public_key_text)
        .unwrap_or_else(|_| fail("decoded updater public key is invalid"));
    let signature = Signature::decode(&signature_text)
        .unwrap_or_else(|_| fail("decoded updater signature is invalid"));
    public_key
        .verify(&installer, &signature, true)
        .unwrap_or_else(|_| fail("signature does not match installer bytes and embedded public key"));

    println!("[updater-signature] OK: signature matches installer and embedded public key");
}
