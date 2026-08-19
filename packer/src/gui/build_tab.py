"""Build tab — 编译设置 + 打包内容与发布选项（纯 GUI 工具的单视图构建页）。

- 编译设置：内嵌 CompileTab（直接平铺）——编译系统 / 依赖清单 /
  产物模式；设置变化自动重新填充 deduce 产物条目
- 打包内容：统一文件选择列表（文件 / 目录 / 规则三种条目，标签标记入口）
  +「添加文件」/「添加目录」（常规系统选择器）+「添加规则」
- 发布选项：输出固定为 .zip 分发包 + 预览树（输出目录在顶部栏）
"""

from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from backend.builder import Builder, BuilderItem, evaluate_pattern
from backend.packaging import pack_suffix
from backend.project_manager import ProjectManager
from gui.compile_tab import CompileTab
from gui.widgets import (BG0, BG1, LIST_BG, STRIP_A, STRIP_B,
                         FillScrollable, center_dialog, reset_entry_border)

# 右栏各行统一的前导标签宽度（像素）
_LABEL_W = 92

# 条目类型徽章样式：(背景, 前景) 按浅/深模式，区分文件/目录/规则
_KIND_STYLES = {
    "path": (("#DCE7FB", "#2E4A7A"), "文件"),
    "dir": (("#E9E2F8", "#4A3A6A"), "目录"),
    "pattern": (("#F8E8D8", "#6A4A2A"), "规则"),
}

