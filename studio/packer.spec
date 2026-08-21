# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 构建配方：onedir + MERGE，GUI 与 CI CLI 共享一份运行时。

产出单个文件夹 `dghub-sdk-studio/`，含两个启动器：
  - `dgstudio-gui.exe`（windowed，GUI；开始菜单入口）
  - `dgstudio-cli.exe`（console，CI 专用只读构建：`dgstudio-cli build`）
与共享的 `_internal/`（Python 运行时、后端、SDK 数据等只存一份）。

由 `build.py` 调用；版本号经 `src/backend/_version.py`（构建期生成）注入。
"""

from pathlib import Path

ROOT = Path(SPECPATH)                     # studio/
SRC = ROOT / "src"
SDK = ROOT.parent / "sdk" / "python"

# 各层 hidden-import（包结构下仍显式列出以降低漏收风险）
_BACKEND = [
    "backend.project_manager", "backend.compilers", "backend.builder",
    "backend.pipeline", "backend.py_compiler", "backend.packaging",
    "backend.build_control", "backend.logbus", "backend.manifest_validator",
    "backend.settings_store", "backend.winflags", "backend._version",
]
_GUI = [
    "gui.app", "gui.manifest_tab", "gui.compile_tab", "gui.build_tab",
    "gui.settings_tab", "gui.log_tab", "gui.widgets",
]
_CLI = ["cli.cli"]

# SDK 作为数据随包（py_compiler._find_sdk_path 在冻结态读 _MEIPASS/dghub_sdk）
# Font Awesome 图标字体随包（widgets.load_icon_font 冻结态读 _MEIPASS/fontawesome）
_DATAS = [
    (str(SDK / "dghub_sdk"), "dghub_sdk"),
    (str(SRC / "gui" / "assets" / "fontawesome"), "fontawesome"),
]
_PATHEX = [str(SRC), str(SDK)]

a_gui = Analysis(
    [str(SRC / "gui" / "main.py")],
    pathex=_PATHEX,
    binaries=[],
    datas=_DATAS,
    hiddenimports=_BACKEND + _GUI,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

a_cli = Analysis(
    [str(SRC / "cli" / "main.py")],
    pathex=_PATHEX,
    binaries=[],
    datas=_DATAS,
    hiddenimports=_BACKEND + _CLI,
    hookspath=[],
    runtime_hooks=[],
    excludes=["customtkinter"],   # CLI 不引 GUI → 精简、无需 tkinter
    noarchive=False,
)

# 共享公共依赖：后出现的 CLI 引用 GUI 已收集的运行时/后端
MERGE(
    (a_gui, "dgstudio-gui", "dgstudio-gui"),
    (a_cli, "dgstudio-cli", "dgstudio-cli"),
)

pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="dgstudio-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,               # windowed GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

pyz_cli = PYZ(a_cli.pure)
exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="dgstudio-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,                # console CLI，stdout 可见（CI 捕获）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 两个 exe + 两份（经 MERGE 去重后的）依赖收进同一文件夹
coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="dghub-sdk-studio",
)
