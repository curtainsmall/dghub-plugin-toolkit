"""backend 单元测试：配置迁移 / Builder / 编译 / 管线 / 打包。"""

import json
from pathlib import Path

import pytest

from backend.builder import BuildError, evaluate_pattern
from backend.packaging import package_plugin, cleanup_intermediates
from backend.pipeline import fill_builder, run_build, validate
from backend.compilers import COMPILERS, get_compiler


# ---------------------------------------------------------------------------
# project_manager：配置读取/归一化
# ---------------------------------------------------------------------------


def test_defaults_fill(make_project):
    pm, _, _ = make_project()
    project = pm.read_project()
    assert project["compiler"]["compile_system"] == ""
    assert project["compiler"]["include_sdk"] is True
    assert project["builder"] == {"files": [], "output_dir": ""}


def test_unknown_keys_preserved(make_project):
    pm, _, _ = make_project()
    project = pm.read_project()
    project["future_key"] = {"x": 1}
    pm.write_project(project)
    assert pm.read_project()["future_key"] == {"x": 1}


def test_builder_items_and_tags(make_project):
    pm, b, _ = make_project()
    b.add_file("main.exe", ["entry"])
    b.add_dir("assets")
    b.add_rule("dist/**")
    items = b.items()
    assert items[0].to_dict() == {"path": "main.exe", "tags": ["entry"]}
    assert items[1].to_dict() == {"dir": "assets"}
    assert items[2].to_dict() == {"pattern": "dist/**"}
    b.set_tags(1, ["entry"])
    assert "entry" in b.items()[1].tags
    b.remove_item(1)
    assert len(b.items()) == 2


def test_builder_entry_validation(make_project):
    pm, b, plugin_dir = make_project()
    # 缺失 entry
    assert any("入口" in e for e in b.entry_errors(plugin_dir))
    b.add_file("main.exe", ["entry"])
    assert b.entry_errors(plugin_dir) == []
    # 多个 entry
    b.add_file("other.exe", ["entry"])
    assert any("重复" in e for e in b.entry_errors(plugin_dir))
    # 目录/规则不能作 entry（先移除文件条目，只剩 dir 条目）
    b.remove_item(0)
    b.remove_item(0)
    b.add_dir("assets", ["entry"])
    assert any("单个文件" in e for e in b.entry_errors(plugin_dir))


def test_builder_resolve_preserves_subdirs(make_project):
    pm, b, plugin_dir = make_project()
    (plugin_dir / "assets" / "sub").mkdir(parents=True)
    (plugin_dir / "assets" / "sub" / "x.dat").write_text("x")
    (plugin_dir / "assets" / "a.txt").write_text("a")
    (plugin_dir / "main.exe").write_text("exe")
    b.add_file("main.exe", ["entry"])
    b.add_dir("assets")
    files = b.resolve(plugin_dir)
    arcs = [arc for _, arc in files]
    assert "main.exe" in arcs
    assert "assets/sub/x.dat" in arcs      # 子目录结构保留
    assert "assets/a.txt" in arcs


def test_builder_resolve_dedup_and_errors(make_project):
    pm, b, plugin_dir = make_project()
    (plugin_dir / "assets").mkdir()
    (plugin_dir / "assets" / "x.dat").write_text("x")
    (plugin_dir / "main.exe").write_text("exe")
    b.add_file("main.exe", ["entry"])
    b.add_dir("assets")
    b.add_rule("assets/**")                # 与 dir 条目重叠
    files = b.resolve(plugin_dir)
    arcs = [arc for _, arc in files]
    assert arcs.count("assets/x.dat") == 1  # 去重
    # 缺失文件 → BuildError
    b.add_file("missing.dat")
    with pytest.raises(BuildError):
        b.resolve(plugin_dir)


def test_evaluate_pattern(make_project):
    pm, _, plugin_dir = make_project()
    (plugin_dir / "dist").mkdir()
    (plugin_dir / "dist" / "a.bin").write_text("a")
    (plugin_dir / "dist" / "b.bin").write_text("b")
    assert evaluate_pattern(plugin_dir, "dist/*.bin") == ["dist/a.bin",
                                                          "dist/b.bin"]


# ---------------------------------------------------------------------------
# compilers：PythonCompiler / CommandCompiler
# ---------------------------------------------------------------------------


