"""Regression coverage for the project-owned Tauri NSIS template."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAURI_DIR = ROOT / "apps" / "desktop" / "src-tauri"
TEMPLATE = TAURI_DIR / "nsis" / "installer-template.nsi"


def test_tauri_config_uses_project_nsis_template() -> None:
    config = json.loads((TAURI_DIR / "tauri.conf.json").read_text(encoding="utf-8"))
    nsis = config["bundle"]["windows"]["nsis"]

    assert nsis["template"] == "nsis/installer-template.nsi"
    assert nsis["installerHooks"] == "nsis/installer-hooks.nsh"


def test_reinstall_page_ignores_stale_uninstaller_metadata() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert 'ReadRegStr $4 SHCTX "${MANUPRODUCTKEY}" ""' in template
    assert '${IfNot} ${FileExists} "$4\\uninstall.exe"' in template
    assert "repairable stale record" in template


def test_completed_uninstall_wins_over_nonzero_exit_code() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    stale_check = template.index("Prefer the resulting filesystem state")
    generic_error = template.index('MessageBox MB_ICONEXCLAMATION "$(unableToUninstall)"')
    checked_region = template[stale_check:generic_error]

    assert '${FileExists} "$4\\uninstall.exe"' in checked_region
    assert '${FileExists} "$4\\${MAINBINARYNAME}.exe"' in checked_region
    assert "StrCpy $0 0" in checked_region


def test_template_preserves_user_data_by_default() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "${If} $DeleteAppDataCheckboxState = 1" in template
    assert 'RmDir /r "$APPDATA\\${BUNDLEID}"' in template
    assert 'RmDir /r "$LOCALAPPDATA\\${BUNDLEID}"' in template
