"""build-only CLI：读 .dghub-sdk/ 构建插件（CI 专用，只读配置）。

- 唯一命令 ``build [目录]``：读 project.json + manifest.json → 两阶段构建 → 出包
- 无任何配置命令（init/config/fill/apply/export）——项目配置唯一来源 = GUI
  生成的 ``.dghub-sdk/``（可进 git 版本化）；本 CLI **不修改项目配置**
- 运行期参数仅 ``--pypi-index``（镜像覆盖，不落盘）
- 退出码（应用层约定，跨平台一致）：0 成功 / 2 用法 / 3 校验失败 /
  4 构建失败 / 130 取消
"""

import argparse
import signal
import sys
from pathlib import Path

from backend.builder import BuildError, Builder
from backend.build_control import Canceller
from backend.logbus import Logger
from backend.pipeline import BuildContext, run_build, validate
from backend.project_manager import (
    ProjectManager,
)

try:
    from backend._version import __version__
except ImportError:  # 源码运行（_version.py 仅构建期生成）
    __version__ = "dev"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_VALIDATE = 3
EXIT_BUILD = 4
EXIT_CANCELLED = 130

# 级别 → (ANSI 色码, 前缀)
_LEVEL_STYLE = {
    "error": ("31", "错误"),
    "warning": ("33", "警告"),
    "success": ("32", "成功"),
}


def _stdout_logger(color: bool) -> Logger:
    """stdout sink：error/warning/success 加前缀与可选 ANSI 着色。"""

    def sink(text: str, level: str) -> None:
        code, prefix = _LEVEL_STYLE.get(level, ("", ""))
        line = f"{prefix} {text}" if prefix else text
        if color and code:
            line = f"\033[{code}m{line}\033[0m"
        print(line)

    return Logger(sink)


def _install_sigint(canceller: Canceller) -> None:
    """Ctrl+C → 取消构建（终止子进程树），退出码 130。"""

    def handler(_sig, _frame) -> None:  # noqa: ANN001
        canceller.cancel()

    try:
        signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError):
        pass


def _make_ctx(pm: ProjectManager, plugin_dir: str, logger: Logger,
              pypi_index: str) -> BuildContext:
    """从 project.json 组装 BuildContext（只读）。"""
    project = pm.read_project()
    compile_system = project.get("compiler", {}).get("compile_system", "")
    out_cfg = project.get("builder", {})
    output_dir = (pm.to_absolute(out_cfg.get("output_dir", ""))
                  or str(Path(plugin_dir) / "output"))
    match compile_system:
        case "python":
            compile_cfg = {
                "manifest": project.get("compiler", {}).get("manifest", ""),
            }
        case "node":
            compile_cfg = {
                "manifest": project.get("compiler", {}).get("manifest", ""),
            }
        case "command":
            compile_cfg = {
                "command": project.get("compiler", {}).get("command", ""),
                "compile_dir": project.get("compiler", {}).get("compile_dir", ""),
            }
        case _:
            compile_cfg = {}
    return BuildContext(
        plugin_dir=Path(plugin_dir),
        source_dir=Path(plugin_dir),
        output_dir=Path(output_dir),
        plugin_name=Path(plugin_dir).name,
        compile_system=compile_system,
        builder=Builder(pm),
        log=logger,
        pm=pm,
        pypi_index=pypi_index,
        compile_cfg=compile_cfg,
    )


def cmd_build(args: argparse.Namespace, logger: Logger) -> int:
    plugin_dir = str(Path(args.dir).resolve())
    if not (Path(plugin_dir) / ".dghub-sdk" / "manifest.json").is_file():
        logger.error(f"未找到 Packer 项目（缺少 .dghub-sdk/）: {plugin_dir}")
        return EXIT_USAGE

    pm = ProjectManager(plugin_dir, log=logger)
    pm.read_project()

    canceller = Canceller()
    _install_sigint(canceller)
    ctx = _make_ctx(pm, plugin_dir, logger, args.pypi_index or "")
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("开始校验")
    errors = validate(ctx)
    if errors:
        for msg in errors:
            logger.error(msg)
        return EXIT_VALIDATE
    logger.info("校验通过")

    try:
        artifact = run_build(ctx, pm.read_manifest())
    except BuildError as be:
        for msg in be.errors:
            logger.error(msg)
        return EXIT_BUILD
    if canceller.cancelled:
        logger.warning("构建已取消")
        return EXIT_CANCELLED
    if artifact is None:
        return EXIT_BUILD
    logger.success(f"构建完成: {artifact}")
    return EXIT_OK


def dispatch(argv: list[str]) -> int:
    # 全局标志（--no-color）挂到顶层与 build 子命令（parents），前后置皆可
    g = argparse.ArgumentParser(add_help=False)
    g.add_argument("--no-color", action="store_true",
                   help="禁用 ANSI 着色（CI 日志）")
    parser = argparse.ArgumentParser(
        prog="dgpacker-cli",
        description="DGHub SDK Packer CI 构建：读 .dghub-sdk/ 构建插件"
                    "（只读配置，无配置命令）",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"DGHub SDK Packer {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_build = sub.add_parser("build", parents=[g],
                             help="读 .dghub-sdk/ 构建插件")
    p_build.add_argument("dir", nargs="?", default=".",
                         help="插件目录（默认当前目录）")
    p_build.add_argument("--pypi-index", default="",
                         help="PyPI 镜像源（运行期覆盖，不写入配置）")
    args = parser.parse_args(argv)

    logger = _stdout_logger(not getattr(args, "no_color", False))
    if args.command == "build":
        return cmd_build(args, logger)
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(dispatch(sys.argv[1:]))
