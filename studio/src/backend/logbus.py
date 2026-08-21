"""结构化日志：调用点显式声明级别，UI 只按级别渲染，不再解析文本前缀。

级别语义：
- ``error`` / ``warning`` / ``success``：UI 着色（红 / 橙 / 绿）。success 仅
  用于**最终产物**完成，中间步骤用 ``info``。
- ``info``：普通进度（默认色）。
- ``detail``：从属细节，如路径、版本（默认色）。
- ``sep`` / ``external``：外部工具（uv/pip/PyInstaller/pre-build）的分隔头与
  原始输出（默认色，无时间戳）。

纯逻辑模块，无 GUI 依赖：Logger 只把 ``(text, level)`` 交给注入的 sink。
"""

from __future__ import annotations

from typing import Callable, Iterable

# UI 需要着色的级别（其余级别一律默认色）
COLORED_LEVELS = ("error", "warning", "success")
# 无时间戳、按原样渲染的外部相关级别
RAW_LEVELS = ("sep", "external")


class Logger:
    """把 ``(text, level)`` 推给 UI sink；调用点用语义方法声明级别。"""

    def __init__(self, sink: Callable[[str, str], None]) -> None:
        self._sink = sink

    def error(self, msg: str) -> None:
        self._sink(msg, "error")

    def warning(self, msg: str) -> None:
        self._sink(msg, "warning")

    def success(self, msg: str) -> None:
        self._sink(msg, "success")

    def info(self, msg: str) -> None:
        self._sink(msg, "info")

    def detail(self, msg: str) -> None:
        self._sink(msg, "detail")

    def separator(self, title: str) -> None:
        """输出一条分节标题（默认色、无时间戳），用于分隔多次构建。"""
        self._sink(f"━━━ {title} ━━━", "sep")

    def external(self, source: str, lines: Iterable[str],
                 returncode: int | None = None) -> None:
        """输出一段外部工具原始输出，前后以来源分隔头包裹。

        Args:
            source: 来源标签（如 "uv" / "pip" / "PyInstaller" / "pre-build"）。
            lines: 外部命令的 stdout/stderr 行（已按行拆分）。
            returncode: 命令退出码；非 0 时在收尾分隔头标注。
        """
        self._sink(f"─── {source} ───", "sep")
        empty = True
        for line in lines:
            empty = False
            self._sink(line, "external")
        if empty:
            self._sink("（无输出）", "external")
        if returncode:
            self._sink(f"─── {source} 结束（退出码 {returncode}）───", "sep")
        else:
            self._sink(f"─── {source} 结束 ───", "sep")
