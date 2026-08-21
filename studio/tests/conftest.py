"""pytest 共享夹具：路径注入、项目工厂与 BuildContext 组装。"""

import sys
from pathlib import Path

import pytest

# backend/gui 为 studio/src 下的顶层包，测试按 backend.* 导入后端
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from backend.builder import Builder  # noqa: E402
from backend.logbus import Logger  # noqa: E402
from backend.pipeline import BuildContext  # noqa: E402
from backend.project_manager import ProjectManager  # noqa: E402


@pytest.fixture
def make_project(tmp_path: Path):
    """项目工厂：创建插件目录 + ProjectManager + Builder。

    返回 (pm, builder, plugin_dir)，project.json 已初始化。
    """

    def _make(name: str = "testplugin") -> tuple[ProjectManager, Builder, Path]:
        plugin_dir = tmp_path / name
        (plugin_dir / ".dghub-sdk").mkdir(parents=True)
        (plugin_dir / ".dghub-sdk" / "manifest.json").write_text(
            '{"id": "test", "name": "test", "version": "0.1.0"}',
            encoding="utf-8")
        pm = ProjectManager(str(plugin_dir))
        pm.write_project({})
        return pm, Builder(pm), plugin_dir

    return _make


@pytest.fixture
def make_ctx(tmp_path: Path):
    """BuildContext 工厂：自动创建插件/源码/输出目录并收集日志。"""

    def _make(pm: ProjectManager, builder: Builder,
              plugin_dir: Path, compile_system: str = "",
              compile_cfg: dict | None = None,
              pypi_index: str = "") -> tuple[BuildContext, list[str]]:
        output_dir = tmp_path / "output"
        output_dir.mkdir(exist_ok=True)
        logs: list[str] = []
        ctx = BuildContext(
            plugin_dir=plugin_dir,
            source_dir=plugin_dir,
            output_dir=output_dir,
            plugin_name=plugin_dir.name,
            compile_system=compile_system,
            builder=builder,
            log=Logger(lambda text, level: logs.append(text)),
            pm=pm,
            pypi_index=pypi_index,
            compile_cfg=compile_cfg or {},
        )
        return ctx, logs

    return _make
