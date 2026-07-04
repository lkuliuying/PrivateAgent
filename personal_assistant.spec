# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 personal_assistant 后端打成单可执行 sidecar（M4 打包预研）。

用法（项目根执行）：
    uv run pyinstaller personal_assistant.spec --noconfirm

产物：dist/personal-assistant-server.exe
随后由 scripts/build-sidecar.bat 复制到
apps/desktop/src-tauri/binaries/personal-assistant-server-x86_64-pc-windows-msvc.exe

模式：onefile（单文件自包含）。Tauri externalBin 要求单个二进制文件。
代价：启动时解压到临时 _MEIPASS，首次启动略慢（sidecar 全生命周期只启动一次，可接受）。
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ---- hidden Imports：chromadb / onnxruntime / langchain 生态常缺子模块 ----
hiddenimports = []
# personal_assistant 包：uvicorn.run("personal_assistant.main_api:app") 是字符串引用，
# PyInstaller 静态分析看不到，必须显式收集全部子模块。
hiddenimports += collect_submodules("personal_assistant")
hiddenimports += collect_submodules("chromadb")
hiddenimports += ["aiomysql", "pymysql"]
hiddenimports += collect_submodules("langchain")
hiddenimports += collect_submodules("langchain_ollama")
hiddenimports += collect_submodules("langchain_chroma")
hiddenimports += collect_submodules("langgraph")

# onnxruntime 是 chromadb 默认 embedding 的依赖；即便我们用 Ollama embedding，
# import chromadb 仍可能引用，打包进来避免运行时 ImportError。
try:
    hiddenimports += collect_submodules("onnxruntime")
except Exception:
    pass

# ---- 数据文件 ----
datas = []
datas += collect_data_files("chromadb")
try:
    datas += collect_data_files("onnxruntime")
except Exception:
    pass
# Alembic 迁移脚本 + ini（server_entry.py 启动时进程内 upgrade head）
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="personal-assistant-server",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
