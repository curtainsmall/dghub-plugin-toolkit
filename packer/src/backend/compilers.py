"""compile 编译体系：抽象契约 + 两个实现 + 注册表。

编译 = 阶段 1（把源码变成可打包产物）的可插拔实现，由 project.json 的
``compile_system`` 字段显式单选（"" 无 / "python" / "command"）。一切语言相关
解析（清单识别、[tool.dghub].entry 读取、probe、deduce）都在编译内，
GUI 与管线不内置任何语言知识。

抽象契约（Compiler 九项能力）：身份、设置字段、启用、清单识别、
探测、预检、校验、推导、执行。编译不推断 Builder（deduce 只是建议）、
编译入口（[tool.dghub].entry）由 Python 编译从清单现读、不持久化、
不接触 GUI。
"""

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.build_control import Canceller
from backend.py_compiler import build_plugin_exe
from backend.logbus import Logger
from backend.winflags import _NO_WINDOW
from backend.builder import BuilderItem


@dataclass
class CompilerContext:
    """编译运行时上下文（run 时由管线组装）。"""

    plugin_dir: Path
    source_dir: Path
    output_dir: Path
    plugin_name: str
    cfg: dict[str, Any]          # 编译设置字段（compile_system 相关字段）
    log: Logger
    pypi_index: str = ""
    canceller: Canceller | None = None
    # 调试构建：保留缓存（PyInstaller workpath / tsc tsbuildinfo 增量）
    keep_cache: bool = False


def run_logged(cmd: Any, logger: Logger, source: str,
               cwd: str | os.PathLike[str] | None = None, shell: bool = False,
               timeout: int = 900,
               env: dict | None = None,
               canceller: Canceller | None = None) -> bool:
    """执行子进程（可取消），输出以来源分隔块记录，返回是否成功。"""
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=cwd, shell=shell, env=env,
            creationflags=_NO_WINDOW)
    except FileNotFoundError:
        logger.error(f"命令不存在: {cmd}")
        return False
    if canceller is not None:
        canceller.set_proc(proc)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        logger.error(f"命令超时: {cmd}")
        logger.external(source, (out or "").splitlines(), proc.returncode)
        return False
    finally:
        if canceller is not None:
            canceller.set_proc(None)
    logger.external(source, (out or "").splitlines(), proc.returncode)
    if canceller is not None and canceller.cancelled:
        logger.warning(f"{source} 已取消")
        return False
    return proc.returncode == 0


class Compiler:
    """compile 编译抽象契约（所有编译共有的接口形状）。"""

    id = ""
    label = ""
    description = ""
    # 设置字段 schema：{field: {"label": str, "type": "str"|"bool",
    #                            "default": Any, "required": bool}}
    fields: dict[str, dict[str, Any]] = {}

    def enabled(self, cfg: dict[str, Any]) -> bool:
        """由显式 compile_system 选择字段决定；缺必要字段由 validate 兜底。"""
        return bool(cfg)

    def is_known_manifest(self, filename: str) -> bool:
        """所选清单是否本编译可识别（无清单概念恒 False）。"""
        return False

    def probe(self, plugin_dir: Path) -> dict[str, Any] | None:
        """探测项目，建议初始配置（无探测能力恒 None）。"""
        return None

    def check_available(self) -> tuple[bool, str]:
        """工具可用性预检，返回 (可用, 标注文案)。"""
        return True, ""

    def validate(self, cfg: dict[str, Any],
                 source_dir: Path) -> list[str]:
        """静态校验编译设置，返回错误消息列表（空 = 通过）。"""
        errors: list[str] = []
        for fname, spec in self.fields.items():
            if spec.get("required") and not cfg.get(fname):
                errors.append(f"已选择 {self.label} 编译，"
                              f"但未填写{spec.get('label', fname)}")
        return errors

    def deduce(self, cfg: dict[str, Any],
                plugin_name: str = "",
                source_dir: Path | None = None) -> list[BuilderItem] | None:
        """检查设置是否足以推导 Builder 条目；返回建议条目或 None。

        ``source_dir`` 供需要读清单（如入口字段）的编译使用，可选。
        """
        return None

    def prod_dir(self, output_dir: Path, plugin_name: str) -> Path | None:
        """编译产物根目录（derived 条目解析基准）；无产物概念返回 None。

        编译产物约定集中在 output_dir 下、以 .<体系>/<插件名>/ 隔离，
        由管线在收集阶段传入 ``Builder.resolve(prod_dir=...)``。
        """
        return None

    def debug_source_command(self, plugin_dir: Path) -> list[str] | None:
        """「调试源码」启动命令；不支持返回 None。

        返回的命令由调试页在插件根目录启动（cwd=plugin_dir），
        结果 = 子进程退出码（stdout/stderr 进日志 tab）。
        """
        return None


    def run(self, ctx: CompilerContext) -> bool:
        """执行阶段 1 工作，产出文件；失败返回 False。"""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# CommandCompiler：用户自定义命令