def test_python_compiler_probe(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[tool.dghub]\nentry='src/main.py'\n")
    py = get_compiler("python")
    assert py.probe(root) == {"manifest": "pyproject.toml",
                              "include_sdk": True}
    # 无 pyproject → None
    assert py.probe(tmp_path / "empty") is None


def test_python_compiler_deduce(make_project):
    py = get_compiler("python")
    assert [i.to_dict() for i in py.deduce(
        {"manifest": "pyproject.toml"}, "my-plugin")] == [
        {"path": "my-plugin.exe", "tags": ["entry"], "derived": True},
        {"dir": "_internal", "derived": True}]
    assert py.deduce({"manifest": ""}, "my-plugin") is None
    cmd = get_compiler("command")
    assert cmd.deduce({"compile": "x"}, "my-plugin") is None


def test_python_compiler_manifest_known():
    py = get_compiler("python")
    # 仅 pyproject.toml（唯一可声明 [tool.dghub].entry 的清单）
    assert py.is_known_manifest("pyproject.toml")
    for name in ("setup.py", "setup.cfg", "requirements.txt",
                 "requirements-dev.txt", "package.json"):
        assert not py.is_known_manifest(name), name


def test_python_compiler_validate(make_project):
    pm, _, plugin_dir = make_project()
    py = get_compiler("python")
    # 缺 manifest → 错误
    assert py.validate({}, plugin_dir)
    # 不可识别清单 → 错误
    assert py.validate({"manifest": "package.json"}, plugin_dir)
    # pyproject 缺 [tool.dghub].entry → 错误
    cfg = {"manifest": "pyproject.toml", "include_sdk": True}
    assert any("[tool.dghub].entry" in e
               for e in py.validate(cfg, plugin_dir))
    # 非 .py 入口 → 错误
    (plugin_dir / "pyproject.toml").write_text(
        "[tool.dghub]\nentry='app.exe'\n")
    assert any(".py" in e for e in py.validate(cfg, plugin_dir))
    # 通过（入口存在性由 resolve 兜底）
    (plugin_dir / "pyproject.toml").write_text(
        "[tool.dghub]\nentry='main.py'\n")
    (plugin_dir / "main.py").write_text("x")
    assert py.validate(cfg, plugin_dir) == []


def test_compiler_registry():
    assert set(COMPILERS) == {"", "python", "node", "command"}
    # 「无」也是合法编译系统：空串/未知 id 恒返回实例（非 None）
    none_comp = get_compiler("")
    assert none_comp.id == "" and none_comp.label == "无"
    assert get_compiler("unknown") is none_comp
    assert none_comp.run(object()) is True  # 阶段 1 空操作


# ---------------------------------------------------------------------------
# pipeline：validate / fill / run_build
# ---------------------------------------------------------------------------


def test_validate_required(make_project, make_ctx):
    pm, b, plugin_dir = make_project()
    ctx, _ = make_ctx(pm, b, plugin_dir, compile_system="python",
                      compile_cfg={"manifest": "", "include_sdk": True})
    errors = validate(ctx)
    # 编译必要字段（manifest 缺失）+ Builder 必要条目（entry 缺失）
    assert any("依赖清单" in e for e in errors)
    assert any("入口" in e for e in errors)
    # 无编译：仅 Builder 必要条目校验
    ctx2, _ = make_ctx(pm, b, plugin_dir)
    assert any("入口" in e for e in validate(ctx2))


def test_fill_builder_only_fills_empty(make_project, make_ctx):
    pm, b, plugin_dir = make_project()
    pm.set_field("compile_system", "python")
    pm.set_field("manifest", "pyproject.toml")
    ctx, _ = make_ctx(pm, b, plugin_dir, compile_system="python",
                      compile_cfg={"manifest": "pyproject.toml",
                                   "include_sdk": True})
    applied = fill_builder(ctx)
    assert applied and any("入口" in a for a in applied)
    assert b.entry_errors(plugin_dir) == []
    # 编译产物条目：exe（入口）+ _internal/（derived）
    items = b.items()
    assert len(items) == 2
    assert items[0].to_dict() == {"path": "testplugin.exe", "tags": ["entry"],
                                  "derived": True}
    assert items[1].to_dict() == {"dir": "_internal", "derived": True}
    # 再次 fill 不重复添加
    fill_builder(ctx)
    assert len(b.items()) == 2
    # 无编译 → 也清除旧 derived，返回清除提示（非 None）
    ctx2, _ = make_ctx(pm, b, plugin_dir, compile_system="")
    applied = fill_builder(ctx2)
    assert applied and any("已刷新" in a for a in applied)
    assert len(b.items()) == 0  # derived 全清，用户条目无


def test_run_build_no_compile(make_project, make_ctx):
    """无编译（纯收集）路径：entry 产物 + 资源 → zip。"""
    pm, b, plugin_dir = make_project()
    (plugin_dir / "main.py").write_text("print('hi')\n")
    (plugin_dir / "assets").mkdir()
    (plugin_dir / "assets" / "data.json").write_text("{}")
    b.add_file("main.py", ["entry"])
    b.add_dir("assets")
    ctx, _ = make_ctx(pm, b, plugin_dir )
    artifact = run_build(ctx, {"id": "t", "name": "t"})
    assert artifact is not None
    # 发布固定 zip；包名默认 = 插件目录名
    assert artifact.name == "testplugin.zip"
    import zipfile
    with zipfile.ZipFile(artifact) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "main.py" in names
        assert "assets/data.json" in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["entry"] == "main.py"


def test_run_build_folder_override(make_project, make_ctx):
    """调试 folder 覆盖（内存，不落盘）：set_no_zip(True) → 目录产物。"""
    pm, b, plugin_dir = make_project()
    (plugin_dir / "main.exe").write_text("exe")
    b.add_file("main.exe", ["entry"])
    b.set_no_zip(True)
    ctx, _ = make_ctx(pm, b, plugin_dir )
    artifact = run_build(ctx, {"id": "t", "name": "t"})
    assert artifact is not None and artifact.is_dir()
    assert (artifact / "manifest.json").is_file()
    assert (artifact / "main.exe").is_file()
    manifest = json.loads((artifact / "manifest.json").read_text())
    assert manifest["entry"] == "main.exe"


def test_run_build_missing_entry_file(make_project, make_ctx):
    """无编译 + entry 条目缺失 → 收集阶段 BuildError（不再豁免）。"""
    pm, b, plugin_dir = make_project()
    b.add_file("missing.exe", ["entry"])
    ctx, _ = make_ctx(pm, b, plugin_dir )
    with pytest.raises(BuildError) as exc_info:
        run_build(ctx, {"id": "t", "name": "t"})
    assert any("不存在" in m for m in exc_info.value.errors)


def test_resolve_entry_exempt(make_project, make_ctx):
    """resolve：有编译输入时 entry 缺失豁免；无编译时不豁免。"""
    pm, b, plugin_dir = make_project()
    b.add_file("missing.exe", ["entry"])
    # 有编译输入（manifest）→ 豁免
    out = b.resolve(plugin_dir, entry_exempt=True)
    assert out == []
    # 无编译 → 报「打包内容文件不存在」
    with pytest.raises(BuildError) as exc_info:
        b.resolve(plugin_dir, entry_exempt=False)
    assert any("missing.exe" in m for m in exc_info.value.errors)


def test_run_build_command_compiler(make_project, make_ctx, tmp_path):
    """CommandCompiler：compile 产出文件 → 收集。"""
    pm, b, plugin_dir = make_project()
    script = tmp_path / "gen.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path('out/plugin.exe').parent.mkdir(parents=True, exist_ok=True)\n"
        "Path('out/plugin.exe').write_bytes(b'exe')\n")
    # compile 在插件目录执行，产出 out/plugin.exe
    pm.set_field("compile_system", "command")
    pm.set_field("compile", f"python {script.as_posix()}")
    (plugin_dir / "out").mkdir()
    (plugin_dir / "out" / "plugin.exe").write_bytes(b"exe")
    b.add_file("out/plugin.exe", ["entry"])
    ctx, _ = make_ctx(pm, b, plugin_dir, compile_system="command",
                      compile_cfg={"compile": f"python {script.as_posix()}",
                                   "compile_dir": ""})
    ok = run_build(ctx, {"id": "t", "name": "t"})
    assert ok is not None, "command compiler build should succeed"
    import zipfile
    with zipfile.ZipFile(ok) as zf:
        assert "out/plugin.exe" in zf.namelist()


def test_packaging_cleanup(make_project):
    pm, _, plugin_dir = make_project()
    output = plugin_dir / "output"
    output.mkdir()
    (output / ".deps").mkdir()
    (output / ".pyi").mkdir()
    (output / "cache").mkdir()
    (output / "testplugin.zip").write_bytes(b"x")
    cleanup_intermediates(output, "testplugin")
    assert not (output / ".deps").exists()
    assert not (output / ".pyi").exists()
    assert not (output / "cache").exists()
    assert (output / "testplugin.zip").exists()  # 产物保留
