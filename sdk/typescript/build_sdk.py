"""Build DGHub TypeScript SDK package from git tag.

Usage:
    python build_sdk.py [--version X.Y.Z]
    # CI 会自动传入 CI_VERSION_TAG 环境变量

构建流程（与 sdk/python/build_sdk.py 对齐）：
  1. 读取 v* tag 提取版本号（或用 --version 强制指定）
  2. 注入 package.json version（构建后恢复原值）
  3. npm run build（tsc 编译 src → dist）
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE_JSON = ROOT / "package.json"
TAG_PREFIX = "v"

_SEMVER_RE = re.compile(
    r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build TS SDK package")
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


def _get_version() -> str:
    """读取 package.json 当前 version。"""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    return data.get("version", "")


def _set_version(version: str) -> None:
    """写入 package.json version。"""
    data = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    data["version"] = version
    PACKAGE_JSON.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  Patched package.json -> version = {version}")


def _build() -> int:
    print("Building TS SDK (tsc)...")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    return subprocess.run([npm, "run", "build"], cwd=ROOT).returncode


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

    original = _get_version()
    print(f"SDK Version: {version}")
    _set_version(version)
    try:
        ret = _build()
    finally:
        # CI 发布用：保留注入版本（artifact 带正确版本号）；本地默认恢复
        if not os.environ.get("KEEP_VERSION"):
            _set_version(original)

    if ret == 0:
        print()
        print("Success! TS SDK package ready in sdk/typescript/dist/")
        print()
    return ret


if __name__ == "__main__":
    sys.exit(main())
