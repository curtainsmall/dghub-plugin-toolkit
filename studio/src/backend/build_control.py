"""构建取消控制：跨线程终止正在运行的子进程（含进程树）。

构建在后台线程执行、子进程用 Popen 启动；``Canceller`` 记录当前子进程句柄，
主线程调用 :meth:`cancel` 即可硬终止整棵进程树（Windows 用 ``taskkill /T``，
以覆盖 ``shell=True`` 下 ``cmd.exe → 实际命令`` 的孙进程；其余平台回退
``terminate``）。纯逻辑模块，无 GUI 依赖。
"""

from __future__ import annotations

import os
import subprocess
import threading

from backend.winflags import _NO_WINDOW


class Canceller:
    """线程安全的构建取消令牌：取消标志 + 当前子进程句柄。"""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def set_proc(self, proc: subprocess.Popen | None) -> None:
        """登记/注销当前子进程；若取消已先行发生，登记时立即杀掉。"""
        with self._lock:
            self._proc = proc
            if proc is not None and self._event.is_set():
                self._kill(proc)

    def cancel(self) -> None:
        """请求取消：置标志并终止当前子进程树（幂等，可重复调用）。"""
        self._event.set()
        with self._lock:
            if self._proc is not None:
                self._kill(self._proc)

    @staticmethod
    def _kill(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return  # 已结束
        try:
            if os.name == "nt":
                # /T 杀整棵进程树（含 shell=True 下的孙进程），/F 强制
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=_NO_WINDOW)
            else:
                proc.terminate()
        except Exception:
            pass
