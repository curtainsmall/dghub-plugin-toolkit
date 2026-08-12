""".dghub-sdk/ project configuration management.

project.json 为唯一配置文件（compiler 节 + builder 节）::

    {
      "compiler": {
        "compile_system": "python",  # 编译选择：""（无）/ "python" / "command"
        "compile": "",        # CommandCompiler 设置（compile_system="command" 时必填）
        "compile_dir": "",    # CommandCompiler 执行目录（空 = 项目根）
        "manifest": "",       # PythonCompiler 设置（compile_system="python" 时必填）
        "include_sdk": true   # PythonCompiler 选项：是否打包 dghub-sdk
      },
      "builder": {
        "files": [],              # 统一文件选择列表：[{"path"|"dir"|"pattern", "tags"}]
        "output_dir": ""          # 输出目录（空 = 插件目录/output）
      }
    }

- 路径（manifest / compile_dir / output_dir）存相对插件目录的路径，跨盘符时回退绝对路径
- 未知键在读-改-写时保留，不丢数据
- 编译入口（entry）为 Python 编译专属输入，由 PythonCompiler 从
  pyproject.toml 的 [tool.dghub].entry 现读，不入 project.json
"""

import json
import os
from pathlib import Path
from typing import Any

from backend.logbus import Logger

_MANIFEST_DEFAULTS: dict[str, Any] = {
    "id": "",
    "name": "",
    "version": "",
    "author": "",
    "description": "",
    "sdk": "1",
}

# compiler 节默认值（compile_system 显式单选："" 无 / "python" / "command"）
_COMPILER_DEFAULTS: dict[str, Any] = {
    "compile_system": "",
    "compile": "",
    "compile_dir": "",
    "manifest": "",
    "include_sdk": True,
}

# 顶层默认值（compiler 节为唯一编译配置来源）
_PROJECT_DEFAULTS: dict[str, Any] = {
    "compiler": dict(_COMPILER_DEFAULTS),
}

# builder 节默认值（files = 统一文件选择列表，条目 {path|dir|pattern, tags}）
_BUILDER_DEFAULTS: dict[str, Any] = {
    "files": [],
    "output_dir": "",
}


class ProjectManager:
    """Manages a `.dghub-sdk/` directory inside the plugin source directory.

    Each tab auto-reads/writes on every change.
    No explicit "save" needed — this is transparent persistence.
    """

    def __init__(self, plugin_dir: str,
                 log: Logger | None = None) -> None:
        # resolve：插件目录可能传入 "." 等相对路径，未解析时 .name 为空串，
        # 会导致产物名（如 {name}.exe / {name}.zip）为空
        self._plugin_dir = Path(plugin_dir).resolve()
        self._root = self._plugin_dir / ".dghub-sdk"
        self._log = log

    @property
    def plugin_dir(self) -> Path:
        """插件根目录（项目根锚点与回退基准）。"""
        return self._plugin_dir

    def _note(self, msg: str, level: str = "info") -> None:
        if self._log:
            getattr(self._log, level)(msg)

    # ------------------------------------------------------------------
    # 路径存取（存相对插件目录，跨盘符回退绝对）
    # ------------------------------------------------------------------

    def to_relative(self, path: str) -> str:
        """将绝对路径转为相对插件目录的存储形式；跨盘符时保留绝对路径。"""
        if not path:
            return ""
        try:
            rel = os.path.relpath(path, self._plugin_dir)
        except ValueError:
            self._note(f"路径与插件目录不同盘符，将存为绝对路径"
                       f"（不可移植）: {path}")
            return Path(path).as_posix()
        return Path(rel).as_posix()

    def to_absolute(self, stored: str) -> str:
        """将存储的（相对/绝对）路径解析为绝对路径；空串返回空串。"""
        if not stored:
            return ""
        p = Path(stored)
        if p.is_absolute():
            return p.as_posix()
        return (self._plugin_dir / p).resolve().as_posix()

    # ------------------------------------------------------------------
    # Manifest（插件元数据）
    # ------------------------------------------------------------------

    def read_manifest(self) -> dict[str, Any]:
        """Read `.dghub-sdk/manifest.json`, return dict (merged with defaults)."""
        data = dict(_MANIFEST_DEFAULTS)
        path = self._root / "manifest.json"
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass
        return data

    def write_manifest(self, data: dict[str, Any]) -> None:
        """Write manifest data to `.dghub-sdk/manifest.json`."""
        self._root.mkdir(parents=True, exist_ok=True)
        merged = dict(_MANIFEST_DEFAULTS)
        merged.update(data)
        (self._root / "manifest.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Project config（compiler 节 + builder 节）
    # ------------------------------------------------------------------

    def _load_json(self, name: str) -> Any:
        path = self._root / name
        if path.is_file():
            try:
                # utf-8-sig：容忍 Windows 编辑器写入的 BOM
                return json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def read_project(self) -> dict[str, Any]:
        """读取并归一化 project.json（compiler 节 + builder 节）。

        旧结构转换已移除——project.json 只接受当前结构；旧顶层编译键
        作为未知键原样保留（不再搬移落盘）。
        """
        raw = self._load_json("project.json")
        if not isinstance(raw, dict):
            return self._fill_defaults({})
        return self._fill_defaults(raw)

    def write_project(self, data: dict[str, Any]) -> None:
        """Write project settings to `.dghub-sdk/project.json`."""
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "project.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _fill_defaults(raw: dict[str, Any]) -> dict[str, Any]:
        """补全顶层与 builder 节默认键；未知键原样保留。"""
        data = dict(raw)
        for k, v in _PROJECT_DEFAULTS.items():
            data.setdefault(k, dict(v) if isinstance(v, dict) else v)
        compiler = dict(data.get("compiler", {}))
        for k, v in _COMPILER_DEFAULTS.items():
            compiler.setdefault(k, v)
        data["compiler"] = compiler
        builder = dict(data.get("builder", {}))
        for k, v in _BUILDER_DEFAULTS.items():
            builder.setdefault(k, v)
        if not isinstance(builder.get("files"), list):
            builder["files"] = []
        data["builder"] = builder
        return data

    # ------------------------------------------------------------------
    # 字段便捷存取（顶层 / builder 节）
    # ------------------------------------------------------------------

    def get_field(self, key: str) -> Any:
        """读顶层字段（compile_system / manifest / include_sdk ...）。"""
        return self.read_project().get(key, _PROJECT_DEFAULTS.get(key))

    def set_field(self, key: str, value: Any) -> None:
        """写一个顶层字段（read-merge-write，保留未知键）。"""
        project = self.read_project()
        project[key] = value
        self.write_project(project)

    def get_builder(self) -> dict[str, Any]:
        """读 builder 节（合并默认值）。"""
        return dict(self.read_project().get("builder", _BUILDER_DEFAULTS))

    def set_builder_field(self, key: str, value: Any) -> None:
        """写 builder 节一个字段（read-merge-write）。"""
        project = self.read_project()
        builder = dict(project.get("builder", {}))
        builder[key] = value
        project["builder"] = builder
        self.write_project(project)

    def read_builder_files(self) -> list[dict[str, Any]]:
        """读 builder.files 条目列表。"""
        return list(self.get_builder().get("files", []))

    def write_builder_files(self, files: list[dict[str, Any]]) -> None:
        """写 builder.files 条目列表。"""
        self.set_builder_field("files", files)


def project_exists(plugin_dir: str) -> bool:
    """Check if `.dghub-sdk/` exists in the given directory."""
    return (Path(plugin_dir) / ".dghub-sdk" / "manifest.json").is_file()