# ---------------------------------------------------------------------------

class CommandCompiler(Compiler):
    """执行用户 shell 命令产出任意文件；产物位置不可预测，
    Builder 条目由用户声明（deduce 恒 None）。"""

    id = "command"
    label = "自定义命令"
    description = "构建前执行用户命令（如编译、生成资源），产物由打包内容声明"
    fields = {
        "command": {"label": "编译命令", "type": "str",
                      "default": "", "required": True},
        "compile_dir": {"label": "执行目录", "type": "str",
                     "default": "", "required": False},
    }

    def enabled(self, cfg: dict[str, Any]) -> bool:
        return bool(cfg.get("command"))

    def probe(self, plugin_dir: Path) -> dict[str, Any] | None:
        return None

    def deduce(self, cfg: dict[str, Any],
                plugin_name: str = "",
                source_dir: Path | None = None) -> list[BuilderItem] | None:
        return None

    def run(self, ctx: CompilerContext) -> bool:
        cmd = (ctx.cfg.get("command") or "").strip()
        if not cmd:
            ctx.log.error("编译命令为空")
            return False
        compile_dir = ctx.cfg.get("compile_dir") or str(ctx.source_dir)
        ctx.log.info(f"执行编译命令（执行目录 {compile_dir}）: {cmd}")
        return run_logged(cmd, ctx.log, "compile", cwd=compile_dir,
                          shell=True, canceller=ctx.canceller)


# ---------------------------------------------------------------------------
# PythonCompiler：uv 依赖下载 + PyInstaller onedir
# ---------------------------------------------------------------------------

# uv 可识别的依赖清单类型
_PY_MANIFESTS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements*.txt")


