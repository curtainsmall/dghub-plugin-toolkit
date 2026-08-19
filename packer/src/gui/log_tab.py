"""底部全局日志面板 — 构建输出 / 调试输出两个子视图，可折叠。

- 两个子视图（构建输出 / 调试输出）各自独立文本与清空，由双 Logger 分流
- 着色仅限 error / warning / success 三级（红 / 橙 / 绿），其余级别默认色
- 外部工具输出（sep / external 级别）按原样渲染、不加时间戳
- 折叠状态持久化（settings_store.log_panel_open）
"""

import datetime
from typing import Any, Callable

import customtkinter as ctk

from backend import settings_store
from gui.ui_dispatch import ui
from gui.widgets import BG1, BG2

# 仅这三种级别着色；颜色取在浅色/深色文本框背景下均可读的中间色调
# （tkinter tag 只接受单色，无法用 CTk 的 (light, dark) 二元组）。
_LEVEL_COLORS: dict[str, str] = {
    "error":   "#E5484D",   # 红：中断构建 / 校验失败
    "warning": "#D9822B",   # 橙：不中断但需注意
    "success": "#30A46C",   # 绿：最终产物完成
}
# 外部工具相关级别：默认色、无时间戳（分隔头 + 原始输出）
_RAW_LEVELS = ("sep", "external")


class _LogPane(ctk.CTkFrame):
    """单个日志子视图：只读文本 + 级别着色。"""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(master, fg_color=BG2, corner_radius=6, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._text = ctk.CTkTextbox(
            self, wrap="word", font=("Consolas", 11), state="disabled",
            fg_color=BG2)
        self._text.grid(row=0, column=0, sticky="nsew")
        for level, color in _LEVEL_COLORS.items():
            self._text.tag_config(level, foreground=color)

    def emit(self, msg: str, level: str = "info") -> None:
        """Append a leveled message; error/warning/success 着色，其余默认色。"""
        if level in _RAW_LEVELS:
            line = f"{msg}\n"          # 外部原样 / 分隔头：不加时间戳
        else:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}\n"
        self._text.configure(state="normal")
        if level in _LEVEL_COLORS:
            self._text.insert("end", line, level)
        else:
            self._text.insert("end", line)
        self._text.see("end")
        self._text.configure(state="disabled")
        self.update_idletasks()

    def write(self, msg: str) -> None:
        """兼容入口：无级别文本按普通进度（info）记录。"""
        self.emit(msg, "info")

    def clear(self) -> None:
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


class LogTab(ctk.CTkFrame):
    """底部全局日志面板：构建输出 / 调试输出两个子视图，可折叠。"""

    def __init__(self, master: Any, **kwargs: Any) -> None:
        # 整体为第一层浮动卡片（BG1），浮在全局背景（BG0）上
        super().__init__(master, fg_color=BG1, corner_radius=8, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 折叠头：点击切换（▾/▸ 日志）；右侧清空当前子视图
        self._open = bool(settings_store.get_state("log_panel_open", True))
        self._toggle_btn = ctk.CTkButton(
            self, text="", anchor="w", height=28,
            fg_color="transparent", hover_color=("gray80", "gray30"),
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._toggle)
        self._toggle_btn.grid(row=0, column=0, sticky="ew",
                              padx=(10, 0), pady=(6, 0))
        self._clear_btn = ctk.CTkButton(
            self, text="清空", width=60, height=26,
            font=ctk.CTkFont(size=11), command=self._clear_current)
        self._clear_btn.grid(row=0, column=1, sticky="e",
                             padx=(0, 10), pady=(6, 0))

        # 两个子视图 tab：构建输出 / 调试输出
        self._tabs = ctk.CTkTabview(self, anchor="nw", height=140)
        self._tabs.grid(row=1, column=0, columnspan=2, sticky="nsew",
                        padx=10, pady=(2, 8))
        self._build_pane = _LogPane(self._tabs.add("构建输出"))
        self._debug_pane = _LogPane(self._tabs.add("调试输出"))
        self._build_pane.pack(fill="both", expand=True)
        self._debug_pane.pack(fill="both", expand=True)

        self._refresh_header()

    # ------------------------------------------------------------------
    # 双 Logger 分流入口
    # ------------------------------------------------------------------

    def emit_build(self, msg: str, level: str = "info") -> None:
        """构建/校验/自动填充等 → 构建输出（线程安全：回主线程渲染）。"""
        ui(lambda: self._build_pane.emit(msg, level))

    def emit_debug(self, msg: str, level: str = "info") -> None:
        """调试构建/运行等 → 调试输出（线程安全：回主线程渲染）。"""
        ui(lambda: self._debug_pane.emit(msg, level))

    # ------------------------------------------------------------------
    # 折叠 / 清空
    # ------------------------------------------------------------------

    def _refresh_header(self) -> None:
        self._toggle_btn.configure(text=("▾ 日志" if self._open else "▸ 日志"))

    def _toggle(self) -> None:
        self._open = not self._open
        settings_store.save_state_key("log_panel_open", self._open)
        if self._open:
            self._tabs.grid()
        else:
            self._tabs.grid_remove()
        self._refresh_header()

    def _clear_current(self) -> None:
        cur = self._tabs.get()
        if cur == "构建输出":
            self._build_pane.clear()
        else:
            self._debug_pane.clear()
