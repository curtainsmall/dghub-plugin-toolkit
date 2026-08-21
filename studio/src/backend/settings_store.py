"""全局用户级设置：`~/.dghub-sdk-studio/state.json`（跨项目、每用户）。

存放与具体插件项目无关的状态：上次打开的插件目录、PyPI 镜像源等。
GUI 设置页与 CLI（如 `--pypi-index` 默认值）共用此模块，避免各自读写分叉。
纯逻辑、无 GUI 依赖。

旧版（DGHub SDK Packer，`~/.dghub-sdk-packer`）配置的迁移由安装器完成
（installer.iss 安装时复制 state.json 并可选清理旧目录），本模块不感知。
"""

import json
from pathlib import Path
from typing import Any

_STATE_DIR = Path.home() / ".dghub-sdk-studio"
_STATE_FILE = _STATE_DIR / "state.json"


def config_dir() -> Path:
    """全局配置目录（state.json 所在；GUI 设置页「打开配置目录」用）。"""
    return _STATE_DIR


def read_state() -> dict:
    """读取全局状态文件（不存在或损坏返回空 dict）。"""
    try:
        if _STATE_FILE.is_file():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def get_state(key: str, default: Any = "") -> Any:
    """读取全局状态的单个键。"""
    return read_state().get(key, default)


def save_state_key(key: str, value: Any) -> None:
    """读-改-写更新全局状态文件的单个键（不覆盖其他键）。"""
    try:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        state = read_state()
        state[key] = value
        _STATE_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass
