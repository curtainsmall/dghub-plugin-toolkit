"""Build plugin as standalone .exe via PyInstaller.

Handles both interpreter mode and frozen (Packer exe) mode by delegating to
system Python for the actual PyInstaller invocation.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from backend.logbus import Logger
from backend.build_control import Canceller
from backend.winflags import _NO_WINDOW


def _get_python_exe() -> list[str]:
    """Return [python_exe] suitable for subprocess, handles frozen exe.

    冻结（打包 exe）运行时进程内没有可用的 Python 解释器，改用系统 Python。
    """
    if not getattr(sys, "frozen", False):
        return [sys.executable]
    for cmd in [["py", "-3"], ["py"], ["python"], ["python3"]]:
        try:
            result = subprocess.run(
                cmd + ["-c", "import sys; print(sys.executable)"],
                capture_output=True, text=True, timeout=5,
                creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                stripped = result.stdout.strip()
                if stripped:
                    return [stripped]
        except Exception:
            continue
    return [sys.executable]  # fallback


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read_entry(plugin_dir: Path) -> str:
    """Read manifest.json, return entry filename (default 'main.py')."""
    manifest_path = plugin_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = data.get("entry", "main.py")
            if entry:
                return entry
        except (json.JSONDecodeError, OSError):
            pass
    return "main.py"


def _scan_toplevel_packages(dep_dir: Path | None) -> tuple[list[str], list[str]]:
    """列出依赖目录中的顶层包，返回 (常规包, 命名空间包)。

    仅列目录结构，不解析任何依赖声明；结果供 PyInstaller
    ``--collect-data`` / ``--copy-metadata`` / ``--add-data`` 收集包内
    数据文件、元数据与源码（litellm 等带数据文件的依赖包，PyInstaller
    默认只收集 .py 代码；tiktoken_ext 等命名空间插件包需整体复制源码）。
    """
    if not dep_dir or not dep_dir.is_dir():
        return [], []
    packages: list[str] = []
    ns_packages: list[str] = []
    for d in dep_dir.iterdir():
        if not d.is_dir() or d.name.startswith("."):
            continue
        if d.name.endswith(".dist-info") or d.name.endswith(".data"):
            continue
        if (d / "__init__.py").is_file():
            packages.append(d.name)
        elif any(d.glob("*.py")):
            # 命名空间包（无 __init__.py）：插件发现依赖文件系统遍历，
            # 需整体复制源码（含 .py）而非仅数据文件
            ns_packages.append(d.name)
    return sorted(packages), sorted(ns_packages)


_IMPORT_RE = re.compile(r"^(?:from|import)\s+([a-zA-Z_]\w*(?:\.\w+)*)",
                        re.MULTILINE)


def _scan_ns_hidden_imports(dep_dir: Path, ns_pkg: str,
                            top_packages: set[str]) -> list[str]:
    """扫描命名空间包 .py 的 import 语句，返回需隐藏导入的模块路径。

    命名空间插件包（tiktoken_ext 等）以源码文件形式进产物，其 import 的
    宿主包子模块（tiktoken.load 等）不在入口 import 图中——须显式收集。
    """
    hidden: list[str] = []
    for py in (dep_dir / ns_pkg).glob("*.py"):
        src = py.read_text(encoding="utf-8", errors="ignore")
        for m in _IMPORT_RE.finditer(src):
            mod = m.group(1)
            # 仅子模块路径需显式收集（顶层模块由常规收集机制处理）
            if ("." in mod and mod.split(".", 1)[0] in top_packages
                    and mod not in hidden):
                hidden.append(mod)
    return hidden


def _check_pyinstaller(py_exe: list[str], logger: Logger) -> bool:
    """Verify PyInstaller is available before starting the build.

    Runs ``python -m PyInstaller --version``. Returns True on success,
    otherwise logs a clear, actionable message and returns False.
    """
    try:
        result = subprocess.run(
            py_exe + ["-m", "PyInstaller", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        logger.error("未找到 Python 解释器，无法调用 PyInstaller")
        return False
    except Exception as exc:
        logger.error(f"检测 PyInstaller 失败: {exc}")
        return False
    if result.returncode != 0:
        logger.error("未检测到 PyInstaller，请在构建环境执行 "
                     "pip install pyinstaller")
        return False
    logger.detail(f"PyInstaller 版本: {result.stdout.strip()}")
    return True


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def build_plugin_exe(
    plugin_dir: str,
    logger: Logger | None = None,
    output_dir: str = "",
    source_dir: str = "",
    entry: str = "",
    dep_dir: str = "",
    canceller: Canceller | None = None,
) -> bool:
    """Build a self-contained .exe from a DGHub plugin directory (onedir).

    Args:
        plugin_dir: Absolute path to plugin root (where .dghub-sdk lives).
        source_dir: Absolute path to source code root (defaults to plugin_dir).
        logger: 可选日志器；缺省时静默。
        output_dir: Output directory for the onedir product.
        entry: 入口文件（相对 source_dir）；缺省时回退读插件根 manifest.json。
        dep_dir: 清单依赖安装目录（.deps）；存在时经 --paths 喂给 PyInstaller。
        canceller: 取消令牌。

    Returns:
        True on success.
    """
    log = logger or Logger(lambda _msg, _level: None)
    pdir = Path(plugin_dir).resolve()
    sdir = Path(source_dir).resolve() if source_dir else pdir
    if not pdir.is_dir():
        log.error(f"插件目录不存在: {pdir}")
        return False

    if not entry:
        entry = _read_entry(pdir)
    entry_path = sdir / entry
    if not entry_path.is_file():
        log.error(f"入口文件不存在: {entry_path}")
        return False

    out_dir = Path(output_dir).resolve() if output_dir else pdir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    exe_name = pdir.name
    # onedir 产物：out_dir/.pyi/<name>/（exe + _internal/，与打包目标目录隔离）
    pyi_dir = out_dir / ".pyi"
    exe_output = pyi_dir / exe_name / f"{exe_name}.exe"
    cache_dir = out_dir / "cache"

    log.info(f"打包插件 exe: {pdir}")
    log.detail(f"入口: {entry}")

    # ---- build PyInstaller command ----
    py_exe = _get_python_exe()
    if not _check_pyinstaller(py_exe, log):
        return False
    cmd = py_exe + [
        "-m", "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name", exe_name,
        "--distpath", str(pyi_dir),
        "--workpath", str(cache_dir / "pyi_build"),
        "--specpath", str(cache_dir),
    ]


    # 依赖目录（清单下载产物 .deps，存在才加）
    deps_dir = Path(dep_dir) if dep_dir else None
    if deps_dir and deps_dir.is_dir() and any(deps_dir.iterdir()):
        cmd += ["--paths", str(deps_dir)]
        log.detail(f"清单依赖路径: {deps_dir}")

    # 依赖数据文件与元数据：.deps 所有顶层包逐一收集（litellm 等带数据
    # 文件的包；PyInstaller 默认只收 .py，数据文件须显式声明）
    dep_pkgs, ns_pkgs = _scan_toplevel_packages(deps_dir)
    for pkg in dep_pkgs:
        cmd += ["--collect-data", pkg]
        if any(deps_dir.glob(f"{pkg}-*.dist-info")):
            cmd += ["--copy-metadata", pkg]
    if dep_pkgs:
        log.detail(f"依赖数据收集: {', '.join(dep_pkgs)}")

    # 命名空间包（tiktoken_ext 等插件包）：整体复制源码目录——插件发现
    # 机制依赖文件系统遍历（pkgutil.iter_modules），归档内的模块不可见
    top_packages = set(dep_pkgs + ns_pkgs)
    for pkg in ns_pkgs:
        cmd += ["--add-data", f"{deps_dir / pkg};{pkg}"]
        for mod in _scan_ns_hidden_imports(deps_dir, pkg, top_packages):
            cmd += ["--hidden-import", mod]
    if ns_pkgs:
        log.detail(f"命名空间包复制: {', '.join(ns_pkgs)}")

    # PyInstaller 子进程环境：.deps 注入 PYTHONPATH——spec 执行时
    # collect_data_files / copy_metadata 需经 sys.path 定位依赖包
    build_env = None
    if dep_pkgs:
        prev = os.environ.get("PYTHONPATH", "")
        build_env = {**os.environ,
                     "PYTHONPATH": str(deps_dir.resolve())
                     + (os.pathsep + prev if prev else "")}

    # 项目根（散装单文件模块：`import utils` 命中 source_dir/utils.py）
    cmd += ["--paths", str(sdir)]
    log.detail(f"项目根路径: {sdir}")

    # entry
    cmd.append(str(entry_path))

    log.info("运行 PyInstaller ...")
    log.detail(f"工作目录: {pdir}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=pdir,
            env=build_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_NO_WINDOW,
        )
    except FileNotFoundError:
        log.error("未找到 Python 解释器，无法运行 PyInstaller")
        return False
    except Exception as exc:
        log.error(f"启动 PyInstaller 失败: {exc}")
        return False

    if canceller is not None:
        canceller.set_proc(proc)
    try:
        out, _ = proc.communicate()
    finally:
        if canceller is not None:
            canceller.set_proc(None)

    if canceller is not None and canceller.cancelled:
        log.warning("PyInstaller 已取消")
        return False

    # PyInstaller 输出：失败时以来源块记录末尾若干行
    if proc.returncode != 0:
        log.error(f"PyInstaller 构建失败（退出码 {proc.returncode}）")
        stderr_tail = (out or "").strip().splitlines()[-10:]
        log.external("PyInstaller", stderr_tail, proc.returncode)
        return False

    if not exe_output.is_file():
        log.error(f"未生成 exe: {exe_output}")
        return False

    size_kb = exe_output.stat().st_size / 1024
    log.info(f"exe 构建产物: {exe_output} ({size_kb:.1f} KB)")
    return True
