"""评测子进程只读取选定模型的系统凭据；与桌面 keyring 4 的 Windows 格式一致。"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

from .model_errors import CloudError


def credential_target(alias: str, namespace: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", alias) or namespace not in {"desktop", "candidate"}:
        raise ValueError("评测凭据引用无效")
    service = "com.personal-assistant.desktop" + (".candidate" if namespace == "candidate" else "")
    return f"model-provider.{alias}.api-key.{service}"


def read_model_credential(alias: str, namespace: str) -> str | None:
    target = credential_target(alias, namespace)
    if os.name != "nt" or os.environ.get("PA_EVALUATION_SYNTHETIC_ONLY") or os.environ.get("PYTEST_CURRENT_TEST"):
        raise CloudError(409, "当前环境禁止访问系统凭据；隔离测试必须使用合成凭据替身", code="evaluation_credential_unavailable")
    return _read_windows(target)


def _read_windows(target: str) -> str | None:
    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.c_void_p), ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                    ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    library = ctypes.WinDLL("Advapi32", use_last_error=True)
    pointer = ctypes.POINTER(Credential)()
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    library.CredReadW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    if not library.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise CloudError(409, "无法读取选定测试模型的系统凭据", code="evaluation_credential_unavailable")
    try:
        size, blob = pointer.contents.CredentialBlobSize, pointer.contents.CredentialBlob
        if not blob or not 0 < size <= 32768 or size % 2:
            raise ValueError
        return ctypes.string_at(blob, size).decode("utf-16-le")
    except (ValueError, UnicodeError):
        raise CloudError(409, "选定测试模型凭据格式无效，请在客户端重新保存", code="evaluation_credential_unavailable") from None
    finally:
        if pointer.contents.CredentialBlob and pointer.contents.CredentialBlobSize <= 32768:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        library.CredFree(pointer)
