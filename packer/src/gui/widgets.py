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


# ---------------------------------------------------------------------------
# 滚轮统一接管：customtkinter CTkScrollableFrame 的原生滚轮回调
# （_mouse_wheel_all）对内容区失效（子控件 master 链不含 canvas——
# 悬停列表内容不滚）且悬停滚动条时方向/范围异常。这里禁用它，
# 由**单一**全局 bind_all 回调按「最近滚动容器」统一处理
# （每实例绑定会导致多回调顺序/去重歧义）。
# ---------------------------------------------------------------------------
_CTK_MOUSE_WHEEL = ctk.CTkScrollableFrame._mouse_wheel_all


def _ctk_mouse_wheel_disabled(self: Any, event: Any) -> None:
    """占位：滚轮统一由 _global_wheel 调度。"""
    return None


ctk.CTkScrollableFrame._mouse_wheel_all = _ctk_mouse_wheel_disabled

_GLOBAL_WHEEL_BOUND = False


def _global_wheel(event: Any) -> None:
    """全局滚轮回调：滚动「事件 widget 向上最近的滚动容器」。

    覆盖 FillScrollable 与内层 CTkScrollableFrame（列表）——内容区
    悬停正确滚动对应容器；滚动条事件由容器局部绑定处理（master 链
    无法归属）。事件标记去重（多容器回调只处理一次）。
    Windows delta（120 的倍数）/ Linux Button-4/5；滚动后 clamp。
    """
    try:
        if getattr(event, "_dgh_scrolled", False):
            return  # 已由滚动条局部绑定等处理
        if isinstance(getattr(event, "widget", None), ctk.CTkScrollbar):
            return
        target: Any = None
        w = getattr(event, "widget", None)
        while w is not None:
            if isinstance(w, ctk.CTkScrollableFrame) \
                    or isinstance(w, FillScrollable):
                target = w
                break
            w = w.master
        if target is None:
            return
        # FillScrollable 用 _canvas；CTkScrollableFrame 用 _parent_canvas
        canvas = getattr(target, "_parent_canvas", None) \
            or getattr(target, "_canvas", None)
        if canvas is None:
            return
        delta = getattr(event, "delta", 0) or 0
        if delta:
            canvas.yview_scroll(int(-delta / 120), "units")
        elif getattr(event, "num", 0) == 4:
            canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", 0) == 5:
            canvas.yview_scroll(1, "units")
        # clamp：scrollregion 更新滞后时防止越界（滚过上下限）
        top, bottom = canvas.yview()
        if top < 0.0:
            canvas.yview_moveto(0.0)
        elif bottom > 1.0:
            canvas.yview_moveto(1.0 - (bottom - top))
        event._dgh_scrolled = True
    except Exception:
        pass


class FillScrollable(ctk.CTkFrame):
    """内容填满视口的滚动容器：内容 ≤ 视口时铺满，内容超高时滚动。

    CTkScrollableFrame 的窗口项尺寸由内部 canvas 锁定（不随父容器
    伸缩），无法实现 fill——这里用 CTkFrame + Canvas + Scrollbar 自控：
    canvas <Configure> 时把内容窗口设为「视口宽 × max(内容, 视口高)」，
    内容始终占满可视区域，超高时出现滚动条。
    用法：``fs = FillScrollable(parent); fs.pack(...)``，内容 grid/pack
    到 ``fs.content``。
    """

    def __init__(self, master: Any, fill_bg: Any = None, **kwargs: Any) -> None:
        # 容器自身 = 全局背景（BG0）：content 的 transparent 会解析为
        # 父背景——若容器用默认主题色，content 会显示多余的深灰层
        kwargs.setdefault("fg_color", BG0)
        super().__init__(master, **kwargs)
        self._scrollbar = ctk.CTkScrollbar(self)
        self._scrollbar.pack(side="right", fill="y")
        # 本容器滚动条：局部绑定滚轮（滚动本容器；master 链不含容器
        # 引用，全局调度无法归属）
        self._scrollbar.bind("<MouseWheel>", self._on_scrollbar_wheel,
                             add=True)
        self._scrollbar.bind("<Button-4>", self._on_scrollbar_wheel,
                             add=True)
        self._scrollbar.bind("<Button-5>", self._on_scrollbar_wheel,
                             add=True)
        # canvas 背景（fill_bg 覆盖默认全局背景——列表容器用 LIST_BG）
        if fill_bg is None:
            bg = BG0[1] if ctk.get_appearance_mode() == "Dark" else BG0[0]
        else:
            bg = fill_bg[1] if ctk.get_appearance_mode() == "Dark" \
                else fill_bg[0]
        self._canvas = ctk.CTkCanvas(self, highlightthickness=0, bg=bg)
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.configure(command=self._canvas.yview)
        # 全局滚轮：首个实例注册**单一** bind_all 回调（后续实例不再
        # 重复绑定——多回调存在顺序/去重歧义；canvas 为 tk 类可 bind_all）
        global _GLOBAL_WHEEL_BOUND
        if not _GLOBAL_WHEEL_BOUND:
            self._canvas.bind_all("<MouseWheel>", _global_wheel, add=True)
            self._canvas.bind_all("<Button-4>", _global_wheel, add=True)
            self._canvas.bind_all("<Button-5>", _global_wheel, add=True)
            _GLOBAL_WHEEL_BOUND = True
        self.content = ctk.CTkFrame(self._canvas, fg_color="transparent")
        self._window = self._canvas.create_window(
            (0, 0), window=self.content, anchor="nw")
        # 内容尺寸变化（条目增减等）也刷新 scrollregion——否则滚轮
        # yview 相对旧范围滚动，视觉上越过上下限
        self.content.bind("<Configure>", self._sync_fill, add=True)
        self._canvas.bind("<Configure>", self._sync_fill, add="+")

    def _on_scrollbar_wheel(self, event: Any) -> None:
        """本容器滚动条上的滚轮：滚动本容器（方向正确 + clamp）。"""
        try:
            delta = getattr(event, "delta", 0) or 0
            if delta:
                self._canvas.yview_scroll(int(-delta / 120), "units")
            elif getattr(event, "num", 0) == 4:
                self._canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", 0) == 5:
                self._canvas.yview_scroll(1, "units")
            top, bottom = self._canvas.yview()
            if top < 0.0:
                self._canvas.yview_moveto(0.0)
            elif bottom > 1.0:
                self._canvas.yview_moveto(1.0 - (bottom - top))
            event._dgh_scrolled = True  # 阻止全局调度重复处理
        except Exception:
            pass


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