class PythonCompiler(Compiler):
    """uv 按清单下载依赖到 .deps → PyInstaller onedir 打包（含 SDK 可选）。

    产物约定：``out_dir/<name>/`` onedir 树（固定位置，管线整树收集）。
    """

    id = "python"
    label = "Python (uv + PyInstaller)"
    description = ("按依赖清单自动下载依赖并打包为自包含 exe"
                   "（uv 下载 + PyInstaller onedir）")
    fields = {
        "manifest": {"label": "依赖清单", "type": "str",
                     "default": "", "required": True},
    }

    def enabled(self, cfg: dict[str, Any]) -> bool:
        return bool(cfg.get("manifest"))

    def is_known_manifest(self, filename: str) -> bool:
        # Python 编译需要声明入口（[tool.dghub].entry）——仅 pyproject.toml
        # 支持该表；requirements.txt / setup.py 等无法声明，不接受
        return filename.lower() == "pyproject.toml"

    def probe(self, plugin_dir: Path) -> dict[str, Any] | None:
        """探测 pyproject.toml → 建议 manifest。"""
        pyproject = plugin_dir / "pyproject.toml"
        if not pyproject.is_file():
            return None
        return {
            "manifest": "pyproject.toml",
        }

    def check_available(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["uv", "--version"], capture_output=True, text=True,
                timeout=10, creationflags=_NO_WINDOW)
            if result.returncode == 0:
                return True, "需要 uv"
        except Exception:
            pass
        return False, "未检测到 uv，请 pip install uv"

    def validate(self, cfg: dict[str, Any],
                 source_dir: Path) -> list[str]:
        errors = super().validate(cfg, source_dir)
        manifest = cfg.get("manifest", "")
        if manifest and not self.is_known_manifest(Path(manifest).name):
            errors.append(f"无法识别的依赖清单: {Path(manifest).name}"
                          "（Python 编译仅支持 pyproject.toml——"
                          "唯一可声明 [tool.dghub].entry 的清单）")
        # entry 是 Python 编译专属输入（pyproject [tool.dghub].entry），
        # 由本编译系统从清单现读，不入 project.json
        entry = read_tool_dghub_entry(Path(source_dir) / manifest) \
            if manifest else ""
        if not entry:
            errors.append("pyproject.toml 缺少 [tool.dghub].entry"
                          "（Python 编译入口）")
        elif not entry.lower().endswith(".py"):
            errors.append(f"Python 编译的入口必须是 .py 文件: {entry}，"
                          "如为已构建产物请将编译设为「自定义命令」")
        elif not (source_dir / entry).is_file():
            errors.append(f"入口文件不存在: {entry}")
        return errors

    def deduce(self, cfg: dict[str, Any],
                plugin_name: str = "",
                source_dir: Path | None = None) -> list[BuilderItem] | None:
        """manifest 已选 → 推导编译产物条目（显式声明，derived 只读）。

        - 入口 exe（<插件名>.exe，entry 标签）
        - _internal/ 依赖目录（PyInstaller onedir 产物）
        两者均为编译产出，构建时从产物树解析。
        """
        if not cfg.get("manifest"):
            return None
        if not plugin_name:
            return None
        return [
            BuilderItem(path=f"{plugin_name}.exe", tags=["entry"],
                        derived=True),
            BuilderItem(dir="_internal", derived=True),
        ]

    def prod_dir(self, output_dir: Path, plugin_name: str) -> Path | None:
        return output_dir / ".pyi" / plugin_name

    def debug_source_command(self, plugin_dir: Path) -> list[str] | None:
        """uv run --project 运行 [tool.dghub].entry 源码；entry 缺失返回 None。"""
        entry = read_tool_dghub_entry(plugin_dir / "pyproject.toml")
        if not entry:
            return None
        return ["uv", "run", "--project", str(plugin_dir), entry]


    def run(self, ctx: CompilerContext) -> bool:
        manifest = ctx.cfg.get("manifest", "")
        if not manifest:
            ctx.log.error("依赖清单为空")
            return False
        manifest_path = Path(ctx.source_dir) / manifest
        if not manifest_path.is_file():
            ctx.log.error(f"依赖清单不存在: {manifest_path}")
            return False

        # 1) uv 按清单安装依赖到 .deps（中间产物，构建后清理）
        deps_dir = ctx.output_dir / ".deps"
        ctx.log.info(f"依赖来源: {manifest}，安装到 .deps/ ...")
        env = None
        if ctx.pypi_index:
            env = {**os.environ, "UV_DEFAULT_INDEX": ctx.pypi_index}
            ctx.log.detail(f"使用 PyPI 镜像源: {ctx.pypi_index}")
        ok = run_logged(
            ["uv", "pip", "install", "--target", str(deps_dir),
             "-r", str(manifest_path)],
            ctx.log, "uv", cwd=ctx.source_dir,
            env=env, canceller=ctx.canceller)
        if not ok:
            ctx.log.error("依赖打包失败")
            return False
        ctx.log.info("依赖打包完成")

        # 2) PyInstaller onedir 打包（依赖 + 项目根散装模块进 exe）
        entry = read_tool_dghub_entry(manifest_path)
        if not entry:
            ctx.log.error("pyproject.toml 缺少 [tool.dghub].entry"
                          "（Python 编译入口）")
            return False
        ctx.log.info("构建 exe...")
        ok = build_plugin_exe(
            plugin_dir=str(ctx.plugin_dir),
            source_dir=str(ctx.source_dir),
            logger=ctx.log,
            output_dir=str(ctx.output_dir),
            entry=entry,
            dep_dir=str(deps_dir),
            canceller=ctx.canceller,
        )
        if not ok:
            ctx.log.error("exe 构建失败")
            return False

        # 3) 清理 PyInstaller 残留（插件目录内，构建后即清）
        for leftover in ctx.plugin_dir.glob("*.spec"):
            leftover.unlink()
        build_dir = ctx.plugin_dir / "build"
        if build_dir.is_dir():
            shutil.rmtree(build_dir, ignore_errors=True)
        ctx.log.info("exe 构建完成")
        return True