# 标签徽章样式：标签 → ((bg_light, bg_dark), 显示名)
_TAG_STYLES = {
    "entry": (("#4CAF50", "#2E7D32"), "入口"),
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
        right.grid_rowconfigure(1, weight=1)  # 弹性空间给预览 Textbox

        # 输出文件预览
        ctk.CTkLabel(right, text="输出文件预览",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, sticky="nw", padx=10, pady=(10, 5))
        self._preview = ctk.CTkTextbox(right, wrap="word",
                                       font=("Consolas", 12),
                                       state="disabled", fg_color=LIST_BG)
        self._preview.grid(row=1, column=0, sticky="nsew", padx=10,
                           pady=(0, 10))
        self._controls.append(self._preview)

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
            kind = next((k for k in ("path", "dir", "pattern")
                        if getattr(item, k, None) is not None), "pattern")
            rel = getattr(item, kind, "")
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

            # 整行可双击（derived 只读不绑定；✕ 保留自身 command）
            if not is_derived:
                def _bind_row_click(w: Any, idx: int) -> None:
                    for child in w.winfo_children():
                        if isinstance(child, ctk.CTkButton):
                            continue
                        child.bind(
                            "<Double-1>",
                            lambda e, i=idx: self._edit_item(i))
                        _bind_row_click(child, idx)

                row.bind("<Double-1>",
                         lambda e, i=i: self._edit_item(i))
                _bind_row_click(row, i)

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

    def _edit_item(self, idx: int) -> None:
        """双击条目：详情对话框（完整路径 + 重选 + 标签下拉）并应用。"""
        b = self._builder()
        if b is None:
            return
        items = b.items()
        if not (0 <= idx < len(items)):
            return
        result = self._ask_item_detail(items[idx])
        if result is None:  # 取消
            return
        new_rel, new_tags = result
        if new_rel is not None:
            b.set_path(idx, new_rel)
        if new_tags is not None:
            # 保持 entry 唯一：新标签为 entry 时，清除其他条目的 entry
            if "entry" in new_tags:
                for i, item in enumerate(b.items()):
                    if i != idx and "entry" in item.tags:
                        b.set_tags(i, [t for t in item.tags
                                       if t != "entry"])
            b.set_tags(idx, new_tags)
        self.clear_errors()  # 内容已变，清除旧错误高亮
        self._refresh_item_list()
        self._refresh_preview()

    def _ask_item_detail(self, item: BuilderItem) -> tuple[str | None,
                                                           list[str]] | None:
        """条目详情对话框：完整路径 + 重选按钮 + 标签下拉。

        返回 (重选后的相对路径或 None, 新标签)；取消返回 None。
        """
        win = ctk.CTkToplevel(self)
        win.title("条目详情")
        win.geometry("460x230")
        win.resizable(False, False)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        center_dialog(win, self.winfo_toplevel())  # 始终居中于主窗口
        try:
            win.after(50, win.lift)
        except Exception:
            pass

        kind = next((k for k in ("path", "dir", "pattern")
                    if getattr(item, k, None) is not None), "pattern")
        rel = getattr(item, kind, "")
        tags = item.tags
        base = Path(self._plugin_dir or ".")
        is_file = (kind == "path")
        pending: list[str | None] = [None]  # 重选后的相对路径
        result: list = []

        def _display(path: Path) -> str:
            """文件选择器风格显示：Windows 反斜杠分隔；目录尾部加 "\\"。"""
            s = str(path).replace("/", "\\")
            if kind == "dir":
                s = s.rstrip("\\") + "\\"
            return s

        def _set_path_display(rel2: str) -> None:
            """刷新路径框显示（只读）。"""
            path_entry.configure(state="normal")
            path_entry.delete(0, "end")
            path_entry.insert(0, _display(base / rel2))
            path_entry.configure(state="readonly")

        # ---- 完整路径（本身即文件选择器：点击弹选择器）----
        ctk.CTkLabel(win, text="完整路径",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
            anchor="w", padx=16, pady=(12, 4))
        path_frame = ctk.CTkFrame(win, fg_color="transparent")
        path_frame.pack(fill="x", padx=16)
        path_entry = ctk.CTkEntry(
            path_frame,
            font=ctk.CTkFont(family="Consolas", size=11))
        path_entry._is_focused = False  # placeholder/焦点状态统一
        path_entry.insert(0, _display(base / rel))
        path_entry.configure(state="readonly")
        path_entry.pack(side="left", fill="x", expand=True)

        if kind != "pattern":  # 规则（glob）无路径可重选
            def _open_selector() -> None:
                if kind == "dir":
                    d = filedialog.askdirectory(title="重新选择目录",
                                                initialdir=base)
                else:
                    d = filedialog.askopenfilename(title="重新选择文件",
                                                   initialdir=base)
                if not d:
                    return
                rel2 = self._rel_to_source(d)
                if rel2 is None:
                    path_entry.configure(border_color="#FF4444")
                    win.after(
                        2000,
                        lambda: reset_entry_border(path_entry))
                    return
                pending[0] = rel2
                _set_path_display(rel2)

            # 与其它选择器一致：按钮触发，路径框只读展示
            ctk.CTkButton(path_frame, text="选择", width=56, height=26,
                          font=ctk.CTkFont(size=11),
                          command=_open_selector).pack(side="right",
                                                       padx=(6, 0))

        # ---- 标签（仅文件可标入口；目录/规则无标签）----
        tag_menu: ctk.CTkOptionMenu | None = None
        if is_file:
            tag_row = ctk.CTkFrame(win, fg_color="transparent")
            tag_row.pack(fill="x", padx=16, pady=(14, 0))
            ctk.CTkLabel(tag_row, text="标签", width=56,
                         anchor="w").pack(side="left")
            cur_label = "入口" if "entry" in tags else "其它"
            tag_menu = ctk.CTkOptionMenu(tag_row, width=220,
                                         values=["入口", "其它"])
            tag_menu.set(cur_label)
            tag_menu.pack(side="left")

        def _ok() -> None:
            new_tags: list[str] = []
            if is_file and tag_menu is not None and tag_menu.get() == "入口":
                new_tags = ["entry"]
            result[:] = [pending[0], new_tags]
            win.destroy()
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x")
        ctk.CTkButton(btns, text="取消", width=70,
                      command=win.destroy).pack(side="right", padx=5)
        ctk.CTkButton(btns, text="确定", width=70,
                      command=_ok).pack(side="right", padx=5)
        self.wait_window(win)
        if not result:
            return None
        new_rel, new_tags = result
        return (new_rel or None, new_tags)

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

    def _refresh_preview(self, out_dir: str = "") -> None:
        plugin_name = Path(self._plugin_dir).name if self._plugin_dir else "插件名"
        lines: list[str] = []
        lines.append("=" * 30)
        # 输出目录始终显示绝对路径、独占一行、格式统一（尾部带 "/"，
        # 与顶部栏 _norm_dir 目录风格一致）：显式传入的可能无尾部斜杠
        # （to_absolute / askdirectory），统一补上——任何刷新入口
        # （含点「不压缩」触发的无参刷新）显示一致，行内容不随入口变化
        default_out = (Path(self._plugin_dir) / "output").as_posix() \
            if self._plugin_dir else "（未选择插件目录）"
        shown_out = (out_dir or default_out).rstrip("/") + "/"
        lines.append(f"输出目录: {shown_out}")

        entry = "未设置"
        b = self._builder()
        packer_name = (b.get_packer_name() if b else "") or plugin_name
        # 与 resolve_packer_name 一致：auto_suffix 开启时按产物模式追加
        project = self._pm.read_project() if self._pm else {}
        compiler = project.get("compiler", {}) if isinstance(project, dict) else {}
        packer_name += pack_suffix(compiler)
        lines.append(f"  {packer_name}.zip  ← 压缩包")

        # 树行：先收集再绘制——最后一行用 L 形转角（└──），其余用 ├──
        tree = ["    ├── manifest.json"]
        b = self._builder()
        workdir = Path(self._plugin_dir or ".")
        if b is not None:
            for item in b.items():
                kind = next((k for k in ("path", "dir", "pattern")
                            if getattr(item, k, None) is not None), "pattern")
                rel = getattr(item, kind, "")
                is_entry = "entry" in item.tags
                if kind == "pattern" and workdir.is_dir():
                    matched = evaluate_pattern(workdir, rel)
                    names = [Path(m).name for m in matched[:10]]
                    extra = (f"…共 {len(matched)} 个" if len(matched) > 10
                             else "")
                    tree.append(
                        f"    ├── {rel}（规则）→ {', '.join(names)} {extra}")
                else:
                    mark = " ← 编译产物" if item.derived \
                        else (" ← 入口" if is_entry else "")
                    shown = rel if kind != "dir" else rel.rstrip("/\\") + "/"
                    tree.append(f"    ├── {shown}{mark}")
        if tree:
            tree[-1] = tree[-1].replace("├──", "└──", 1)
        lines.extend(tree)

        self._preview.configure(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("1.0", "\n".join(lines))
        self._preview.configure(state="disabled")
