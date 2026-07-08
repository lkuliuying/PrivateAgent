# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller ONEDIR 打包配置（第五阶段 M5 评估用，非默认打包路径）。

与 ``personal_assistant.spec``（onefile）的区别：产物是一个**目录**而非单文件，
启动时无需解压到 ``_MEIPASS``，首启更快；代价是分发变成一个文件夹。

产物：``dist/personal-assistant-server/personal-assistant-server.exe`` + 依赖目录。

⚠️ Tauri 集成注意事项（评估阶段，尚未切换为默认）：
- Tauri ``externalBin`` 要求**单个**二进制（``<name>-<target-triple>.exe``），
  与 onedir 目录产物不兼容。onefile 仍通过 ``externalBin`` 直接作为 sidecar。
- 若要启用 onedir，需改用 Tauri ``resources`` 打包整个目录，并在 ``lib.rs`` 中
  用 ``app.path().resource_dir()`` 解析目录、用 ``tauri_plugin_shell::process::Command``
  指向目录内的 ``personal-assistant-server.exe`` 启动（而非 ``app.shell().sidecar()``）。
  这需要改动 ``lib.rs`` 的 ``start_sidecar`` 路径逻辑，**当前未实现**。
- 评估流程：用本 spec 构建 -> 用 ``scripts/measure_sidecar_baseline.py --startup``
  对比 onefile/onedir 体积与首启耗时 -> 仅当 smoke 全通过且收益明显才切换默认。

用法（项目根，评估时手动指定 spec）：
    uv run pyinstaller personal_assistant_onedir.spec --noconfirm
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ---- hidden imports（与 onefile spec 一致）----
hiddenimports = []
hiddenimports += collect_submodules("personal_assistant")
hiddenimports += collect_submodules("chromadb")
hiddenimports += ["aiomysql", "pymysql"]
# cryptography: MySQL 8 默认 caching_sha2_password 认证需要；aiomysql 动态 import，
# PyInstaller 静态分析看不到，必须显式声明（见 onefile spec 同名注释）。
hiddenimports += ["cryptography"]
hiddenimports += collect_submodules("langchain")
hiddenimports += collect_submodules("langchain_ollama")
hiddenimports += collect_submodules("langchain_chroma")
hiddenimports += collect_submodules("langgraph")

try:
    hiddenimports += collect_submodules("onnxruntime")
except Exception:
    pass

# ---- 数据文件（与 onefile spec 一致）----
datas = []
datas += collect_data_files("chromadb")
try:
    datas += collect_data_files("onnxruntime")
except Exception:
    pass
datas += [("alembic.ini", ".")]
datas += [("alembic", "alembic")]

a = Analysis(
    ["src/personal_assistant/server_entry.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
)

pyz = PYZ(a.pure)

# onedir：EXE 仅含脚本与 pyz，二进制/数据交给 COLLECT 放到目录里。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="personal-assistant-server",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="personal-assistant-server",
)
