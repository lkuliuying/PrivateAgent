; PrivateAgent NSIS lifecycle hooks.
; The PyInstaller onefile sidecar has a bootloader/worker process pair. Killing
; only the Tauri process can leave the worker holding personal-assistant-server.exe,
; so the default NSIS Delete silently fails. Stop every matching current-user
; sidecar and confirm the process is gone before files are copied or removed.

!macro PA_STOP_SIDECAR
  !define PA_HOOK_ID ${__LINE__}
  StrCpy $R8 20

  pa_sidecar_stop_${PA_HOOK_ID}:
    nsis_tauri_utils::FindProcessCurrentUser "personal-assistant-server.exe"
    Pop $R0
    ${If} $R0 != 0
      Goto pa_sidecar_stopped_${PA_HOOK_ID}
    ${EndIf}

    nsis_tauri_utils::KillProcessCurrentUser "personal-assistant-server.exe"
    Pop $R0
    Sleep 250
    IntOp $R8 $R8 - 1
    ${If} $R8 > 0
      Goto pa_sidecar_stop_${PA_HOOK_ID}
    ${EndIf}

    IfSilent pa_sidecar_abort_${PA_HOOK_ID} 0
    MessageBox MB_ICONSTOP|MB_OK "PrivateAgent local service is still running. Please close it and try again.$\r$\n$\r$\nPrivateAgent 本地服务仍在运行，请结束该进程后重试。"
    pa_sidecar_abort_${PA_HOOK_ID}:
      Abort

  pa_sidecar_stopped_${PA_HOOK_ID}:
  !undef PA_HOOK_ID
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro PA_STOP_SIDECAR
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro PA_STOP_SIDECAR
!macroend
