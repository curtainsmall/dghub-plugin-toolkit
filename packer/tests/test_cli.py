"""CLI 单元测试：build-only（只读构建，无配置命令）。"""

import json
import zipfile
from pathlib import Path

import pytest

from cli.cli import (
    EXIT_BUILD,
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VALIDATE,
    _make_ctx,
    _stdout_logger,
    dispatch,
)
from backend.project_manager import ProjectManager


def _write_project(plugin_dir: Path, project: dict, files: dict[str, str]) -> None:
    """建最小 Packer 项目：project.json + manifest.json + 若干文件。"""
    (plugin_dir / ".dghub-sdk").mkdir(parents=True, exist_ok=True)
    (plugin_dir / ".dghub-sdk" / "manifest.json").write_text(
        '{"id": "t", "name": "t", "version": "0.1.0"}', encoding="utf-8")
    (plugin_dir / ".dghub-sdk" / "project.json").write_text(
        json.dumps(project), encoding="utf-8")
    for rel, content in files.items():
        p = plugin_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def test_build_success(tmp_path, capsys):
    """无编译（纯收集）：entry 产物 + 资源 → zip，退出码 0。"""
    root = tmp_path / "proj"
    _write_project(root, {
            "compile_system": "",
        "entry": "main.py",
        "builder": {
            "files": [{"path": "main.py", "tags": ["entry"]},
                      {"dir": "assets"}],
            "output_dir": "",
        },
    }, {"main.py": "print('hi')\n", "assets/data.json": "{}\n"})
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_OK, capsys.readouterr().out
    zip_path = root / "output" / "proj.zip"  # 包名默认 = 插件目录名
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "main.py" in names and "assets/data.json" in names
        assert json.loads(zf.read("manifest.json"))["entry"] == "main.py"


def test_build_missing_entry(tmp_path, capsys):
    """缺 entry 条目 → 校验失败退出码 3。"""
    root = tmp_path / "proj"
    _write_project(root, {
            "compiler": {"compile_system": ""},
        "entry": "main.py",
        "builder": {"files": [], "output_dir": ""},
    }, {"main.py": "print('hi')\n"})
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_VALIDATE
    assert "入口" in capsys.readouterr().out


def test_build_no_project(tmp_path, capsys):
    """非 Packer 项目目录 → 用法错误退出码 2。"""
    root = tmp_path / "empty"
    root.mkdir()
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_USAGE
    assert ".dghub-sdk" in capsys.readouterr().out


def test_version(capsys):
    """--version 输出产品全名并退出 0（argparse version action）。"""
    with pytest.raises(SystemExit) as exc:
        dispatch(["--version"])
    assert exc.value.code == 0
    assert "DGHub SDK Packer" in capsys.readouterr().out


def test_build_no_color_position(tmp_path, capsys):
    """--no-color 支持子命令后置（CI 习惯写法）。"""
    root = tmp_path / "proj"
    _write_project(root, {
            "compile_system": "",
        "entry": "main.py",
        "builder": {"files": [{"path": "main.py", "tags": ["entry"]}],
                    "output_dir": ""},
    }, {"main.py": "x"})
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_OK
    assert (root / "output" / "proj.zip").is_file()  # 发布固定 zip


def test_build_no_project_readonly(tmp_path, capsys):
    """CLI 不修改项目配置：构建后 project.json 原样。"""
    root = tmp_path / "proj"
    project = {
        "compiler": {"compile_system": ""},
        "entry": "main.py",
        "builder": {"files": [{"path": "main.py", "tags": ["entry"]}],
                    "output_dir": ""},
    }
    _write_project(root, project, {"main.py": "x"})
    before = (root / ".dghub-sdk" / "project.json").read_bytes()
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_OK
    after = (root / ".dghub-sdk" / "project.json").read_bytes()
    assert before == after  # 只读：配置未被改动


def test_make_ctx_reads_mode_and_suffix(tmp_path):
    """CLI 上下文组装：python/node 读取 self_contained + auto_suffix——
    正式构建 zip 名后缀与调试一致（回归：此前只读 manifest，依赖版
    项目误按自包含 deduce 且永不追加后缀）。"""
    root = tmp_path / "proj"
    _write_project(root, {
        "compiler": {"compile_system": "python",
                     "manifest": "pyproject.toml",
                     "self_contained": False,
                     "auto_suffix": True},
        "builder": {"files": [], "output_dir": ""},
    }, {"pyproject.toml": "[tool.dghub]\nentry='main.py'\n"})
    pm = ProjectManager(str(root))
    ctx = _make_ctx(pm, str(root), _stdout_logger(False), "")
    assert ctx.compile_cfg["self_contained"] is False
    assert ctx.compile_cfg["auto_suffix"] is True
    # 缺字段 → 默认：自包含 + 无后缀
    root2 = tmp_path / "proj2"
    _write_project(root2, {
        "compiler": {"compile_system": "node",
                     "manifest": "package.json"},
        "builder": {"files": [], "output_dir": ""},
    }, {"package.json": "{}"})
    pm2 = ProjectManager(str(root2))
    ctx2 = _make_ctx(pm2, str(root2), _stdout_logger(False), "")
    assert ctx2.compile_cfg["self_contained"] is True
    assert ctx2.compile_cfg["auto_suffix"] is False
