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
    dispatch,
)


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
        "format_version": 2,
        "compile_system": "",
        "entry": "main.py",
        "builder": {
            "files": [{"path": "main.py", "tags": ["entry"]},
                      {"dir": "assets"}],
            "no_zip": False,
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
        "format_version": 2,
        "compile_system": "",
        "entry": "main.py",
        "builder": {"files": [], "no_zip": False, "output_dir": ""},
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
        "format_version": 2,
        "compile_system": "",
        "entry": "main.py",
        "builder": {"files": [{"path": "main.py", "tags": ["entry"]}],
                    "no_zip": True, "output_dir": ""},
    }, {"main.py": "x"})
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_OK
    assert (root / "output" / "proj").is_dir()  # no_zip 出 folder；包名默认 = 插件目录名


def test_build_no_project_readonly(tmp_path, capsys):
    """CLI 不修改项目配置：构建后 project.json 原样。"""
    root = tmp_path / "proj"
    project = {
        "format_version": 2,
        "compile_system": "",
        "entry": "main.py",
        "builder": {"files": [{"path": "main.py", "tags": ["entry"]}],
                    "no_zip": True, "output_dir": ""},
    }
    _write_project(root, project, {"main.py": "x"})
    before = (root / ".dghub-sdk" / "project.json").read_bytes()
    code = dispatch(["build", str(root), "--no-color"])
    assert code == EXIT_OK
    after = (root / ".dghub-sdk" / "project.json").read_bytes()
    assert before == after  # 只读：配置未被改动
