"""线程安全 UI 调度：后台线程提交，主线程轮询执行。

Python 3.14 的 tkinter 禁止跨线程 Tcl 调用（``after`` / ``configure``
均抛 ``RuntimeError: main thread is not in main loop``）——后台线程
（构建 / 调试 / 预检）的 UI 更新必须经此调度回主线程执行。
"""

import queue
from typing import Any, Callable

_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
_root: Any = None


def init(root: Any) -> None:
    """App 启动时初始化（绑定主窗口并启动轮询循环）。"""
    global _root
    _root = root
    _root.after(50, _poll)


def ui(fn: Callable[[], None]) -> None:
    """线程安全：请求在主线程执行 fn（任意线程可调用）。"""
    _queue.put(fn)


def _poll() -> None:
    while True:
        try:
            fn = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception:
            pass  # 主线程内异常不阻断轮询（UI 更新失败不致命）
    try:
        _root.after(50, _poll)
    except Exception:
        pass
