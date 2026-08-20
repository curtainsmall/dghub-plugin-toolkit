"""Build tab — 编译设置 + 打包内容与发布选项（纯 GUI 工具的单视图构建页）。

- 编译设置：内嵌 CompileTab（直接平铺）——编译系统 / 依赖清单 /
  产物模式；设置变化自动重新填充 deduce 产物条目
- 打包内容：统一文件选择列表（文件 / 目录 / 规则三种条目；入口由
  编译系统 deduce 自动生成，不手动标记）
  +「添加文件」/「添加目录」（常规系统选择器）+「添加规则」
- 发布选项：输出固定为 .zip 分发包 + 预览树（输出目录在顶部栏）
"""

from pathlib import Path
from dataclasses import dataclass
from tkinter import filedialog
from tkinter import ttk
from typing import Any, Callable

import customtkinter as ctk

from backend.builder import (BuildError, Builder, ItemKind,
                             evaluate_pattern)
from backend.packaging import pack_suffix
from backend.project_manager import ProjectManager
from gui.compile_tab import CompileTab
from gui.widgets import (BG0, BG1, LIST_BG, STRIP_A, STRIP_B,
                         FillScrollable, ToolTip)

# 右栏各行统一的前导标签宽度（像素）
_LABEL_W = 92


@dataclass
class PreviewItem:
    """产物内容条目（来源无关：手动/编译产物/规则/声明）。

    - ``kind="file"``：包内文件（``source`` 存在时为实际文件，
      否则为编译产物声明——未构建）
    - ``kind="dir"``：目录声明（编译产物目录，未展开）
    - ``kind="missing"``：声明但缺失的条目
    """

    arc: str                       # 包内相对路径（posix）
    kind: str = "file"             # "file" | "dir" | "missing"
    source: Path | None = None     # 源文件（file 且实际存在时）
    derived: bool = False          # 编译产物来源
    entry: bool = False            # 入口

# 条目类型徽章样式：(背景, 前景) 按浅/深模式，区分文件/目录/规则
_KIND_STYLES = {
    "file": (("#DCE7FB", "#2E4A7A"), "文件"),
    "dir": (("#E9E2F8", "#4A3A6A"), "目录"),
    "pattern": (("#F8E8D8", "#6A4A2A"), "规则"),
}

# 标签徽章样式：标签 → ((bg, fg), 显示名)
_TAG_STYLES = {
    "entry": (("#4CAF50", "#2E7D32"), "入口"),
    "manifest": (("#F5C518", "#B8860B"), "清单"),
}



