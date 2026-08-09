"""Build DGHub SDK wheel/sdist from git tag.

Usage:
    python build_sdk.py [--version X.Y.Z]
    # CI 会自动传入 CI_VERSION_TAG 环境变量

构建流程：
  1. 读取 v* tag 提取版本号（或用 --version 强制指定）
  2. 替换 pyproject.toml 中的占位版本
  3. python -m build 生成 wheel + sdist
  4. 恢复 pyproject.toml 占位版本
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"
TAG_PREFIX = "v"

_SEMVER_RE = re.compile(
    r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build SDK wheel/sdist")
    parser.add_argument(
        "--version", default="", metavar="X.Y.Z",
        help="强制指定构建版本号（SemVer），跳过 git tag 读取",
    )
    return parser.parse_args()


def _get_tag() -> str:
    """获取当前版本 tag。

    CI 环境优先读 CI_VERSION_TAG（精确触发 tag），
    本地回退到 git describe --match "v*"。
    """
    ci_tag = os.environ.get("CI_VERSION_TAG", "")
    if ci_tag:
        return ci_tag
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--match", f"{TAG_PREFIX}*",
             "--abbrev=0"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _patch_version(version: str) -> None:
    """将 pyproject.toml 中 version = "0.0.0" 替换为真实版本。"""
    content = PYPROJECT.read_text(encoding="utf-8")
    content = re.sub(
        r'^version = "0\.0\.0"',
        f'version = "{version}"',
        content, count=1, flags=re.MULTILINE,
    )
    PYPROJECT.write_text(content, encoding="utf-8")
    print(f"  Patched pyproject.toml -> version = {version}")


def _to_pep440(version: str) -> str:
    """将 semver pre-release 后缀转为 PEP 440 格式。"""
    if "-" not in version:
        return version
    base, rest = version.split("-", 1)
    if rest.startswith("alpha"):
        return f"{base}a{rest[len('alpha'):].lstrip('.')}"
    if rest.startswith("beta"):
        return f"{base}b{rest[len('beta'):].lstrip('.')}"
    if rest.startswith("rc"):
        return f"{base}rc{rest[len('rc'):].lstrip('.')}"
    if rest.startswith("dev"):
        return f"{base}.dev{rest[len('dev'):].lstrip('.')}"
    return version  # unknown pattern, leave as-is


def _restore_version() -> None:
    """构建后恢复 pyproject.toml 为占位版本。"""
    content = PYPROJECT.read_text(encoding="utf-8")
    content = re.sub(
        r'^version = "[^"]+"',
        'version = "0.0.0"',
        content, count=1, flags=re.MULTILINE,
    )
    PYPROJECT.write_text(content, encoding="utf-8")
    print("  Restored pyproject.toml -> version = 0.0.0")


def _build() -> int:
    print("Building SDK wheel & sdist...")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(ROOT / "dist")],
        cwd=ROOT,
    )
    return result.returncode


def _clean_egg_info() -> None:
    """清理构建产生的 egg-info 目录（可再生的元数据缓存）。"""
    import shutil
    for p in ROOT.glob("*.egg-info"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            print(f"  Removed directory: {p.name}")


def main() -> int:
    args = _parse_args()
    if args.version:
        if not _SEMVER_RE.match(args.version):
            print(f"Error: invalid SemVer version: {args.version}")
            return 1
        version = args.version
    else:
        tag = _get_tag()
        if tag.startswith(TAG_PREFIX):
            version = tag[len(TAG_PREFIX):]
        else:
            version = "0.0.0-dev"
            print(f"Warning: no {TAG_PREFIX}* tag found, using {version}")

    version = _to_pep440(version)
    print(f"SDK Version: {version}")
    _patch_version(version)
    try:
        ret = _build()
    finally:
        _restore_version()
        _clean_egg_info()

    if ret == 0:
        print()
        print("Success! SDK package created in sdk/python/dist/")
        print()
    return ret


if __name__ == "__main__":
    sys.exit(main())
