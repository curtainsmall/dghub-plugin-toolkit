"""GUI 共享组件：跨 tab 复用的小部件与样式辅助（消除重复定义）。"""

from typing import Any

import customtkinter as ctk


class ToolTip:
    """悬停提示：为控件绑定进入/离开事件，显示轻量气泡。"""

    def __init__(self, widget: Any, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: Any | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: Any = None) -> None:
        if self._tip is not None:
            return
        import tkinter as tk
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self._tip, text=self._text, background="#333333",
                 foreground="white", padx=6, pady=2).pack()

    def _hide(self, _event: Any = None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def reset_entry_border(entry: ctk.CTkEntry) -> None:
    """将输入框恢复为主题默认边框（清除错误红框，而非抹成无边框）。"""
    entry.configure(
        border_width=ctk.ThemeManager.theme["CTkEntry"]["border_width"],
        border_color=ctk.ThemeManager.theme["CTkEntry"]["border_color"])


def center_dialog(child: ctk.CTkToplevel, parent_win: Any) -> None:
    """将子对话框居中于父窗口，并限制在主窗口边界内。"""
    child.update_idletasks()
    pw = parent_win.winfo_width()
    ph = parent_win.winfo_height()
    px = parent_win.winfo_x()
    py = parent_win.winfo_y()
    cw = child.winfo_reqwidth()
    ch = child.winfo_reqheight()
    if pw > 0 and ph > 0:
        x = px + (pw - cw) // 2
        y = py + (ph - ch) // 2
        # clamp：对话框始终落在主窗口边界内
        x = max(px, min(x, px + pw - cw))
        y = max(py, min(y, py + ph - ch))
        child.geometry(f"+{x}+{y}")