def read_tool_dghub_entry(manifest: Path) -> str:
    """读 pyproject.toml 的 [tool.dghub].entry（可选约定，仅读不写）。

    不存在、非 pyproject.toml 或解析失败均返回空串。
    """
    if manifest.name != "pyproject.toml" or not manifest.is_file():
        return ""
    try:
        import tomllib
        with manifest.open("rb") as f:
            data = tomllib.load(f)
        entry = data.get("tool", {}).get("dghub", {}).get("entry", "")
        return entry if isinstance(entry, str) else ""
    except Exception:
        return ""


def read_package_json_main(manifest: Path) -> str:
    """读 package.json 的 main 入口字段；缺省回退 ``index.js``。

    不存在、非 package.json 或解析失败均返回空串。
    """
    if manifest.name != "package.json" or not manifest.is_file():
        return ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        main = data.get("main", "")
        return main if isinstance(main, str) and main else "index.js"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# NodeCompiler：npm 依赖 + tsc（可选）+ SEA 打包（exe + node_modules + 入口目录）
# ---------------------------------------------------------------------------

# SEA 注入引导器模板：SEA 内嵌脚本的 require 仅支持内置模块，
# 外部依赖/入口必须经 import() 动态加载（PoC 验证）
_SEA_BOOTSTRAP = '''\
const path = require("path");
const { pathToFileURL } = require("url");
import(pathToFileURL(path.join(__dirname, "{entry}")).href)
  .catch((e) => {{ console.error(e); process.exit(1); }});
'''

# postject 注入哨兵（官方固定值）
_SEA_FUSE = "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2"

# 依赖版启动器（bundle=deps）：DGHub 以 .py 入口执行本脚本（宿主自带 Python
# 运行时），拉起系统 Node 运行插件入口。环境变量（DGHUB_TOKEN 等）由子进程继承。
_NODE_LAUNCHER = '''\
"""Node 插件启动器（依赖版产物，由 Packer 生成）。

DGHub 以 .py 入口执行本脚本（宿主自带 Python 运行时），拉起系统 Node
运行插件入口；环境变量（DGHUB_TOKEN 等）由子进程继承。
"""
import shutil
import subprocess
import sys
from pathlib import Path

node = shutil.which("node")
if node is None:
    sys.exit("未找到 node，请安装 Node.js（依赖版产物需要系统 Node 运行时）")

entry = Path(__file__).resolve().parent / "{entry}"
proc = subprocess.Popen(
    [node, str(entry)],
    creationflags=0x08000000,  # CREATE_NO_WINDOW：无控制台窗口
)
sys.exit(proc.wait())
'''


def _node_tool(name: str) -> list[str]:
    """解析 npm/npx 可执行路径（Windows 下为 .cmd，需经 cmd.exe 执行）。"""
    path = shutil.which(name)
    if path and path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", path]
    return [path or name]


