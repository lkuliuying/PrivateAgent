use zeroize::Zeroizing;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PromptOutcome {
    Stored,
    Cancelled,
}

#[cfg(windows)]
fn wide_z(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
pub fn prompt_and_store(
    account: &str,
    caption: &str,
    message: &str,
) -> Result<PromptOutcome, String> {
    use std::mem::size_of;
    use std::ptr::{null, null_mut};

    use windows_sys::Win32::Foundation::{ERROR_CANCELLED, NO_ERROR};
    use windows_sys::Win32::Security::Credentials::{
        CredUIPromptForCredentialsW, CREDUI_FLAGS_ALWAYS_SHOW_UI, CREDUI_FLAGS_DO_NOT_PERSIST,
        CREDUI_FLAGS_EXCLUDE_CERTIFICATES, CREDUI_FLAGS_GENERIC_CREDENTIALS,
        CREDUI_FLAGS_KEEP_USERNAME, CREDUI_FLAGS_PASSWORD_ONLY_OK, CREDUI_INFOW,
    };

    let target = wide_z(&format!("com.personal-assistant.desktop/{account}"));
    let caption = wide_z(caption);
    let message = wide_z(message);
    let mut username = Zeroizing::new(vec![0_u16; 256]);
    let preset_username = "PrivateAgent\0".encode_utf16().collect::<Vec<_>>();
    username[..preset_username.len()].copy_from_slice(&preset_username);
    let mut password = Zeroizing::new(vec![0_u16; 512]);
    let mut save = 0;

    let info = CREDUI_INFOW {
        cbSize: size_of::<CREDUI_INFOW>() as u32,
        hwndParent: null_mut(),
        pszMessageText: message.as_ptr(),
        pszCaptionText: caption.as_ptr(),
        hbmBanner: null_mut(),
    };
    let flags = CREDUI_FLAGS_GENERIC_CREDENTIALS
        | CREDUI_FLAGS_ALWAYS_SHOW_UI
        | CREDUI_FLAGS_DO_NOT_PERSIST
        | CREDUI_FLAGS_EXCLUDE_CERTIFICATES
        | CREDUI_FLAGS_KEEP_USERNAME
        | CREDUI_FLAGS_PASSWORD_ONLY_OK;

    // The native dialog owns the only interactive plaintext boundary. It does not persist
    // the value itself; successful input is written immediately to the OS credential store.
    let result = unsafe {
        CredUIPromptForCredentialsW(
            &info,
            target.as_ptr(),
            null(),
            NO_ERROR,
            username.as_mut_ptr(),
            username.len() as u32,
            password.as_mut_ptr(),
            password.len() as u32,
            &mut save,
            flags,
        )
    };

    if result == ERROR_CANCELLED {
        return Ok(PromptOutcome::Cancelled);
    }
    if result != NO_ERROR {
        return Err("native credential prompt failed".to_string());
    }

    let password_length = password
        .iter()
        .position(|value| *value == 0)
        .unwrap_or(password.len());
    if password_length == 0 {
        return Err("credential must not be empty".to_string());
    }
    let secret = String::from_utf16(&password[..password_length])
        .map_err(|_| "native credential input was invalid".to_string())?;
    let secret = Zeroizing::new(secret);
    crate::credentials::set(account, secret.as_str())?;
    Ok(PromptOutcome::Stored)
}

#[cfg(not(windows))]
pub fn prompt_and_store(
    _account: &str,
    _caption: &str,
    _message: &str,
) -> Result<PromptOutcome, String> {
    Err("native credential prompt is not available on this platform".to_string())
}