class BuildTab(ctk.CTkFrame):
    """构建页：编译设置 / 包名 / 打包内容 / 发布选项 / 预览。"""
    def __init__(self, master: Any,
                 on_compile_changed: Callable[[], None] | None = None,
                 on_error_cleared: Callable[[], None] | None = None,
                 on_build_clicked: Callable[[], None] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(master, fg_color=BG0, **kwargs)
        self._pm: ProjectManager | None = None
        self._plugin_dir: str | None = None
        self._loading = False
        self._enabled = False
        self._on_compile_changed = on_compile_changed
        self._on_error_cleared = on_error_cleared
        self._on_build_clicked = on_build_clicked
        self._controls: list[Any] = []
        self._error_rels: set[str] = set()  # 校验失败的条目相对路径
        self._area_error: str = ""          # 区域级错误（如缺少入口）
        self._builder_obj: Builder | None = None  # 持久的 Builder 实例（含 deduced 视图）

        self._build_ui()
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        for w in self._controls:
            try:
                w.configure(state=state)
            except Exception:
                pass
        self._compile_view._set_enabled(enabled)

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # 页面级滚动（内容填满视口，日志面板压缩时超高内容可滚动）
        scroll = FillScrollable(self)
        scroll.pack(fill="both", expand=True)
        c = scroll.content
        # 第一层浮动卡片（BG1）：tab 全部内容包在一个 frame 中，
        # 浮在全局背景（BG0）上；内部双栏透明（同 BG1，无间隙）
        main_card = ctk.CTkFrame(c, fg_color=BG1, corner_radius=8)
        main_card.pack(fill="both", expand=True, padx=8, pady=8)
        main_card.grid_columnconfigure(0, weight=3)
        main_card.grid_columnconfigure(1, weight=2)
        main_card.grid_rowconfigure(0, weight=1)

        # ---- 左栏：编译设置 + 打包内容 + 发布 ----
        left = ctk.CTkFrame(main_card, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 5))
        left.grid_columnconfigure(1, weight=1)

        # 编译设置（完全平铺：编译系统 / 依赖清单 / 产物模式，
        # 与下方区块同背景无分组色块）
        self._compile_view = CompileTab(
            left, fg_color="transparent",
            on_changed=self._on_compile_inner_changed)
        self._compile_view.grid(row=0, column=0, columnspan=4,
                                sticky="ew", padx=0)

        # 包名（自定义输出包名；留空 = 自动：插件目录名）
        ctk.CTkLabel(left, text="包名", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=1, column=0, padx=10, pady=(16, 5), sticky="w")
        self._name_entry = ctk.CTkEntry(
            left, placeholder_text="留空使用插件目录名",
            font=ctk.CTkFont(size=11))
        self._name_entry.grid(row=1, column=1, columnspan=2, sticky="ew",
                              padx=(5, 10), pady=(16, 5))
        self._name_entry.bind("<FocusOut>", lambda _: self._save_packer_name())
        self._name_entry.bind("<Return>", lambda _: self._save_packer_name())
        # CTkEntry 6.0.0 初始 _is_focused=True 导致 placeholder 不激活；
        # 统一修正为 False（等价 5.x 默认行为）
        self._name_entry._is_focused = False
        self._controls.append(self._name_entry)
        # 按产物模式自动加后缀（exe → -self_contained / deps → -dependent，
        # 后缀文本可在设置页自定义）
        self._auto_suffix_var = ctk.BooleanVar(value=False)
        self._auto_suffix_check = ctk.CTkCheckBox(
            left, text="按产物模式加后缀",
            variable=self._auto_suffix_var,
            command=self._on_auto_suffix_toggled)
        self._auto_suffix_check.grid(row=1, column=3, sticky="w",
                                     padx=(5, 10), pady=(16, 5))
        self._controls.append(self._auto_suffix_check)

        # 打包内容：添加文件/目录/规则 = 系统选择器入口
        ctk.CTkLabel(left, text="打包内容", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=2, column=0, padx=10, pady=(0, 5), sticky="w")
        add_frame = ctk.CTkFrame(left, fg_color="transparent")
        add_frame.grid(row=2, column=1, sticky="w", padx=(5, 0), pady=(0, 5))
        file_btn = ctk.CTkButton(add_frame, text="添加文件", width=90,
                                 command=self._add_files)
        file_btn.pack(side="left")
        dir_btn = ctk.CTkButton(add_frame, text="添加目录", width=90,
                                command=self._add_dir)
        dir_btn.pack(side="left", padx=(5, 0))
        rule_btn = ctk.CTkButton(add_frame, text="添加规则", width=90,
                                 command=self._add_rule)
        rule_btn.pack(side="left", padx=(5, 0))
        self._controls.extend([file_btn, dir_btn, rule_btn])

        # 添加提示（如项目根外文件被跳过），有内容才显示
        self._add_hint_lbl = ctk.CTkLabel(
            left, text="", font=ctk.CTkFont(size=11),
            text_color="#FF4444", anchor="w")
        self._add_hint_lbl.grid(row=3, column=1, columnspan=3, sticky="w",
                                padx=5)
        self._add_hint_lbl.grid_remove()

        # 条目列表（卡片内凹陷区：LIST_BG，条目斑马条纹；
        # FillScrollable 统一滚动实现）
        self._item_list = FillScrollable(left, fill_bg=LIST_BG)
        self._item_list.grid(row=4, column=0, columnspan=4, sticky="nsew",
                             padx=5, pady=5)
        left.grid_rowconfigure(4, weight=1)
        self._controls.append(self._item_list)

        # 区域级错误提示（如打包内容为空 / 缺少入口）
        self._area_err_lbl = ctk.CTkLabel(
            left, text="", font=ctk.CTkFont(size=11),
            text_color="#FF4444", anchor="w")
        self._area_err_lbl.grid(row=5, column=1, columnspan=3, sticky="w",
                                padx=5)
        self._area_err_lbl.grid_remove()

        # ---- 右栏：输出文件预览 + 构建按钮 ----
        right = ctk.CTkFrame(main_card, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 10))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)  # 弹性空间给预览树

        # 输出文件预览（标题右侧 ⓘ 悬停解释颜色图例）
        preview_title = ctk.CTkFrame(right, fg_color="transparent")
        preview_title.grid(row=0, column=0, sticky="nw", padx=10,
                           pady=(10, 5))
        ctk.CTkLabel(preview_title, text="输出文件预览",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left")
        legend_icon = ctk.CTkLabel(
            preview_title, text="ⓘ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray45", "gray65"))
        legend_icon.pack(side="left", padx=(6, 0))
        ToolTip(legend_icon, rich=[
            ("普通文件\n", "white"),
            ("入口文件（含所在目录）\n", "#4CAF50"),
            ("manifest.json（清单）\n", "#F5C518"),
            ("尚未生成（构建后生成）\n", "#888888"),
            ("缺失条目", "#E5484D"),
        ])
        # 产物树（根 = 包名，可折叠）
        self._preview = ttk.Treeview(right, show="tree", selectmode="none",
                                     style="Preview.Treeview")
        self._preview.grid(row=1, column=0, sticky="nsew", padx=10,
                           pady=(0, 10))
        self._controls.append(self._preview)
        self._style_preview_tree()

        # 构建按钮行（右栏底部）：开始构建 + 状态
        build_row = ctk.CTkFrame(right, fg_color="transparent")
        build_row.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 12))
        build_row.grid_columnconfigure(0, weight=1)
        self._build_status = ctk.CTkLabel(build_row, text="",
                                          font=ctk.CTkFont(size=12),
                                          anchor="e")
        self._build_status.grid(row=0, column=0, sticky="e", padx=(0, 8))
        self._build_btn = ctk.CTkButton(
            build_row, text="开始构建", command=self._build_clicked,
            width=120, height=36, font=ctk.CTkFont(size=14, weight="bold"))
        self._build_btn.grid(row=0, column=1, sticky="e")
        self._controls.append(self._build_btn)

    def _build_clicked(self) -> None:
        """「开始构建」→ 透传给 app（构建/取消切换由 app 管理）。"""
        if self._on_build_clicked:
            self._on_build_clicked()

    def get_build_button(self) -> ctk.CTkButton:
        """供 app 管理构建状态（文本切换 / 禁用）。"""
        return self._build_btn

    def get_build_status(self) -> ctk.CTkLabel:
        """供 app 设置构建状态文本。"""
        return self._build_status

    # ------------------------------------------------------------------
    # 打包内容（统一文件列表，标签标记入口）
    # ------------------------------------------------------------------

    def _builder(self) -> Builder | None:
        """持久的 Builder 实例（deduced 视图在内存，需跨操作保留）。"""
        if self._builder_obj is None and self._pm is not None:
            self._builder_obj = Builder(self._pm)
        return self._builder_obj

    def get_builder(self) -> Builder | None:
        """供 app 组装 BuildContext（与列表共用同一实例，含 deduced 视图）。"""
        return self._builder()

    def _add_files(self) -> None:
        """常规文件选择器：多选文件（必须位于项目根内）。"""
        if not self._plugin_dir:
            return
        b = self._builder()
        if b is None:
            return
        base = self._plugin_dir
        files = filedialog.askopenfilenames(title="选择要打包的文件",
                                           initialdir=base)
        if not files:
            return
        skipped = 0
        for f in files:
            rel = self._rel_to_source(f)
            if rel:
                b.add_file(rel)
            else:
                skipped += 1
        if skipped:
            self._show_add_hint(f"已跳过项目根外的 {skipped} 个文件")
        self.clear_errors()  # 内容已变，清除旧错误高亮
        self._refresh_item_list()
        self._refresh_preview()

    def _add_dir(self) -> None:
        """常规目录选择器：选一个目录（必须位于项目根内）。"""
        if not self._plugin_dir:
            return
        b = self._builder()
        if b is None:
            return
        base = self._plugin_dir
        d = filedialog.askdirectory(title="选择要打包的目录",
                                    initialdir=base)
        if not d:
            return
        rel = self._rel_to_source(d)
        if rel is None:
            self._show_add_hint("所选目录必须在项目根内")
            return
        b.add_dir(rel)
        self.clear_errors()  # 内容已变，清除旧错误高亮
        self._refresh_item_list()
        self._refresh_preview()

    # ------------------------------------------------------------------
    # 编译设置区块（变化透传 → app 自动填充）
    # ------------------------------------------------------------------

    def _on_compile_inner_changed(self) -> None:
        """内嵌 CompileTab 设置变化：透传给 app（自动填充）。"""
        if self._on_compile_changed:
            self._on_compile_changed()

    def get_compile_view(self) -> CompileTab:
        """供 app 组装 BuildContext（编译系统 / 编译设置字段）。"""
        return self._compile_view

    def _rel_to_source(self, path: str) -> str | None:
        """绝对路径 → 相对项目根的 posix 路径；不在项目根内返回 None。"""
        base = Path(self._plugin_dir or ".")
        try:
            return Path(path).resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            return None

    def _show_add_hint(self, msg: str,
                       color: str | tuple[str, str] = "#FF4444") -> None:
        """显示提示，3 秒后自动清除（无内容不占位）。"""
        self._add_hint_lbl.configure(text=msg, text_color=color)
        self._add_hint_lbl.grid()
        try:
            self.after(
                3000,
                lambda: (self._add_hint_lbl.configure(text=""),
                         self._add_hint_lbl.grid_remove()))
        except Exception:
            pass

    def _add_rule(self) -> None:
        """添加规则（对话框输入 glob pattern——与添加文件/目录交互一致）。"""
        dlg = ctk.CTkToplevel(self)
        dlg.title("添加规则")
        dlg.geometry("360x160")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        # 简单居中（父窗口中心偏移）
        self.winfo_toplevel().update_idletasks()
        x = self.winfo_toplevel().winfo_rootx() + 80
        y = self.winfo_toplevel().winfo_rooty() + 120
        dlg.geometry(f"360x160+{x}+{y}")

        ctk.CTkLabel(dlg, text="规则 (glob):").grid(
            row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        entry = ctk.CTkEntry(dlg, width=250, placeholder_text="dist/**")
        entry._is_focused = False
        entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 0))
        entry.focus_set()
        ctk.CTkLabel(
            dlg, text="相对插件目录的 glob；不支持 ../ 跨目录引用",
            text_color=("gray50", "gray60"),
            font=ctk.CTkFont(size=11),
        ).grid(row=1, column=0, columnspan=2, padx=10, sticky="w")

        def on_ok() -> None:
            pattern = entry.get().strip()
            if not pattern:
                return
            b = self._builder()
            if b is not None:
                b.add_rule(pattern)
                self.clear_errors()  # 内容已变，错误提示可清除
                self._refresh_item_list()
                self._refresh_preview()
            dlg.destroy()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=2, column=0, columnspan=2, sticky="e",
                     pady=(15, 10))
        ctk.CTkButton(btn_row, text="取消", width=100,
                      command=dlg.destroy).pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="确定", width=100,
                      command=on_ok).pack(side="right", padx=5)
        entry.bind("<Return>", lambda _e: on_ok())
        dlg.wait_window()

    def _refresh_item_list(self) -> None:
        for w in self._item_list.content.winfo_children():
            w.destroy()
        b = self._builder()
        if b is None:
            return
        workdir = Path(self._plugin_dir or ".")
        for i, item in enumerate(b.items()):
            kind = item.kind.value
            rel = item.value
            tags = item.tags
            is_entry = "entry" in tags

            # 卡片式行（斑马纹交替底色 + 圆角）
            leave_color = (STRIP_A if i % 2 else STRIP_B)
            row = ctk.CTkFrame(
                self._item_list.content,
                fg_color=leave_color,
                corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)
            if rel in self._error_rels:
                row.configure(border_width=2, border_color="#FF4444")
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=3)  # pady 3：字体放大后行高保持

            # hover 高亮（递归绑定非按钮子控件，✕ 保留自身 hover）

            # 目录以尾部 "\" 标识；规则保留徽章（glob 无自然符号）
            if kind == "pattern":
                (kbg, kfg), klabel = _KIND_STYLES[kind]
                ctk.CTkLabel(inner, text=klabel, width=36,
                             font=ctk.CTkFont(size=10, weight="bold"),
                             fg_color=kbg, text_color=kfg,
                             corner_radius=4).pack(side="left")
            is_error = rel in self._error_rels
            is_derived = bool(item.derived)
            if is_derived:
                # 编译产物：显示相对插件目录的路径（输出目录/.pyi/<插件名>/...）
                if "manifest" in tags:
                    display = rel  # 打包时生成的固定文件，无产物路径
                else:
                    out_rel = (b.get_output_dir() or "output").rstrip("/\\")
                    plugin_name = Path(self._plugin_dir or ".").name
                    display = f"{out_rel}/.pyi/{plugin_name}/{rel}"
                if kind == "dir":
                    display += "/"
            else:
                display = rel if kind != "dir" else rel.rstrip("/\\") + "/"
            ctk.CTkLabel(inner, text=display, anchor="w",
                         font=ctk.CTkFont(family="Consolas", size=13,
                                          weight="bold"),
                         text_color=("#FF4444" if is_error
                                     else ("gray55", "gray45")
                                     if is_derived else None)
                         ).pack(side="left", fill="x", expand=True,
                                padx=(8, 6))
            # 入口徽章：位于文件名右侧（仍左对齐区域）
            if "entry" in tags:
                (tbg, tfg), tname = _TAG_STYLES["entry"]
                ctk.CTkLabel(inner, text=tname, width=36,
                             font=ctk.CTkFont(size=10, weight="bold"),
                             fg_color=tbg, text_color=tfg,
                             corner_radius=4).pack(side="left",
                                                    padx=(2, 0))
            # manifest 徽章：打包生成的固定文件（黄色，如入口徽章）
            if "manifest" in tags:
                (tbg, tfg), tname = _TAG_STYLES["manifest"]
                ctk.CTkLabel(inner, text=tname, width=36,
                             font=ctk.CTkFont(size=10, weight="bold"),
                             fg_color=tbg, text_color=tfg,
                             corner_radius=4).pack(side="left",
                                                    padx=(2, 0))
            if is_derived:
                ctk.CTkLabel(inner, text="编译产物", width=56,
                             font=ctk.CTkFont(size=10),
                             fg_color=("gray80", "gray30"),
                             text_color=("gray25", "gray75"),
                             corner_radius=4).pack(side="left", padx=(2, 0))

            # 右侧按钮：✕ 最右（derived 只读，不显示）
            if not is_derived:
                ctk.CTkButton(
                    inner, text="✕", width=26, height=24,
                    fg_color="transparent",
                    hover_color=("#FF6B6B", "#B34040"),
                    font=ctk.CTkFont(size=12),
                    command=lambda i=i: self._remove_item(i)).pack(
                    side="right", padx=(2, 0))

            # hover 高亮：进入行区域时提升底色，离开恢复斑马底色
            hover_color = ("#D6E4F2", "gray28")
            for w in (row, inner):
                w.bind("<Enter>",
                       lambda e, r=row, hc=hover_color:
                       r.configure(fg_color=hc))
                w.bind("<Leave>",
                       lambda e, r=row, lc=leave_color:
                       r.configure(fg_color=lc))
            for w in inner.winfo_children():
                if isinstance(w, ctk.CTkButton):
                    continue
                w.bind("<Enter>",
                       lambda e, r=row, hc=hover_color:
                       r.configure(fg_color=hc))
                w.bind("<Leave>",
                       lambda e, r=row, lc=leave_color:
                       r.configure(fg_color=lc))

            if kind == "pattern" and workdir.is_dir():
                n = len(evaluate_pattern(workdir, rel))
                hint = (f"匹配 {n} 个文件" if n else
                        "当前无匹配，构建时求值")
                ctk.CTkLabel(row, text=f"    {hint}",
                             font=ctk.CTkFont(size=10), text_color="gray",
                             anchor="w").pack(fill="x", padx=10, pady=(0, 3))

        # 区域级错误：打包内容容器红框 + 红色提示
        if self._area_error:
            self._item_list.configure(border_width=2,
                                      border_color="#FF4444")
        else:
            self._item_list.configure(border_width=0)

    def _remove_item(self, idx: int) -> None:
        b = self._builder()
        if b is not None:
            b.remove_item(idx)
            self.clear_errors()  # 内容已变，清除旧错误高亮
            self._refresh_item_list()
            self._refresh_preview()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _on_setting_changed(self, *args: Any) -> None:
        if self._loading:
            return
        self.save_settings()
        self._refresh_preview()

    def set_plugin_dir(self, d: str, pm: ProjectManager | None = None) -> None:
        if pm and self._pm is not pm:
            self._pm = pm
            self._builder_obj = None  # 新项目：重建 Builder（deduced 由加载流程注入）
        self._plugin_dir = d
        b = self._builder()
        if b is not None:
            b.prune_persisted()  # 清理旧版 derived/auto 落盘残留（迁移）
        self._set_enabled(True)
        self._error_rels = set()  # 新项目清除旧错误高亮
        self._area_error = ""
        self._area_err_lbl.grid_remove()
        self._compile_view.set_plugin_dir(d, pm)
        if self._pm:
            b = self._builder()
            name = b.get_packer_name() if b else ""
            # placeholder 显示默认包名（插件目录名）
            self._name_entry.configure(placeholder_text=Path(d).name)
            self._name_entry.delete(0, "end")
            if name:
                self._name_entry.insert(0, name)
            else:
                # 无自定义包名：重新激活 placeholder 刷新默认包名显示
                self._name_entry._activate_placeholder()
            self._auto_suffix_var.set(bool(
                self._pm.read_project().get("compiler", {})
                .get("auto_suffix", False)))
            self._refresh_item_list()
        self._refresh_preview()

    def _save_packer_name(self) -> None:
        """保存自定义包名（FocusOut / Return 时写入 project.json）。"""
        b = self._builder()
        if b is None:
            return
        b.set_packer_name(self._name_entry.get().strip())
        self._refresh_preview()

    def _on_auto_suffix_toggled(self) -> None:
        """自动后缀开关变化 → 保存并刷新预览。"""
        if self._loading or not self._pm:
            return
        project = self._pm.read_project()
        compiler = project.setdefault("compiler", {})
        compiler["auto_suffix"] = bool(self._auto_suffix_var.get())
        self._pm.write_project(project)
        self._refresh_preview()

    def save_settings(self) -> None:
        """发布选项已无持久化字段（仅 zip 输出），保留占位供调用方兼容。"""
        return

    # ------------------------------------------------------------------
    # accessors（供 app.py / 预览）
    # ------------------------------------------------------------------

    def mark_errors(self, rels: set[str], area_msg: str = "") -> None:
        """标记校验错误：条目级（红框红字）+ 区域级（容器红框 + 提示）。"""
        self._error_rels = set(rels)
        self._area_error = area_msg
        if self._area_error:
            self._area_err_lbl.configure(text=self._area_error)
            self._area_err_lbl.grid()
        else:
            self._area_err_lbl.grid_remove()
        self._refresh_item_list()

    def clear_errors(self) -> None:
        """清除条目与区域错误高亮（校验通过/重新校验前调用）。"""
        if self._error_rels or self._area_error:
            self._error_rels = set()
            self._area_error = ""
            self._area_err_lbl.grid_remove()
            self._refresh_item_list()
            if self._on_error_cleared:
                self._on_error_cleared()  # 级联清除 tab 标题高亮

    # ------------------------------------------------------------------
    # 预览
    # ------------------------------------------------------------------

    def refresh_preview(self, output_dir: str = "") -> None:
        self._refresh_preview(output_dir)

    def _style_preview_tree(self) -> None:
        """Treeview 样式：按外观模式适配深/浅色（卡片内凹陷列表区）。"""
        style = ttk.Style()
        style.theme_use("clam")
        dark = ctk.get_appearance_mode() == "Dark"
        bg = LIST_BG[1] if dark else LIST_BG[0]
        fg = "#D0D0D0" if dark else "#202020"
        style.configure("Preview.Treeview",
                        background=bg, fieldbackground=bg,
                        foreground=fg, rowheight=22, borderwidth=0,
                        bordercolor=bg, lightcolor=bg, darkcolor=bg)
        style.map("Preview.Treeview",
                  background=[("selected", "#2B6EA6")],
                  foreground=[("selected", "#FFFFFF")])
        self._preview.tag_configure("entry", foreground="#4CAF50")
        self._preview.tag_configure(
            "derived", foreground=("#888888" if dark else "#777777"))
        self._preview.tag_configure(
            "manifest", foreground=("#F5C518" if dark else "#B8860B"))
        self._preview.tag_configure("missing", foreground="#E5484D")

    def _preview_ins(self, parent: str, text: str,
                     tag: str = "") -> str:
        """Treeview 插入一行，返回节点 id。"""
        return self._preview.insert(
            parent, "end", text=text,
            tags=(tag,) if tag else ())

    def _preview_arcs(self, items: list[PreviewItem],
                      parent: str) -> None:
        """按路径分目录插入产物树（arc → 嵌套节点）。

        叶子标注：入口绿色、编译产物灰；目录若包含入口文件
        （如 src/ 含 src/main.py）也标绿。
        """
        root: dict[str, Any] = {}
        by_arc: dict[str, PreviewItem] = {}
        entry_arcs = [it.arc for it in items if it.entry]
        for it in items:
            by_arc[it.arc] = it
            node = root
            for part in it.arc.split("/"):
                node = node.setdefault(part, {})

        def _ins(d: dict[str, Any], pid: str, prefix: str = "") -> None:
            for key in sorted(d):
                children = d[key]
                path = f"{prefix}/{key}" if prefix else key
                if children:
                    tag = ("entry" if any(
                        a.startswith(path + "/") for a in entry_arcs) else "")
                    nid = self._preview_ins(pid, key + "/", tag)
                    _ins(children, nid, path)
                else:
                    src = by_arc.get(path)
                    if src is not None and src.arc == "manifest.json":
                        leaf_tag = "manifest"
                    elif src is not None and src.entry:
                        leaf_tag = "entry"
                    elif src is not None and src.derived:
                        leaf_tag = "derived"
                    else:
                        leaf_tag = ""
                    self._preview_ins(pid, key, leaf_tag)

        _ins(root, parent)

    # ------------------------------------------------------------------
    # 预览：收集（来源无关）→ 模型 → 渲染（解耦）
    # ------------------------------------------------------------------

    def _collect_preview_items(self, out_dir: str = "") -> list[PreviewItem]:
        """从 Builder 条目收集产物内容（手动/derived/规则统一模型）。

        无论条目来自何处，都产出 PreviewItem 列表——渲染器只消费
        该模型，可扩展其他来源（zip 扫描等）而不改渲染。
        """
        items: list[PreviewItem] = []
        b = self._builder()
        if b is None or not self._plugin_dir:
            return items
        source = Path(self._plugin_dir)
        prod = self._guess_prod_dir(out_dir)
        for item in b.items():
            rel = item.value
            is_entry = "entry" in item.tags
            if item.derived:
                if rel == "manifest.json":
                    # 打包时由 packaging 生成（zip/文件夹注入），
                    # 产物树中不存在——恒为声明行
                    items.append(PreviewItem(rel, "file", derived=True))
                    continue
                if prod is None:
                    # 未构建/已打包：文件为声明、目录单行
                    if item.kind is ItemKind.DIR:
                        items.append(PreviewItem(rel, "dir", derived=True))
                    else:
                        items.append(PreviewItem(rel, "file",
                                                 derived=True,
                                                 entry=is_entry))
                    continue
                base = prod / rel
                if base.is_file():
                    items.append(PreviewItem(rel, "file", source=base,
                                             derived=True, entry=is_entry))
                elif base.is_dir():
                    for f in sorted(base.rglob("*")):
                        if f.is_file():
                            items.append(PreviewItem(
                                f"{rel}/{f.relative_to(base).as_posix()}",
                                "file", source=f, derived=True))
                else:
                    items.append(PreviewItem(rel, "missing"))
            elif item.kind is ItemKind.DIR:
                base = source / rel
                if base.is_dir():
                    for f in sorted(base.rglob("*")):
                        if f.is_file():
                            items.append(PreviewItem(
                                f"{rel}/{f.relative_to(base).as_posix()}",
                                "file", source=f))
                else:
                    items.append(PreviewItem(rel, "missing"))
            elif item.kind is ItemKind.PATTERN:
                for matched in evaluate_pattern(source, rel):
                    items.append(PreviewItem(matched, "file",
                                             source=source / matched))
            else:  # FILE
                p = source / rel
                if p.is_file():
                    items.append(PreviewItem(rel, "file", source=p,
                                             entry=is_entry))
                else:
                    items.append(PreviewItem(rel, "missing"))
        return items

    def _render_preview(self, items: list[PreviewItem],
                        packer_name: str) -> None:
        """渲染产物模型 → 产物树（根 = 包名，子 = zip 内文件）。"""
        files = [it for it in items if it.kind == "file"]
        missing = [it for it in items if it.kind == "missing"]
        dirs = [it for it in items if it.kind == "dir"]

        # ---- 产物树（根 = 包名，子 = zip 内文件）----
        root = self._preview_ins("", f"📁 {packer_name}/")
        self._preview_arcs(files, root)
        tree_dirs = {it.arc.split("/")[0] for it in files}
        for it in dirs:
            if it.arc in tree_dirs:
                continue  # 已在文件树中（如 src/ 由 src/main.py 建立）
            self._preview_ins(root, f"{it.arc}/", "derived")
        if missing:
            for it in sorted(missing, key=lambda x: x.arc):
                self._preview_ins(root, it.arc, "missing")
        # 展开根节点（子节点可见）
        self._preview.item(root, open=True)

    def _refresh_preview(self, out_dir: str = "") -> None:
        plugin_name = Path(self._plugin_dir).name if self._plugin_dir else "插件名"
        self._preview.delete(*self._preview.get_children())

        # 输出目录（绝对路径、尾部 "/"，任何刷新入口显示一致）
        default_out = (Path(self._plugin_dir) / "output").as_posix() \
            if self._plugin_dir else "（未选择插件目录）"
        shown_out = (out_dir or default_out).rstrip("/") + "/"

        b = self._builder()
        packer_name = (b.get_packer_name() if b else "") or plugin_name
        project = self._pm.read_project() if self._pm else {}
        compiler = project.get("compiler", {}) if isinstance(project, dict) else {}
        packer_name += pack_suffix(compiler)

        # 收集（来源无关）→ 渲染
        items = self._collect_preview_items(out_dir)
        self._render_preview(items, packer_name)

    def _guess_prod_dir(self, out_dir: str) -> Path | None:
        """推导编译产物树目录（.pyi/<name> 或 .node/<name>）；未构建不存在。"""
        if not self._plugin_dir or not self._pm:
            return None
        out = Path(out_dir) if out_dir else \
            Path(self._plugin_dir) / "output"
        project = self._pm.read_project() or {}
        compiler = project.get("compiler", {}) or {}
        system = compiler.get("compile_system", "")
        if system == "node":
            d = out / ".node" / Path(self._plugin_dir).name
        elif system == "python":
            d = out / ".pyi" / Path(self._plugin_dir).name
        else:
            return None
        return d if d.is_dir() else None
