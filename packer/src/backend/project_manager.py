""".dghub-sdk/ project configuration management.

project.json 为唯一配置文件（format_version 2，顶层平铺 + builder 节）::

    {
      "format_version": 2,
      "compile_system": "python",      # 编译选择：""（无）/ "python" / "command"
      "compile": "",            # CommandCompiler 设置（compile_system="command" 时必填）
      "compile_dir": "",             # CommandCompiler 执行目录（空 = 项目根）
      "manifest": "",             # PythonCompiler 设置（compile_system="python" 时必填）
      "include_sdk": true,        # PythonCompiler 选项：是否打包 dghub-sdk
      "builder": {
        "files": [],              # 统一文件选择列表：[{"path"|"dir"|"pattern", "tags"}]
        "no_zip": false,          # 发布形态：false = zip（默认）；true = folder
        "output_dir": ""          # 输出目录（空 = 插件目录/output）
      }
    }

- 路径（manifest / compile_dir / output_dir）存相对插件目录的路径，跨盘符时回退绝对路径
- 未知键在读-改-写时保留，不丢数据
- 旧格式（format_version 1，build_systems 命名空间）执行破坏性迁移：
  字段归位（compile_system 按 manifest/compile 推断、extra_files 去 dest 入
  builder.files、target 映射 no_zip），并删除旧 deps.json（manifest.json 不受影响）
- 编译入口（entry）为 Python 编译专属输入，由 PythonCompiler 从
  pyproject.toml 的 [tool.dghub].entry 现读，不入 project.json
"""

import json
import os
from pathlib import Path
from typing import Any

from backend.logbus import Logger

# 当前支持的配置格式代数（仅破坏性变更时递增）
_SUPPORTED_FORMAT = 2

_MANIFEST_DEFAULTS: dict[str, Any] = {
    "id": "",
    "name": "",
    "version": "",
    "author": "",
    "description": "",
    "sdk": "1",
}

# 顶层默认值（compile_system 显式单选："" 无 / "python" / "command"）
_PROJECT_DEFAULTS: dict[str, Any] = {
    "compile_system": "",
    "compile": "",
    "compile_dir": "",
    "manifest": "",
    "include_sdk": True,
}

# builder 节默认值（files = 统一文件选择列表，条目 {path|dir|pattern, tags}）
_BUILDER_DEFAULTS: dict[str, Any] = {
    "files": [],
    "no_zip": False,
    "output_dir": "",
}


class UnsupportedFormatError(Exception):
    """project.json 由更新版本的 Packer 创建，当前版本无法读取。"""


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
    # Project config（format_version 2，顶层平铺 + builder 节）
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
        """读取并归一化 project.json；旧格式执行破坏性迁移。"""
        raw = self._load_json("project.json")
        deps_path = self._root / "deps.json"

        if isinstance(raw, dict) and "format_version" in raw:
            fv = raw["format_version"]
            if isinstance(fv, int) and fv > _SUPPORTED_FORMAT:
                raise UnsupportedFormatError(
                    f"project.json 格式版本为 {fv}，当前仅支持 "
                    f"{_SUPPORTED_FORMAT}：项目由更新版本的 Packer 创建，"
                    "请升级 Packer")
            if fv == _SUPPORTED_FORMAT and "builder" in raw:
                data = self._fill_defaults(raw)
                # v2 早期键 producer → compile_system（温和搬移，落盘一次）
                if not data.get("compile_system") and data.get("producer"):
                    data["compile_system"] = data["producer"]
                    data.pop("producer", None)
                    try:
                        self.write_project(data)
                    except OSError:
                        pass
                return data
            # format_version 1 或结构不识别 → 破坏性迁移

        had_legacy = (isinstance(raw, dict) and bool(raw)) \
            or deps_path.is_file()
        if had_legacy:
            self._migrate_v1(raw or {}, deps_path)
        return self._fill_defaults(self._load_json("project.json") or {})

    def write_project(self, data: dict[str, Any]) -> None:
        """Write project settings to `.dghub-sdk/project.json`."""
        data.setdefault("format_version", _SUPPORTED_FORMAT)
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
            data.setdefault(k, v)
        builder = dict(data.get("builder", {}))
        for k, v in _BUILDER_DEFAULTS.items():
            builder.setdefault(k, v)
        if not isinstance(builder.get("files"), list):
            builder["files"] = []
        data["builder"] = builder
        return data

    def _migrate_v1(self, raw: dict[str, Any], deps_path: Path) -> None:
        """旧版（format_version 1，build_systems 命名空间）破坏性迁移。"""
        systems = raw.get("build_systems", {})
        if not isinstance(systems, dict):
            systems = {}
        uv = systems.get("uv", {})
        gen = systems.get("generic", {})

        data = dict(_PROJECT_DEFAULTS)
        data.update({
            "format_version": _SUPPORTED_FORMAT,
            # v1 entry/source_dir 弃用：编译入口由 PythonCompiler 从 pyproject 现读，
            # 构建根统一为插件目录
            "compile": gen.get("pre_build", ""),        # v1 旧键 pre_build
            "compile_dir": gen.get("exec_dir", ""),     # v1 旧键 exec_dir
            "manifest": uv.get("manifest", ""),
            "include_sdk": bool(uv.get("include_sdk", True)),
        })
        # compile_system 推断：manifest 非空 → python；否则 compile 非空 → command
        if data["manifest"]:
            data["compile_system"] = "python"
        elif data["compile"]:
            data["compile_system"] = "command"
        else:
            data["compile_system"] = ""

        # builder 节：extra_files 去 dest 入 files；target 映射 no_zip
        builder = dict(_BUILDER_DEFAULTS)
        files: list[dict[str, Any]] = []
        extra = gen.get("extra_files", [])
        if isinstance(extra, list):
            for item in extra:
                if not isinstance(item, dict):
                    continue
                new: dict[str, Any] = {}
                if "path" in item:
                    new["path"] = item["path"]
                elif "pattern" in item:
                    new["pattern"] = item["pattern"]
                else:
                    continue
                tags = item.get("tags")
                if isinstance(tags, list) and tags:
                    new["tags"] = tags
                files.append(new)
        builder["files"] = files
        builder["no_zip"] = (raw.get("target") == "folder")
        builder["output_dir"] = raw.get("output_dir", "")
        data["builder"] = builder

        try:
            self.write_project(data)
            if deps_path.is_file():
                deps_path.unlink()
            self._note("检测到旧版配置，已迁移到新格式"
                       "（manifest 不受影响），请检查设置", "warning")
        except OSError as exc:
            self._note(f"配置迁移落盘失败（{exc}），将在下次写入时重试",
                       "warning")

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