class NodeCompiler(Compiler):
    """npm 按 package.json 安装依赖 → tsc 编译（可选）→ SEA 打包。

    产物约定（onedir，同 PyInstaller 模式）：``out_dir/.node/<name>/`` 下
    的 SEA exe（含 Node.js 运行时 + 引导器）+ ``node_modules/`` + 入口目录。
    入口 = package.json ``main``（生态标准，缺省 index.js）。
    """

    id = "node"
    label = "Node.js (npm + SEA)"
    description = ("按 package.json 安装依赖并打包为自包含 exe"
                   "（npm + tsc 可选 + SEA 单文件运行时）")
    fields = {
        "manifest": {"label": "依赖清单", "type": "str",
                     "default": "", "required": True},
        "bundle": {"label": "产物模式", "type": "str",
                   "default": "exe", "required": False,
                   "choices": [
                       ("exe", "自包含（SEA exe，目标机无需 Node）"),
                       ("deps", "依赖版（源码 + node_modules + 启动脚本，需系统 Node）"),
                   ]},
    }

    def enabled(self, cfg: dict[str, Any]) -> bool:
        return bool(cfg.get("manifest"))

    def is_known_manifest(self, filename: str) -> bool:
        return filename.lower() == "package.json"

    def probe(self, plugin_dir: Path) -> dict[str, Any] | None:
        """探测 package.json → 建议 manifest。"""
        if (plugin_dir / "package.json").is_file():
            return {"manifest": "package.json"}
        return None

    def check_available(self) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["node", "--version"], capture_output=True, text=True,
                timeout=10, creationflags=_NO_WINDOW)
            if result.returncode == 0:
                return True, "需要 Node.js 20+（SEA）"
        except Exception:
            pass
        return False, "未检测到 node，请安装 Node.js 20+"

    def validate(self, cfg: dict[str, Any],
                 source_dir: Path) -> list[str]:
        errors = super().validate(cfg, source_dir)
        bundle = cfg.get("bundle", "exe")
        if bundle not in ("exe", "deps"):
            errors.append(f"未知产物模式: {bundle}（exe / deps）")
        manifest = cfg.get("manifest", "")
        if manifest and not self.is_known_manifest(Path(manifest).name):
            errors.append(f"无法识别的依赖清单: {Path(manifest).name}"
                          "（Node.js 编译仅支持 package.json）")
        entry = read_package_json_main(Path(source_dir) / manifest) \
            if manifest else ""
        if not entry:
            errors.append("package.json 缺少 main 入口字段"
                          "（Node.js 编译入口，缺省 index.js）")
        elif not (source_dir / entry).is_file():
            # TS 项目入口为 tsc 产物：构建前不存在，由编译生成（resolve 兜底）
            if not (source_dir / "tsconfig.json").is_file():
                errors.append(f"入口文件不存在: {entry}")
        return errors

    def deduce(self, cfg: dict[str, Any],
                plugin_name: str = "",
                source_dir: Path | None = None) -> list[BuilderItem] | None:
        """manifest 已选 → 推导产物条目。

        bundle=exe（默认）：SEA exe + node_modules + 入口目录；
        bundle=deps：启动脚本 start_node.py（.py 入口）+ node_modules + 入口目录。
        """
        if not cfg.get("manifest") or not plugin_name:
            return None
        items: list[BuilderItem] = []
        if cfg.get("bundle") == "deps":
            items.append(BuilderItem(path="start_node.py", tags=["entry"],
                                     derived=True))
        else:
            items.append(BuilderItem(path=f"{plugin_name}.exe", tags=["entry"],
                                     derived=True))
        items.append(BuilderItem(dir="node_modules", derived=True))
        # 入口所在目录（dist / src …）随产物收集；入口在根则只收入口文件
        if source_dir is not None:
            entry = read_package_json_main(
                source_dir / str(cfg.get("manifest", "")))
            entry_dir = str(Path(entry).parent) if entry else ""
            if entry_dir not in ("", "."):
                items.append(BuilderItem(dir=entry_dir, derived=True))
            elif entry:
                items.append(BuilderItem(path=entry, derived=True))
        return items

    def debug_source_command(self, plugin_dir: Path) -> list[str] | None:
        """node 运行 package.json main 入口；入口缺失返回 None。"""
        entry = read_package_json_main(plugin_dir / "package.json")
        if not entry:
            return None
        return ["node", entry]

    def prod_dir(self, output_dir: Path, plugin_name: str) -> Path | None:
        return output_dir / ".node" / plugin_name

    def run(self, ctx: CompilerContext) -> bool:
        manifest = ctx.cfg.get("manifest", "")
        if not manifest:
            ctx.log.error("依赖清单为空")
            return False
        manifest_path = Path(ctx.source_dir) / manifest
        if not manifest_path.is_file():
            ctx.log.error(f"依赖清单不存在: {manifest_path}")
            return False

        entry = read_package_json_main(manifest_path)
        if not entry:
            ctx.log.error("package.json 缺少 main 入口字段"
                          "（Node.js 编译入口，缺省 index.js）")
            return False

        # 1) npm 安装依赖（产物所需 node_modules 生成于插件目录）
        ctx.log.info(f"依赖来源: {manifest}，npm install ...")
        lock_existed = (ctx.source_dir / "package-lock.json").exists()
        ok = run_logged([*_node_tool("npm"), "install", "--no-audit", "--no-fund"],
                        ctx.log, "npm", cwd=ctx.source_dir,
                        canceller=ctx.canceller)
        if not ok:
            ctx.log.error("依赖安装失败")
            return False
        ctx.log.info("依赖安装完成")

        # 2) TS 项目（tsconfig.json 存在）→ 编译；调试构建用增量 tsc
        if (ctx.source_dir / "tsconfig.json").is_file():
            if ctx.keep_cache:
                # 调试构建：增量编译，tsbuildinfo 缓存放 debug/cache/
                # （对齐 PyInstaller 缓存位置，二次调试编译只重编译变更）
                cache_dir = ctx.output_dir / "cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                build_cmd = [*_node_tool("npx"), "tsc", "--incremental",
                             "--tsBuildInfoFile",
                             str(cache_dir / "tsbuildinfo.json")]
                ctx.log.info("调试构建：增量 tsc 编译（缓存 debug/cache/）")
            else:
                pkg = json.loads(manifest_path.read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
                if isinstance(scripts, dict) and scripts.get("build"):
                    build_cmd = [*_node_tool("npm"), "run", "build"]
                else:
                    build_cmd = [*_node_tool("npx"), "tsc"]
            ctx.log.info(f"编译 TS: {' '.join(build_cmd)}")
            ok = run_logged(build_cmd, ctx.log, "tsc",
                            cwd=ctx.source_dir,
                            canceller=ctx.canceller)
            if not ok:
                ctx.log.error("TS 编译失败")
                return False

        # 3) 产物模式：exe（SEA）或 deps（依赖版）
        prod_dir = ctx.output_dir / ".node" / ctx.plugin_name
        prod_dir.mkdir(parents=True, exist_ok=True)
        if ctx.cfg.get("bundle") == "deps":
            # 依赖版：跳过 SEA，生成 .py 启动脚本作 entry（宿主以 .py 入口
            # 执行，用自带 Python 运行时拉起系统 Node）
            launcher = prod_dir / "start_node.py"
            launcher.write_text(
                _NODE_LAUNCHER.replace("{entry}",
                                       entry.replace(chr(92), "/")),
                encoding="utf-8")
            ctx.log.info("依赖版产物：生成 start_node.py 启动脚本"
                         "（需目标机安装 Node.js）")
        else:
            # 4) 自包含：SEA 三件套（快照 → 复制 node.exe → postject 注入）
            bootstrap = ctx.source_dir / "sea-bootstrap.cjs"
            bootstrap.write_text(
                _SEA_BOOTSTRAP.replace("{entry}",
                                       entry.replace(chr(92), "/")),
                encoding="utf-8")
            sea_config = ctx.source_dir / "sea-config.packer.json"
            sea_config.write_text(json.dumps({
                "main": "sea-bootstrap.cjs",
                "output": "sea-prep.blob",
            }), encoding="utf-8")
            exe_path = prod_dir / f"{ctx.plugin_name}.exe"
            try:
                ok = run_logged(
                    ["node", "--experimental-sea-config",
                     "sea-config.packer.json"],
                    ctx.log, "SEA", cwd=ctx.source_dir,
                    canceller=ctx.canceller)
                if not ok:
                    return False
                node_exe = shutil.which("node")
                if not node_exe:
                    ctx.log.error("未找到 node.exe")
                    return False
                shutil.copy2(node_exe, exe_path)
                ctx.log.info("注入 SEA 引导器...")
                ok = run_logged(
                    [*_node_tool("npx"), "--yes", "postject",
                     str(exe_path), "NODE_SEA_BLOB", "sea-prep.blob",
                     "--sentinel-fuse", _SEA_FUSE],
                    ctx.log, "postject", cwd=ctx.source_dir,
                    canceller=ctx.canceller)
                if not ok:
                    return False
            finally:
                bootstrap.unlink(missing_ok=True)
                sea_config.unlink(missing_ok=True)
                (ctx.source_dir / "sea-prep.blob").unlink(missing_ok=True)

        # 5) 收集产物：node_modules + 入口目录 → prod_dir
        node_modules = ctx.source_dir / "node_modules"
        if node_modules.is_dir():
            shutil.copytree(node_modules, prod_dir / "node_modules",
                            dirs_exist_ok=True)
        entry_dir = Path(entry).parent
        if str(entry_dir) != ".":
            src = ctx.source_dir / entry_dir
            if src.is_dir():
                shutil.copytree(src, prod_dir / entry_dir,
                                dirs_exist_ok=True)
        else:
            src = ctx.source_dir / entry
            if src.is_file():
                shutil.copy2(src, prod_dir / entry)

        # 6) 清理：构建期间生成的 package-lock.json（若原本不存在）
        if not lock_existed:
            (ctx.source_dir / "package-lock.json").unlink(missing_ok=True)
        ctx.log.info(f"构建完成（{'exe' if ctx.cfg.get('bundle') != 'deps' else 'deps'}）")
        return True


# ---------------------------------------------------------------------------
# NoneCompiler：「无」编译系统（合法注册的空操作实现）
# ---------------------------------------------------------------------------

class NoneCompiler(Compiler):
    """「无」编译系统：不探测 / 不推导 / 不编译（阶段 1 空操作）。

    注册为合法编译系统（id 为空串），使 ``get_compiler`` 恒返回实例，
    调用方无需再判 None——deduce/validate/probe 均走基类默认（空/无）。
    """

    id = ""
    label = "无"

    def run(self, ctx: CompilerContext) -> bool:
        return True  # 无阶段 1 工作，直接进入收集


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

COMPILERS: dict[str, Compiler] = {
    "": NoneCompiler(),
    "python": PythonCompiler(),
    "node": NodeCompiler(),
    "command": CommandCompiler(),
}

# 编译选项（GUI 下拉 / config 校验）：("" 无) 优先于具体编译
COMPILER_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "无"),
    ("python", "Python (uv + PyInstaller)"),
    ("node", "Node.js (npm + SEA)"),
    ("command", "自定义命令"),
)


def get_compiler(compile_system: str) -> Compiler:
    """按 id 取编译；空串 / 未知 id 回退「无」编译器（恒非 None）。"""
    return COMPILERS.get(compile_system, COMPILERS[""])
