"""调试支撑：DGHub 本机探测、常驻子进程运行、调试构建产物定位。

「调试」tab 的后端逻辑：不接触前端；进程输出经 logbus 进日志 tab。
"""

import json
import socket
import subprocess
import urllib.request
from pathlib import Path

from backend.build_control import Canceller
from backend.logbus import Logger
from backend.pipeline import run_build
from backend.winflags import _NO_WINDOW

# 默认 DGHub 服务端地址（SDK 的 DGHUB_HOST/PORT 默认值同源）
_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 8000


def detect_dghub(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT,
                 timeout: float = 0.5) -> bool:
    """本机 DGHub 服务端连通性探测（仅 socket 握手，不做协议交互）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_token(host: str = _DEFAULT_HOST, port: int = _DEFAULT_PORT,
                timeout: float = 2.0) -> str | None:
    """从 DGHub 拉取会话 token（GET /api/plugins/_session_token）。"""
    try:
        url = f"http://{host}:{port}/api/plugins/_session_token"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if isinstance(data, dict):
                return data.get("token")
            return body.strip()
    except Exception:
        return None


def run_process(cmd: list[str], cwd: Path, env: dict, logger: Logger,
                source: str,
                canceller: Canceller | None = None) -> int:
    """启动常驻子进程，stdout/stderr 逐行送日志（external 块）；返回退出码。

    可取消：``canceller.cancel()`` 后终止进程树（Windows ``taskkill /T``）。
    行按块冲刷（满 20 行或遇空行），兼顾流式可见与 external 分块展示。
    """
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=cwd, env=env,
            creationflags=_NO_WINDOW)
    except FileNotFoundError:
        logger.error(f"命令不存在: {cmd}")
        return -1
    if canceller is not None:
        canceller.set_proc(proc)

    lines: list[str] = []

    def _flush() -> None:
        if lines:
            logger.external(source, list(lines), None)
            lines.clear()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if canceller is not None and canceller.cancelled:
                proc.kill()
                break
            lines.append(line.rstrip("\r\n"))
            if len(lines) >= 20:
                _flush()
        _flush()
        returncode = proc.wait()
    finally:
        if canceller is not None:
            canceller.set_proc(None)
    if canceller is not None and canceller.cancelled:
        logger.warning(f"{source} 已停止")
    return returncode


def build_for_debug(ctx, manifest_data: dict) -> Path | None:
    """调试构建：no_zip 强制 folder（与项目发布目标配置无关，产物需立即运行）。

    ctx.output_dir 已由调用方组装为 ``plugin_dir/debug/``；本函数只临时覆盖
    builder 的 no_zip（构建后还原，不修改项目配置）。返回产物文件夹
    ``plugin_dir/debug/<插件名>/``；失败返回 None。
    """
    builder = ctx.builder
    old_no_zip = builder.get_no_zip()
    builder.set_no_zip(True)
    try:
        artifact = run_build(ctx, manifest_data)
    finally:
        builder.set_no_zip(old_no_zip)
    return artifact


def locate_debug_entry(ctx, artifact: Path) -> Path | None:
    """产物文件夹内定位插件入口。

    Python 编译 = ``<插件名>.exe``；其余编译系统 = 打包内容 entry 条目
    （arc 相对插件根，落在产物文件夹内）。
    """
    if ctx.compile_system == "python":
        exe = artifact / f"{ctx.plugin_name}.exe"
        return exe if exe.is_file() else None
    item = ctx.builder.entry_item()
    if item is not None and item.path is not None:
        p = artifact / item.path
        return p if p.exists() else None
    return None
