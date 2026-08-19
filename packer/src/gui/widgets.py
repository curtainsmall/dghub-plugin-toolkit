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

# 分层配色（(light, dark) 二元组，全局统一）：
#   BG0 全局背景（最底层）→ BG1 第一层组件（浮动卡片）→
#   LIST_BG 列表容器（卡片内凹陷区）→ 条目条纹（STRIP_A/B 交替）
BG0 = ("#E4E4E4", "#1E1E1E")
BG1 = ("#F7F7F7", "#2E2E2E")
LIST_BG = ("#ECECEC", "#262626")
STRIP_A = ("#FAFAFA", "#343434")
STRIP_B = ("#F0F0F0", "#2A2A2A")


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


class FillScrollable(ctk.CTkFrame):
    """内容填满视口的滚动容器：内容 ≤ 视口时铺满，内容超高时滚动。

    CTkScrollableFrame 的窗口项尺寸由内部 canvas 锁定（不随父容器
    伸缩），无法实现 fill——这里用 CTkFrame + Canvas + Scrollbar 自控：
    canvas <Configure> 时把内容窗口设为「视口宽 × max(内容, 视口高)」，
    内容始终占满可视区域，超高时出现滚动条。
    用法：``fs = FillScrollable(parent); fs.pack(...)``，内容 grid/pack
    到 ``fs.content``。
    """

    def __init__(self, master: Any, **kwargs: Any) -> None:
        # 容器自身 = 全局背景（BG0）：content 的 transparent 会解析为
        # 父背景——若容器用默认主题色，content 会显示多余的深灰层
        kwargs.setdefault("fg_color", BG0)
        super().__init__(master, **kwargs)
        self._scrollbar = ctk.CTkScrollbar(self)
        self._scrollbar.pack(side="right", fill="y")
        # canvas 背景必须显式 = 全局背景（默认白色会露出白边框）
        bg = BG0[1] if ctk.get_appearance_mode() == "Dark" else BG0[0]
        self._canvas = ctk.CTkCanvas(self, highlightthickness=0, bg=bg)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.configure(command=self._canvas.yview)
        self.content = ctk.CTkFrame(self._canvas, fg_color="transparent")
        self._window = self._canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        self._canvas.bind("<Configure>", self._sync_fill, add="+")

    def _sync_fill(self, _event: Any = None) -> None:
        try:
            vw = self._canvas.winfo_width()
            vh = self._canvas.winfo_height()
            ch = max(self.content.winfo_reqheight(), vh)
            self._canvas.itemconfigure(self._window, width=vw, height=ch)
            self.content.configure(width=vw, height=ch)
            self._canvas.configure(
                scrollregion=(0, 0, vw, max(ch, vh)))
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
