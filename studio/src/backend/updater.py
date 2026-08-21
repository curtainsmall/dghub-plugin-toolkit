"""应用内更新：版本检测、安装器下载、检查节流（纯逻辑，无 GUI 依赖）。

数据源为 GitHub Releases API（/releases/latest，自动排除 pre-release）。
节流与跳过状态存于全局 state.json（复用 settings_store）。
"""

import json
import re
import tempfile
import urllib.request
from pathlib import Path

from backend import settings_store

GITHUB_REPO = "curtainsmall/dghub-sdk-toolkit"
ASSET_NAME = "dghub-sdk-studio-setup.exe"
_CHUNK = 128 * 1024  # 进度回调粒度：每 128KB 一次


class DownloadCancelled(Exception):
    """下载被用户取消（is_cancelled 回调返回 True 时抛出）。"""


def get_current_version() -> str:
    """读取构建期注入的版本号；开发模式返回 "dev"。"""
    try:
        from backend._version import __version__ as version  # type: ignore[reportMissingImports]
        return version
    except ImportError:
        return "dev"


def _parse_semver(v: str) -> tuple[int, ...] | None:
    """解析三段式 SemVer 前缀；无法解析返回 None。"""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_newer(latest: str, current: str) -> bool:
    """latest > current（三段式比较，如 0.6.9 < 0.6.10 < 0.7.0）。"""
    l, c = _parse_semver(latest), _parse_semver(current)
    if l is None or c is None:
        return False
    return l > c


def check_latest(timeout: float = 15.0) -> tuple[str | None, str | None, int]:
    """查询 GitHub 最新正式版。

    Returns:
        (version, download_url, file_size_bytes)。
        - 网络/API 失败（超时、release 不存在）→ ``(None, None, 0)``
        - 找到版本但附件名不匹配 ``ASSET_NAME``（如旧版 updater 查
          新安装器名）→ ``(version, None, 0)``——调用方应提示手动
          下载，而非误报网络错误

    优先走 Releases API；API 限速（403）时降级为跟随 releases/latest
    网页重定向提取版本号（size 未知返回 0，下载 URL 按固定格式构造）。
    """
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "dghub-sdk-studio-updater",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        if not version:
            return None, None, 0
        for asset in data.get("assets", []):
            if asset.get("name") == ASSET_NAME:
                return version, asset.get("browser_download_url"), \
                    int(asset.get("size") or 0)
        return version, None, 0
    except Exception:
        pass
    # API 失败（如限速）→ 降级：跟随 releases/latest 重定向取最新 tag
    try:
        req = urllib.request.Request(
            f"https://github.com/{GITHUB_REPO}/releases/latest",
            headers={"User-Agent": "dghub-sdk-studio-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = resp.geturl()
        tag = final.rstrip("/").rsplit("/", 1)[-1]
        version = tag[1:] if tag.startswith("v") else tag
        if not version:
            return None, None, 0
        url = (f"https://github.com/{GITHUB_REPO}/releases/download/"
               f"{tag}/{ASSET_NAME}")
        return version, url, 0
    except Exception:
        return None, None, 0


def update_dest(version: str) -> Path:
    """下载目标路径：临时目录下按版本命名（重试时覆盖）。"""
    return Path(tempfile.gettempdir()) / "dghub-studio-update" / \
        f"setup-{version}.exe"


def cleanup_stale_installers(keep_version: str) -> None:
    """删除临时目录中其他版本的 installer，仅保留当前版本。"""
    d = Path(tempfile.gettempdir()) / "dghub-studio-update"
    if not d.is_dir():
        return
    keep = f"setup-{keep_version}.exe"
    for p in d.glob("setup-*.exe"):
        if p.name != keep:
            try:
                p.unlink()
            except Exception:
                pass


def download_installer(url: str, dest: Path, on_progress=None,
                       is_cancelled=None) -> bool:
    """阻塞式下载 installer 到 dest。

    Args:
        url: 安装器下载地址（browser_download_url）。
        dest: 目标文件路径。
        on_progress: 每 128KB 回调 ``on_progress(downloaded, total)``。
        is_cancelled: 无参回调，返回 True 时取消下载（抛 DownloadCancelled）。

    Returns:
        True 下载完整；失败返回 False 并清理部分文件。
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            written = 0
            with dest.open("wb") as f:
                while True:
                    if is_cancelled and is_cancelled():
                        raise DownloadCancelled()
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        on_progress(written, total)
        return True
    except DownloadCancelled:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        return False


def should_notify(latest: str, current: str) -> bool:
    """是否应弹窗提示：latest > current，且无已设置版本或 latest 更新。

    「已设置版本」= 用户点过「忽略此版本」的记录：只屏蔽该版本，
    更新的版本出现时重新提示。
    """
    if not is_newer(latest, current):
        return False
    skipped = get_skipped_version()
    if not skipped:
        return True
    return is_newer(latest, skipped)


def get_skipped_version() -> str:
    """用户跳过的版本号（空串 = 未跳过）。"""
    skipped = settings_store.get_state("skipped_update", "")
    return skipped if isinstance(skipped, str) else ""


def skip_version(version: str) -> None:
    """记录跳过某版本：该版本不再自动弹窗提醒。"""
    settings_store.save_state_key("skipped_update", version)
