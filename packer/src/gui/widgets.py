"""GUI 共享组件：跨 tab 复用的小部件与样式辅助（消除重复定义）。"""

import ctypes
import sys
import tkinter.font as tkfont
from pathlib import Path
from typing import Any

import customtkinter as ctk

# Font Awesome 6 Free（SIL OFL 1.1），随 Packer 分发：
# 冻结态 _MEIPASS/fontawesome/，源码态包内 assets/fontawesome/
_FA_FILENAME = "fa-solid-900.ttf"
_ICON_FAMILY: str | None | bool = False   # False = 尚未探测


def _fa_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass) / "fontawesome" / _FA_FILENAME
    return (Path(__file__).resolve().parent
            / "assets" / "fontawesome" / _FA_FILENAME)


def load_icon_font() -> str | None:
    """加载 Font Awesome 图标字体，返回可用 family 名；失败返回 None。

    Windows：AddFontResourceExW 私有注册（FR_PRIVATE，不污染系统）；
    其他平台依赖系统已安装的 Font Awesome。结果进程内缓存。
    """
    global _ICON_FAMILY
    if _ICON_FAMILY is not False:
        return _ICON_FAMILY if isinstance(_ICON_FAMILY, str) else None
    # 系统已装 Font Awesome（Linux/macOS 常见）→ 直接用
    for family in tkfont.families():
        if "Font Awesome" in family:
            _ICON_FAMILY = family
            return family
    path = _fa_path()
    if path.is_file() and sys.platform == "win32":
        try:
            # FR_PRIVATE = 0x10：仅本进程可见，进程退出自动卸载
            if ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0) != 0:
                for family in tkfont.families():
                    if "Font Awesome" in family:
                        _ICON_FAMILY = family
                        return family
        except Exception:
            pass
    _ICON_FAMILY = None
    return None


def icon_font(size: int = 14) -> ctk.CTkFont:
    """返回 Font Awesome 图标字体；字体不可用时回退默认字体。"""
    family = load_icon_font()
    if family:
        return ctk.CTkFont(family=family, size=size)
    return ctk.CTkFont(size=size)


class FillScrollable(ctk.CTkScrollableFrame):
    """内容填满视口的滚动容器：内容 ≤ 视口时铺满，内容超高时滚动。

    CTkScrollableFrame 的内容按自然尺寸（canvas 窗口 anchor=nw 不拉伸）
    ——本类在 canvas <Configure> 时把内容框架最小尺寸同步为视口，
    实现「fill + 可滚动」：页面内容始终占满可视区域，超高时出现滚动条。
    用法：``fs = FillScrollable(parent); fs.pack(...)``，内容 grid/pack
    到 ``fs.content``（不要直接挂到 fs 上）。
    """

    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True)
        self._parent_canvas.bind("<Configure>", self._sync_fill, add="+")

    def _sync_fill(self, _event: Any = None) -> None:
        try:
            vw = self._parent_canvas.winfo_width()
            vh = self._parent_canvas.winfo_height()
            self.content.configure(
                width=max(self.content.winfo_reqwidth(), vw),
                height=max(self.content.winfo_reqheight(), vh))
        except Exception:
            pass


class ToolTip:
    """悬停提示：为控件绑定进入/离开事件，显示轻量气泡。"""

    def __init__(self, widget: Any, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: Any | None = None
        self._label: Any | None = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def set_text(self, text: str) -> None:
        """更新提示文本；气泡正在显示时即时刷新。"""
        self._text = text
        if self._tip is not None and self._label is not None:
            self._label.configure(text=text)

    def _show(self, _event: Any = None) -> None:
        if self._tip is not None:
            return
        import tkinter as tk
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tk.Toplevel(self._widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._label = tk.Label(self._tip, text=self._text, background="#333333",
                               foreground="white", padx=6, pady=2,
                               justify="left")
        self._label.pack()

    def _hide(self, _event: Any = None) -> None:
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
            self._label = None


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
