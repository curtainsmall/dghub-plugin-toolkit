"""Build DGHub SDK Studio: 源码 → onedir → Inno Setup 安装器（一步到位）。

Usage:
    python build.py [--version X.Y.Z]
    # 或 uv: uv run build.py --version 0.4.0

流程：注入版本 → PyInstaller(packer.spec) 出 onedir → ISCC 编译安装器。
产物：studio/installer/dghub-sdk-studio-setup.exe（onedir bin/ 为中间物）。
前置：本机需装 Inno Setup 6（ISCC 在 PATH 或默认安装目录）。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TAG_PREFIX = "v"

# _version.py 归属后端（GUI 关于页读取），仅构建期生成
_VERSION_PATH = ROOT / "src" / "backend" / "_version.py"
_SPEC = ROOT / "packer.spec"
_ISS = ROOT / "installer.iss"
_ONEDIR = ROOT / "bin" / "dghub-sdk-studio"

_SEMVER_RE = re.compile(
    r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build DGHub SDK Studio installer")
    parser.add_argument(
        "--version", default="", metavar="X.Y.Z",
        help="强制指定构建版本号（SemVer），跳过 git tag 读取",
    )
    return parser.parse_args()


def _get_tag() -> str:
    """CI 触发 tag（CI_VERSION_TAG，精确触发 tag）；本地无此环境变量则返回空串。

    不从本地 git tag 猜版本——发布 tag 打在 main 的合并提交上、且对本地
    dev 构建而言，报一个具体旧版本号（如 0.3.0）反而误导。本地无 --version
    时由 `_resolve_version` 统一落到 "No Version"。
    """
    return os.environ.get("CI_VERSION_TAG", "")


def _resolve_version(override: str = "") -> str:
    """解析版本：--version 优先；否则 CI_VERSION_TAG（去 v 前缀）；本地无参 → "No Version"。"""
    if override:
        return override
    tag = _get_tag()
    if tag:
        return tag[len(TAG_PREFIX):] if tag.startswith(TAG_PREFIX) else tag
    return "No Version"


def _write_version(version: str) -> None:
    """写入版本号到 backend/_version.py（供 GUI/CLI 运行期读取）。"""
    _VERSION_PATH.write_text(
        f'"""Auto-generated version. Do not edit."""\n__version__ = "{version}"\n',
        encoding="utf-8",
    )
    print(f"Version: {version or '(no version)'}")


def _reset_version() -> None:
    """构建结束后删除 _version.py，该文件仅在构建期存在。"""
    _VERSION_PATH.unlink(missing_ok=True)


def _find_iscc() -> str:
    """定位 Inno Setup 6 的 ISCC.exe（PATH 优先，其次默认安装目录）。"""
    found = shutil.which("ISCC")
    if found:
        return found
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            cand = Path(base) / "Inno Setup 6" / "ISCC.exe"
            if cand.is_file():
                return str(cand)
    return ""


def main() -> int:
    args = _parse_args()
    # --version 必须是合法 SemVer（本地无参时不走此路，落 "No Version"）
    if args.version and not _SEMVER_RE.match(args.version):
        print(f"Error: invalid SemVer version: {args.version}")
        return 1
    version = _resolve_version(args.version)
    _write_version(version)
    try:
        rc = _build_onedir()
        if rc != 0:
            return rc
        rc = _build_installer(version)
        if rc != 0:
            return rc
    finally:
        _reset_version()
        _clean(ROOT / "cache")
    print(f"\nDone. Installer: {(_ISS.parent / 'installer' / 'dghub-sdk-studio-setup.exe')}")
    return 0


def _build_onedir() -> int:
    """PyInstaller 按 packer.spec 产出 onedir（bin/dghub-sdk-studio/）。"""
    print("Building onedir bundle with PyInstaller (packer.spec)...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(ROOT / "bin"),
        "--workpath", str(ROOT / "cache" / "build_tmp"),
        str(_SPEC),
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nPyInstaller failed with error code {result.returncode}")
        return result.returncode
    if not _ONEDIR.is_dir():
        print(f"\nError: expected onedir not found: {_ONEDIR}")
        return 1
    print(f"onedir ready: {_ONEDIR}")
    return 0


def _build_installer(version: str) -> int:
    """ISCC 编译 installer.iss → studio/installer/dghub-sdk-studio-setup.exe。"""
    iscc = _find_iscc()
    if not iscc:
        print("\nError: ISCC.exe (Inno Setup 6) not found.")
        print("  Install Inno Setup 6 or ensure ISCC.exe is on PATH.")
        return 1
    print(f"Compiling installer with ISCC: {iscc}")
    cmd = [iscc, f"/DMyVersion={version or '0.0.0'}", str(_ISS)]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print(f"\nISCC failed with error code {result.returncode}")
        return result.returncode
    return 0


def _clean(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        print(f"  Removed directory: {path.name}")
    elif path.is_file():
        path.unlink(missing_ok=True)
        print(f"  Removed file: {path.name}")


if __name__ == "__main__":
    sys.exit(main())
