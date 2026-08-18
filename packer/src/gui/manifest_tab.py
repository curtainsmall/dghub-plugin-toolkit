"""Manifest editor tab."""

import json
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from backend.manifest_validator import VALID_FIELD_TYPES, validate_manifest
from backend.project_manager import ProjectManager
from gui.widgets import center_dialog, reset_entry_border

FIELD_TYPE_LABELS: dict[str, str] = {
    "bool": "开关 (bool)",
    "percent": "百分比 0-100 (percent)",
    "duration": "秒数 (duration)",
    "number": "数字 (number)",
    "text": "文本 (text)",
    "select": "下拉框 (select)",
    "channel": "通道选择 a/b/both (channel)",
    "preset": "波形预设 (preset)",
    "path": "路径 (path)",
}

# 字段类型徽章样式（浅/深模式背景色）：类型 → ((bg_light, bg_dark), 短名)
_FIELD_BADGE = {
    "text": (("#DCE7FB", "#2E4A7A"), "文本"),
    "path": (("#DCE7FB", "#2E4A7A"), "路径"),
    "number": (("#FDEBD9", "#8A5A20"), "数字"),
    "percent": (("#FDEBD9", "#8A5A20"), "百分比"),
    "duration": (("#FDEBD9", "#8A5A20"), "秒数"),
    "bool": (("#DCF5E5", "#2E6B45"), "开关"),
    "select": (("#E9E2F8", "#4A3A6A"), "下拉"),
    "channel": (("#E9E2F8", "#4A3A6A"), "通道"),
    "preset": (("#E9E2F8", "#4A3A6A"), "预设"),
}


def _fmt_detail_default(field: dict) -> str:
    """字段 default 的详情面板显示（bool/数值格式化）。"""
    v = field.get("default")
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _field_badge_style(ftype: str) -> tuple[tuple[str, str], str]:
    """字段类型 → 徽章配色 + 短名（未知类型回退灰色）。"""
    return _FIELD_BADGE.get(ftype, (("gray75", "gray35"), ftype))


def _reset_entry_border(entry: ctk.CTkEntry) -> None:
    """将输入框恢复为主题默认边框（已移至 gui/widgets，此处保留兼容别名）。"""
    reset_entry_border(entry)


class ManifestTab(ctk.CTkFrame):
    """Tab for creating / editing manifest.json."""

    def __init__(self, master: Any,
                 on_field_edit: Callable[[str], None] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        # internal data
        self._sections: list[dict[str, Any]] = []
        self._section_buttons: list[ctk.CTkButton] = []
        self._selected_section: int = 0
        self._field_buttons: list[ctk.CTkButton] = []
        self._selected_field: int = 0  # 默认选中第一个字段
        self._plugin_dir: str | None = None
        self._controls: list[ctk.CTkBaseClass] = []
        self._field_errors: dict[str, str] = {}
        self._pm: ProjectManager | None = None
        self._auto_save_enabled = False
        # 字段被编辑时回调（key）→ 供 app 级联清除错误高亮
        self._on_field_edit = on_field_edit

        self._build_ui()
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        """Enable or disable all interactive controls."""
        state = "normal" if enabled else "disabled"
        for w in self._controls:
            try:
                w.configure(state=state)
            except Exception:
                pass
        # lock internal tk Entry as readonly (not disabled) so
        # placeholder stays visible; FocusIn interceptor prevents
        # CTk from clearing it
        entry_state = "normal" if enabled else "readonly"
        for _, widget in self._fields.items():
            try:
                widget._entry.configure(state=entry_state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)  # main content

        # -- main area: left (form) + right (preview) --
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        main.grid_columnconfigure(0, weight=1)              # left 弹性
        main.grid_columnconfigure(1, weight=0, minsize=360)  # right 固定宽
        main.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right = ctk.CTkFrame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # -- left side: form --
        self._build_basic_info(left)
        self._build_capabilities(left)
        self._build_schema_editor(left)

        # -- right side: field detail (editable) --
        self._build_field_detail(right)

        # -- bottom bar --
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        bottom.grid_columnconfigure(0, weight=1)

        self._error_label = ctk.CTkLabel(bottom, text="", text_color="red")
        self._error_label.pack(side="right", padx=5)

    # ------------------------------------------------------------------
    # basic info
    # ------------------------------------------------------------------

    def _build_basic_info(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(frame, text="基本信息",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))

        self._fields: dict[str, Any] = {}
        for key, label, placeholder, required in [
            ("id", "插件 ID", "my_plugin (小写字母开头)", True),
            ("name", "插件名称", "我的插件", True),
            ("version", "版本号", "0.1.0", True),
            ("author", "作者", "", False),
            ("description", "简介", "", False),
            ("homepage", "主页", "https://...", False),
        ]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            row.grid_columnconfigure(0, weight=0, minsize=100)
            row.grid_columnconfigure(1, weight=1)
            label_frame = ctk.CTkFrame(row, fg_color="transparent")
            label_frame.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(label_frame, text=label, anchor="w").pack(side="left")
            if required:
                ctk.CTkLabel(label_frame, text="*", text_color="red",
                             font=ctk.CTkFont(size=14)).pack(side="left")
            widget: ctk.CTkEntry = ctk.CTkEntry(row, placeholder_text=placeholder)
            widget._is_focused = False
            widget.grid(row=0, column=1, sticky="ew", padx=(5, 0))
            widget.bind("<KeyRelease>",
                        lambda e, k=key: self._on_field_keyrelease(k))
            widget.bind("<FocusIn>",
                        lambda e, k=key: self._on_field_focusin(k))
            self._fields[key] = widget
            self._controls.append(widget)

    def _on_field_keyrelease(self, key: str) -> None:
        widget = self._fields.get(key)
        if isinstance(widget, ctk.CTkEntry):
            _reset_entry_border(widget)
        if self._on_field_edit:
            self._on_field_edit(key)
        self._auto_save()

    def reset_field_borders(self) -> None:
        """将必填字段输入框恢复默认边框（供 app 在构建开始时统一复位）。"""
        for key in ("id", "name", "version"):
            w = self._fields.get(key)
            if isinstance(w, ctk.CTkEntry):
                _reset_entry_border(w)

    def _on_field_focusin(self, key: str) -> None:
        """Clear error text when the user focuses on a field."""
        widget = self._fields.get(key)
        if not isinstance(widget, ctk.CTkEntry):
            return
        if key in self._field_errors:
            del self._field_errors[key]
            widget.delete(0, "end")
            widget.configure(text_color=("gray10", "gray90"))

    # ------------------------------------------------------------------
    # capabilities
    # ------------------------------------------------------------------

    def _build_capabilities(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(frame, text="能力声明",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))
        self._cb_startup_check = ctk.CTkCheckBox(frame, text="启动检查 (startup_check)",
                                                  command=self._auto_save)
        self._cb_startup_check.pack(anchor="w", padx=10, pady=(0, 10))
        self._controls.append(self._cb_startup_check)

    # ------------------------------------------------------------------
    # config schema editor
    # ------------------------------------------------------------------

    def _build_schema_editor(self, parent: ctk.CTkFrame) -> None:
        frame = ctk.CTkFrame(parent)
        frame.pack(fill="both", expand=True, pady=(0, 10))
        ctk.CTkLabel(frame, text="Config Schema 编辑器",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=(10, 5))

        # sections area
        sec_frame = ctk.CTkFrame(frame)
        sec_frame.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        sec_frame.grid_columnconfigure(0, weight=1)
        sec_frame.grid_columnconfigure(1, weight=1)
        sec_frame.grid_rowconfigure(0, weight=1)

        # left: section list
        sec_left = ctk.CTkFrame(sec_frame)
        sec_left.grid(row=0, column=0, sticky="nsew")
        sec_left.grid_columnconfigure(0, weight=1)
        sec_left.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(sec_left, text="分组列表",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, pady=(5, 5))
        self._section_container = ctk.CTkScrollableFrame(sec_left)
        self._section_container.grid(row=1, column=0, sticky="nsew", padx=2, pady=5)
        self._section_container.grid_columnconfigure(0, weight=1)

        sec_btn_frame = ctk.CTkFrame(sec_left, fg_color="transparent")
        sec_btn_frame.grid(row=2, column=0, pady=5)
        ctk.CTkButton(sec_btn_frame, text="+ 添加分组", width=90,
                      command=self._add_section).pack(side="left", padx=2)
        ctk.CTkButton(sec_btn_frame, text="- 删除分组", width=90,
                      command=self._delete_section).pack(side="left", padx=2)
        for btn in sec_btn_frame.winfo_children():
            self._controls.append(btn)

        # right: fields in selected section
        sec_right = ctk.CTkFrame(sec_frame)
        sec_right.grid(row=0, column=1, sticky="nsew")
        sec_right.grid_columnconfigure(0, weight=1)
        sec_right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(sec_right, text="字段列表 (Fields)",
                     font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, pady=(5, 5))
        self._field_container = ctk.CTkScrollableFrame(sec_right)
        self._field_container.grid(row=1, column=0, sticky="nsew", padx=2, pady=5)
        self._field_container.grid_columnconfigure(0, weight=1)

        self._field_error_label = ctk.CTkLabel(
            self._field_container, text="",
            text_color="red", anchor="center",
            font=ctk.CTkFont(size=12))
        # 初始隐藏，有错误时才显示

        fld_btn_frame = ctk.CTkFrame(sec_right, fg_color="transparent")
        fld_btn_frame.grid(row=2, column=0, pady=5)
        ctk.CTkButton(fld_btn_frame, text="+ 添加字段", width=90,
                      command=self._add_field).pack(side="left", padx=2)
        ctk.CTkButton(fld_btn_frame, text="- 删除字段", width=80,
                      command=self._delete_field).pack(side="left", padx=2)
        for btn in fld_btn_frame.winfo_children():
            self._controls.append(btn)

    # ------------------------------------------------------------------
    # section management
    # ------------------------------------------------------------------

    def _add_section(self) -> None:
        # 直接创建默认分组（名称自动编号）并选中——随后在分组详情重命名
        n = 1
        names = {s.get("section") for s in self._sections}
        while f"new_group_{n}" in names:
            n += 1
        self._sections.append({"section": f"new_group_{n}", "fields": []})
        # 选中新分组（内含字段联动：新分组无字段 → 字段空态）
        self._select_section(len(self._sections) - 1)
        self._auto_save()  # 新增后写回磁盘

    def _delete_section(self) -> None:
        sel = self._get_selected_section_index()
        if sel is not None and 0 <= sel < len(self._sections):
            if messagebox.askyesno("确认", f"删除分组 '{self._sections[sel]['section']}'？"):
                self._sections.pop(sel)
                # 调整选中索引：min(sel, len-1) 在空列表时自动得 -1
                self._select_section(min(sel, len(self._sections) - 1))
                self._auto_save()  # 删除后写回磁盘
    
    def _select_section(self, idx: int) -> None:
        """选中分组 → 分组列表高亮/详情 + 联动选中其第一个字段
        （无字段 → -1 空态）。

        ``-1`` 为合法选中索引：无任何分组高亮，分组详情显示空态提示。
        字段联动收敛于此——add/delete 等方法仅调用本方法即可。
        """
        if idx < -1 or idx >= len(self._sections):
            return  # 非法索引忽略
        self._selected_section = idx
        self._section_container.configure(border_width=0)
        self._refresh_section_list()
        self._refresh_fields_display()  # 字段列表重建（切分组必刷）
        self._refresh_section_detail()
        # 字段联动：自动选中该分组第一个字段（无字段 → -1 空态）
        cur = self._get_current_section()
        fields = cur.get("fields", []) if cur else []
        self._select_field(0 if fields else -1)

    def _on_section_click(self, idx: int) -> None:
        """点击分组 → 选中分组（_select_section 内含字段联动）。"""
        self._select_section(idx)
    
    def _on_field_click(self, idx: int) -> None:
        """双击字段行 → 详情面板显示（记录选中供删除按钮定位）。"""
        self._edit_field_at(idx)
    
    def _select_field(self, idx: int) -> None:
        """选中字段 → 高亮 + 右侧详情面板显示。

        ``-1`` 为合法选中索引：无任何行高亮，详情面板显示空态提示。
        """
        sec = self._get_current_section()
        if sec is None or idx >= len(sec["fields"]):
            return
        self._selected_field = idx
        self._refresh_field_highlight()
        self._refresh_field_detail()
    
    def _refresh_field_highlight(self) -> None:
        """轻量更新字段行高亮（不整列重渲染，避免破坏双击编辑）。"""
        for j, row in enumerate(self._field_buttons):
            sel = (j == self._selected_field)
            leave = (("gray94", "gray19") if j % 2
                     else ("gray88", "gray23"))
            row.configure(fg_color=("#2B6EA6" if sel else leave))

    def _edit_field_at(self, idx: int) -> None:
        """选中字段（双击/单击）→ 右侧详情面板显示并编辑（不再弹对话框）。"""
        sec = self._get_current_section()
        if sec is None or idx >= len(sec["fields"]):
            return
        self._selected_field = idx
        self._refresh_field_detail()

    def _get_selected_section_index(self) -> int | None:
        if 0 <= self._selected_section < len(self._sections):
            return self._selected_section
        return None
    
    def _refresh_section_list(self) -> None:
        """Rebuild section rows with highlight on the selected one."""
        for btn in self._section_buttons:
            btn.destroy()
        self._section_buttons.clear()
    
        for i, sec in enumerate(self._sections):
            selected = (i == self._selected_section)
            n_fields = len(sec.get("fields", []))

            # 卡片式行（斑马纹 + 圆角；选中整行蓝底）
            leave_color = (("gray94", "gray19") if i % 2
                           else ("gray88", "gray23"))
            row = ctk.CTkFrame(
                self._section_container,
                fg_color=("#2B6EA6" if selected else leave_color),
                corner_radius=6)
            row.grid(row=i + 1, column=0, sticky="ew", padx=2, pady=2)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row, text=sec["section"], anchor="w",
                font=ctk.CTkFont(weight="bold"),
                text_color=("white" if selected else None)
            ).grid(row=0, column=0, sticky="w", padx=(8, 0))
            ctk.CTkLabel(
                row, text=f"{n_fields} 字段",
                font=ctk.CTkFont(size=11),
                text_color=("#D6E4FF" if selected else "gray")
            ).grid(row=0, column=2, padx=(8, 8))

            # 整行可点击（含子控件）
            row.bind("<Button-1>", lambda e, idx=i: self._on_section_click(idx))
            for child in row.winfo_children():
                child.bind(
                    "<Button-1>", lambda e, idx=i: self._on_section_click(idx))

            # hover 高亮：未选中行悬停提升底色；选中行保持蓝底
            hover_color = ("#D6E4F2", "gray28")
            sel_color = "#2B6EA6"
            for w in (row, *row.winfo_children()):
                w.bind("<Enter>",
                       lambda e, r=row, s=selected, hc=hover_color:
                       r.configure(fg_color=(sel_color if s else hc)))
                w.bind("<Leave>",
                       lambda e, r=row, s=selected, lc=leave_color:
                       r.configure(fg_color=(sel_color if s else lc)))
            self._section_buttons.append(row)

    def _refresh_fields_display(self) -> None:
        """Rebuild field rows（无选中态；双击编辑、hover 高亮）。"""
        for btn in self._field_buttons:
            btn.destroy()
        self._field_buttons.clear()
        self._field_error_label.configure(text="")
        self._field_error_label.grid_remove()
    
        sec = self._get_current_section()
        if sec is None:
            return
    
        for j, f in enumerate(sec["fields"]):
            ftype = f.get("type", "?")
            (fbg, ffg), fshort = _field_badge_style(ftype)
            key = f.get("key", "?")
            flabel = f.get("label", "")

            # 卡片式行（斑马纹 + 圆角；选中行蓝底，与分组列表一致）
            selected = (j == self._selected_field)
            leave_color = (("gray94", "gray19") if j % 2
                           else ("gray88", "gray23"))
            row = ctk.CTkFrame(
                self._field_container,
                fg_color=("#2B6EA6" if selected else leave_color),
                corner_radius=6)
            row.grid(row=j + 1, column=0, sticky="ew", padx=2, pady=2)
            row.grid_columnconfigure(1, weight=1)

            ctk.CTkLabel(
                row, text=fshort, width=44, height=20,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=fbg, text_color=ffg, corner_radius=4
            ).grid(row=0, column=0, padx=(6, 6), pady=4)
            ctk.CTkLabel(
                row, text=key, anchor="w",
                font=ctk.CTkFont(family="Consolas", size=13, weight="bold")
            ).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(
                row, text=flabel, anchor="e",
                font=ctk.CTkFont(size=12), text_color="gray"
            ).grid(row=0, column=2, padx=(8, 8))

            # 单击 → 选中（高亮，供删除按钮定位）；双击 → 编辑字段
            row.bind("<Button-1>",
                     lambda e, idx=j: self._select_field(idx))
            row.bind("<Double-1>",
                     lambda e, idx=j: self._on_field_click(idx))
            for child in row.winfo_children():
                child.bind("<Button-1>",
                           lambda e, idx=j: self._select_field(idx))
                child.bind(
                    "<Double-1>", lambda e, idx=j: self._on_field_click(idx))

            # hover 高亮：进入行区域提升底色，离开恢复（选中行保持蓝底——
            # 动态判断选中，避免选中状态变化后 hover 覆盖高亮）
            hover_color = ("#D6E4F2", "gray28")
            for w in (row, *row.winfo_children()):
                w.bind("<Enter>",
                       lambda e, r=row, hc=hover_color, idx=j:
                       r.configure(fg_color=hc
                                   if idx != self._selected_field
                                   else "#2B6EA6"))
                w.bind("<Leave>",
                       lambda e, r=row, lc=leave_color, idx=j:
                       r.configure(fg_color=("#2B6EA6"
                                             if idx == self._selected_field
                                             else lc)))
            self._field_buttons.append(row)

    # ------------------------------------------------------------------
    # field management
    # ------------------------------------------------------------------

    def _get_current_section(self) -> dict | None:
        idx = self._get_selected_section_index()
        if idx is not None and 0 <= idx < len(self._sections):
            return self._sections[idx]
        return None

    def _add_field(self) -> None:
        sec = self._get_current_section()
        if sec is None:
            self._field_error_label.configure(text="请先选择一个分组")
            self._field_error_label.grid(row=0, column=0)
            self._error_label.configure(text="", text_color="red")
            return
        # 直接创建默认字段并加入列表、选中（随后在详情面板编辑）
        n = 1
        keys = {f.get("key") for f in sec["fields"]}
        while f"new_field_{n}" in keys:
            n += 1
        sec["fields"].append({
            "key": f"new_field_{n}",
            "type": "text",
            "label": "新字段",
        })
        self._refresh_section_list()  # 字段数变化 → 刷新 section 计数
        self._select_field(len(sec["fields"]) - 1)  # 复用：选中新字段
        self._auto_save()  # 新增后写回磁盘

    def _delete_field(self) -> None:
        sec = self._get_current_section()
        if sec is None or not sec["fields"]:
            return
        idx = self._selected_field
        if idx < 0 or idx >= len(sec["fields"]):  # -1 = 未选中
            return
        if messagebox.askyesno("确认", f"删除字段 '{sec['fields'][idx].get('key', '?')}'？"):
            sec["fields"].pop(idx)
            # 调整选中索引：min(idx, len-1) 在空列表时自动得 -1
            self._refresh_section_list()  # 字段数变化 → 刷新 section 计数
            self._select_field(min(idx, len(sec["fields"]) - 1))
            self._auto_save()  # 删除后写回磁盘

    # type-specific fields shown in field dialog
    _TYPE_EXTRA: dict[str, list[str]] = {
        "bool":       ["default", "description"],
        "number":     ["default", "description", "min", "max", "step"],
        "text":       ["default", "description"],
        "percent":    ["default", "description"],
        "duration":   ["default", "description"],
        "channel":    ["default", "description"],
        "preset":     ["description"],
        "select":     ["default", "description"],
        "path":       ["default", "description"],
    }

    def _build_field_detail(self, parent: Any) -> None:
        """构建右侧字段详情面板（选中字段 → 可编辑控件；无选中 → 空态）。"""
        # ---- 分组详情（当前选中分组的名称编辑）----
        # 独立容器：内部空态/表单切换用 pack_forget 不会重排面板其他部分
        # （pack_forget 后重新 pack 会追加到末尾——必须在容器内隔离）
        self._sec_detail_area = ctk.CTkFrame(parent, fg_color="transparent")
        self._sec_detail_area.pack(anchor="nw", fill="x", pady=(0, 5))

        sec_header = ctk.CTkFrame(self._sec_detail_area, fg_color="transparent")
        sec_header.pack(anchor="nw", fill="x")
        ctk.CTkLabel(sec_header, text="分组详情",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        # 空态提示（无分组时显示；初始即显示——与字段详情空态一致）
        self._sec_detail_empty = ctk.CTkLabel(
            self._sec_detail_area,
            text="未选择分组——点击左侧分组列表或「+ 添加分组」新建。",
            text_color=("gray50", "gray60"), justify="left", anchor="w")
        self._sec_detail_empty.pack(anchor="nw", fill="x", pady=(4, 0))

        self._sec_detail_row = ctk.CTkFrame(self._sec_detail_area,
                                            fg_color="transparent")
        self._sec_detail_row.pack(fill="x", pady=(4, 0))
        self._sec_detail_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._sec_detail_row, text="名称", width=90,
                     anchor="w").grid(row=0, column=0, padx=(0, 5), sticky="w")
        self._sec_name_entry = ctk.CTkEntry(self._sec_detail_row)
        self._sec_name_entry._is_focused = False  # placeholder/焦点状态统一
        self._sec_name_entry.grid(row=0, column=1, sticky="ew")
        self._sec_name_entry.bind(
            "<FocusOut>", lambda _e: self._save_section_detail())
        self._sec_name_entry.bind(
            "<Return>", lambda _e: self._save_section_detail())
        self._controls.append(self._sec_name_entry)

        ctk.CTkFrame(parent, height=1, fg_color=("gray80", "gray30")).pack(
            fill="x", pady=(0, 8))

        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.pack(anchor="nw", fill="x", pady=(0, 5))
        ctk.CTkLabel(header, text="字段详情",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        # 空态提示（无选中字段时显示）
        self._detail_empty = ctk.CTkLabel(
            parent, text="未选择字段——点击左侧字段行查看/编辑，\n或点击「+ 添加字段」新建。",
            text_color=("gray50", "gray60"), justify="left")
        self._detail_empty.pack(anchor="nw", padx=10, pady=10)

        # 编辑表单（有选中字段时显示）
        self._detail_form = ctk.CTkFrame(parent, fg_color="transparent")
        self._detail_form.pack(fill="both", expand=True)
        self._detail_form.grid_columnconfigure(1, weight=1)

        self._detail_edits: dict[str, Any] = {}  # 字段名 → 编辑控件
        self._detail_row_frames: dict[str, ctk.CTkFrame] = {}
        self._detail_type = ctk.StringVar(value="")

        def _add_edit(key: str, label: str,
                      make_widget) -> None:
            """在行容器内创建控件（master=row，grid 撑满——避免 pack/grid
            混用冲突）。"""
            row = ctk.CTkFrame(self._detail_form, fg_color="transparent")
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(row, text=label, width=90, anchor="w").grid(
                row=0, column=0, padx=(0, 5), sticky="w")
            widget = make_widget(row)
            widget.grid(row=0, column=1, sticky="ew")
            self._detail_row_frames[key] = row
            self._detail_edits[key] = widget

        _add_edit("key", "key", lambda m: ctk.CTkEntry(m))
        # type（下拉切换 → 条件字段显隐 + 保存）
        _add_edit("type", "type", lambda m: ctk.CTkOptionMenu(
            m, values=sorted(VALID_FIELD_TYPES),
            variable=self._detail_type,  # 绑定：选择时更新 StringVar
            command=lambda _t: (self._on_detail_type_changed(),
                                self._save_detail_field())))
        _add_edit("label", "label", lambda m: ctk.CTkEntry(m))
        _add_edit("description", "description", lambda m: ctk.CTkEntry(m))

        # ---- default 行：控件按 type 动态切换（与旧编辑对话框一致）----
        self._detail_default_row = ctk.CTkFrame(self._detail_form,
                                                fg_color="transparent")
        self._detail_default_row.pack(fill="x", pady=2)
        self._detail_default_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._detail_default_row, text="default", width=90,
                     anchor="w").grid(row=0, column=0, padx=(0, 5), sticky="w")
        self._detail_default_widget: Any = None
        self._detail_row_frames["default"] = self._detail_default_row

        # ---- options 行：按钮列表（+ 添加 / 双击编辑 / X 删除）----
        self._detail_options: list[tuple[str, str]] = []
        self._detail_options_row = ctk.CTkFrame(self._detail_form,
                                                fg_color="transparent")
        self._detail_options_row.pack(fill="x", pady=2)
        self._detail_options_row.grid_columnconfigure(0, weight=1)
        opts_head = ctk.CTkFrame(self._detail_options_row,
                                 fg_color="transparent")
        opts_head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(opts_head, text="options", width=90,
                     anchor="w").pack(side="left")
        ctk.CTkButton(opts_head, text="+ 添加选项", width=80, height=22,
                      command=self._add_option_detail).pack(side="right")
        self._options_container = ctk.CTkScrollableFrame(
            self._detail_options_row,
            fg_color=("gray87", "gray20"), corner_radius=6,
            height=140)
        self._options_container.grid(row=1, column=0, sticky="ew",
                                     padx=(95, 0))
        self._options_container.grid_columnconfigure(0, weight=1)
        self._options_buttons: list[ctk.CTkFrame] = []
        self._detail_row_frames["options"] = self._detail_options_row

        for k in ("min", "max", "step"):
            _add_edit(k, k, lambda m: ctk.CTkEntry(m))
        # 条件行默认隐藏（default/options/min/max/step 按 type 显示）
        for k in ("options", "min", "max", "step"):
            self._detail_row_frames[k].pack_forget()
        self._detail_default_row.pack_forget()

        # 保存：变更即写回（FocusOut / Return / 下拉选择）
        def _wire_save(key: str, w: Any) -> None:
            if key == "type":
                return  # type 菜单 command 已在创建时绑定（显隐 + 保存），勿覆盖
            if isinstance(w, ctk.CTkOptionMenu):
                w.configure(command=lambda _v: self._save_detail_field())
            else:
                w.bind("<FocusOut>", lambda _e: self._save_detail_field())
                w.bind("<Return>", lambda _e: self._save_detail_field())
        for k, w in self._detail_edits.items():
            _wire_save(k, w)

        self._detail_form.pack_forget()  # 初始隐藏（空态）
        # 初始（无分组）：名称编辑行隐藏，仅显示分组空态提示
        self._sec_detail_row.pack_forget()

    def _save_section_detail(self) -> None:
        """分组名称编辑 → 写回当前分组并自动保存。"""
        sec = self._get_current_section()
        if sec is None:
            return
        name = self._sec_name_entry.get().strip()
        if not name or name == sec.get("section", ""):
            return
        sec["section"] = name
        self._refresh_section_list()
        self._auto_save()

    def _refresh_section_detail(self) -> None:
        """按当前选中分组填充名称（无分组 → 空态提示）。"""
        sec = self._get_current_section()
        if sec is None:
            # 无分组：显示提示，隐藏名称编辑行
            self._sec_detail_empty.pack(anchor="nw", fill="x", pady=(0, 8))
            self._sec_detail_row.pack_forget()
            return
        self._sec_detail_empty.pack_forget()
        self._sec_detail_row.pack(fill="x", pady=(0, 8))
        self._sec_name_entry.delete(0, "end")
        self._sec_name_entry.insert(0, str(sec.get("section", "")))

    def _refresh_field_detail(self) -> None:
        """按当前选中字段填充详情表单（无选中 → 空态）。"""
        sec = self._get_current_section()
        idx = self._selected_field
        field = None
        if sec is not None and 0 <= idx < len(sec["fields"]):
            field = sec["fields"][idx]

        if field is None:
            # 空态
            self._detail_empty.pack(anchor="nw", padx=10, pady=10)
            self._detail_form.pack_forget()
            return

        self._detail_empty.pack_forget()
        self._detail_form.pack(fill="both", expand=True)

        ftype = str(field.get("type", "text"))
        self._detail_type.set(ftype)
        self._set_detail_entry("key", str(field.get("key", "")))
        self._set_detail_entry("label", str(field.get("label", "")))
        self._set_detail_entry("description",
                               str(field.get("description", "")))
        for k in ("min", "max", "step"):
            v = field.get(k)
            self._set_detail_entry(k, "" if v is None else str(v))
        # options 按钮列表（select 专用；兼容旧字符串数组格式）
        self._detail_options = []
        for o in (field.get("options") or []):
            if isinstance(o, dict):
                val = str(o.get("value", ""))
                lbl = str(o.get("label", "")) or val
            else:
                val = lbl = str(o)
            if val:
                self._detail_options.append((val, lbl))
        self._refresh_options_display()
        # 行显隐 + 空重建（内部 _rebuild_default_widget 无恢复值）
        self._on_detail_type_changed()
        # default 控件恢复字段原默认值（重建在显隐之后，避免被覆盖）
        self._rebuild_default_widget(ftype, _fmt_detail_default(field))

    def _set_detail_entry(self, key: str, value: str) -> None:
        w = self._detail_edits.get(key)
        if isinstance(w, ctk.CTkEntry):
            w.delete(0, "end")
            if value:
                w.insert(0, value)

    def _rebuild_default_widget(self, new_type: str,
                                restore_value: str | None = None) -> None:
        """重建 default 行控件（与旧编辑对话框一致）。

        bool/channel/select → OptionMenu；其余 → Entry（placeholder 按 type）。
        ``restore_value`` 仅加载/选中字段时传入；切换 type 时传 None 不保留。
        """
        row = self._detail_default_row
        for w in row.grid_slaves(row=0, column=1):
            w.destroy()
        if new_type == "bool":
            widget = ctk.CTkOptionMenu(row, values=["true", "false"])
            if restore_value in ("true", "false"):
                widget.set(restore_value)
            else:
                widget.set("false")
        elif new_type == "channel":
            widget = ctk.CTkOptionMenu(row, values=["A", "B", "Both"])
            if restore_value and restore_value.lower() in ("a", "b", "both"):
                widget.set(restore_value.upper())
            else:
                widget.set("A")
        elif new_type == "select":
            opts = ([v for v, _ in self._detail_options]
                    if self._detail_options else ["(No Option)"])
            widget = ctk.CTkOptionMenu(row, values=opts)
            if restore_value in opts:
                widget.set(restore_value)
            else:
                widget.set(opts[0])
        else:
            widget = ctk.CTkEntry(row)
            widget._is_focused = False  # placeholder/焦点状态统一
            if restore_value:
                widget.insert(0, restore_value)
            if new_type == "percent":
                widget.configure(placeholder_text="0-100")
            elif new_type == "duration":
                widget.configure(placeholder_text=">= 0")
            elif new_type == "number":
                widget.configure(placeholder_text="number")
        widget.grid(row=0, column=1, sticky="ew")
        self._detail_default_widget = widget
        # 变更即保存
        if isinstance(widget, ctk.CTkOptionMenu):
            widget.configure(command=lambda _v: self._save_detail_field())
        else:
            widget.bind("<FocusOut>", lambda _e: self._save_detail_field())
            widget.bind("<Return>", lambda _e: self._save_detail_field())

    def _default_value(self) -> str:
        """读取 default 动态控件当前值（Entry → 文本；OptionMenu → 选项）。"""
        w = self._detail_default_widget
        if w is None:
            return ""
        if isinstance(w, ctk.CTkEntry):
            return w.get().strip()
        return str(w.get()).strip()

    def _refresh_options_display(self) -> None:
        """重建 options 列表（卡片行样式：value + label + X 删除；双击编辑）。"""
        for btn in self._options_buttons:
            btn.destroy()
        self._options_buttons.clear()
        hover_color = ("#D6E4F2", "gray28")
        for i, (val, lbl) in enumerate(self._detail_options):
            leave_color = (("gray94", "gray19") if i % 2
                           else ("gray88", "gray23"))
            row = ctk.CTkFrame(self._options_container,
                               fg_color=leave_color, corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(
                row, text=val, anchor="w",
                font=ctk.CTkFont(family="Consolas", size=13, weight="bold")
            ).grid(row=0, column=0, padx=(6, 6), pady=4)
            ctk.CTkLabel(
                row, text=lbl, anchor="e",
                font=ctk.CTkFont(size=12), text_color="gray"
            ).grid(row=0, column=1, sticky="ew", padx=(8, 8))
            del_btn = ctk.CTkButton(
                row, text="X", width=26, height=24,
                fg_color="transparent", hover_color="#8B0000",
                command=lambda idx=i: self._delete_option_detail(idx),
            )
            del_btn.grid(row=0, column=2, padx=(2, 4))
            # 双击行（X 按钮除外）→ 编辑
            row.bind("<Double-1>",
                     lambda e, idx=i: self._edit_option_detail(idx))
            for child in row.winfo_children():
                if child is del_btn:
                    continue
                child.bind("<Double-1>",
                           lambda e, idx=i: self._edit_option_detail(idx))
            # hover 高亮（X 按钮排除，避免与删除反馈色冲突）
            for w in (row, *[c for c in row.winfo_children()
                             if c is not del_btn]):
                w.bind("<Enter>", lambda e, r=row, hc=hover_color:
                       r.configure(fg_color=hc))
                w.bind("<Leave>", lambda e, r=row, lc=leave_color:
                       r.configure(fg_color=lc))
            self._options_buttons.append(row)

    def _option_prompt(self, title: str,
                       initial: tuple[str, str] = ("", "")) \
            -> tuple[str, str] | None:
        """选项添加/编辑对话框（value + label 双输入；label 留空 = 同 value）。"""
        dlg = ctk.CTkToplevel(self)
        dlg.title(title)
        dlg.geometry("350x160")
        dlg.resizable(False, False)
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        # 简单居中（父窗口中心）
        self.winfo_toplevel().update_idletasks()
        x = self.winfo_toplevel().winfo_rootx() + 80
        y = self.winfo_toplevel().winfo_rooty() + 120
        dlg.geometry(f"350x160+{x}+{y}")
        ctk.CTkLabel(dlg, text="值 (value):").grid(
            row=0, column=0, padx=10, pady=(10, 0), sticky="w")
        val_entry = ctk.CTkEntry(dlg, width=250)
        val_entry._is_focused = False
        val_entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 0))
        ctk.CTkLabel(dlg, text="标签 (label):").grid(
            row=1, column=0, padx=10, pady=(6, 0), sticky="w")
        lbl_entry = ctk.CTkEntry(dlg, width=250)
        lbl_entry._is_focused = False
        lbl_entry.grid(row=1, column=1, padx=(5, 10), pady=(6, 0))
        ctk.CTkLabel(dlg, text="标签留空时默认与值相同",
                     text_color=("gray50", "gray60"),
                     font=ctk.CTkFont(size=11)
                     ).grid(row=2, column=0, columnspan=2,
                            padx=10, sticky="w")
        if initial[0]:
            val_entry.insert(0, initial[0])
        if initial[1]:
            lbl_entry.insert(0, initial[1])
        val_entry.focus_set()
        result: list[tuple[str, str] | None] = [None]

        def on_ok() -> None:
            val = val_entry.get().strip()
            if val:
                lbl = lbl_entry.get().strip() or val
                result[0] = (val, lbl)
                dlg.destroy()

        def on_cancel() -> None:
            dlg.destroy()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e", pady=(15, 10))
        ctk.CTkButton(btn_row, text="取消", width=100,
                      command=on_cancel).pack(side="right", padx=5)
        ctk.CTkButton(btn_row, text="确定", width=100,
                      command=on_ok).pack(side="right", padx=5)
        val_entry.bind("<Return>", lambda _e: on_ok())
        lbl_entry.bind("<Return>", lambda _e: on_ok())
        dlg.wait_window()
        return result[0]

    def _add_option_detail(self) -> None:
        """添加选项（对话框输入，value 重复项忽略）。"""
        val = self._option_prompt("添加选项")
        if val is None or any(v == val[0] for v, _ in self._detail_options):
            return
        self._detail_options.append(val)
        self._refresh_options_display()
        self._save_detail_field()

    def _edit_option_detail(self, idx: int) -> None:
        """双击选项 → 编辑 value/label。"""
        if idx < 0 or idx >= len(self._detail_options):
            return
        old = self._detail_options[idx]
        val = self._option_prompt("编辑选项", initial=old)
        if val is None or not val[0]:
            return
        if any(v == val[0] for v, _ in self._detail_options) \
                and val[0] != old[0]:
            return
        self._detail_options[idx] = val
        self._refresh_options_display()
        self._save_detail_field()

    def _delete_option_detail(self, idx: int) -> None:
        """删除选项（X 按钮）。"""
        if idx < 0 or idx >= len(self._detail_options):
            return
        self._detail_options.pop(idx)
        self._refresh_options_display()
        self._save_detail_field()

    def _on_detail_type_changed(self) -> None:
        """按 type 显隐条件行 + 重建 default 控件（与旧编辑对话框一致）。

        全部 forget 后按固定顺序重排可见行——pack_forget 后重新 pack
        会追加到末尾，直接显隐会导致行顺序错乱。
        """
        ftype = self._detail_type.get()
        numeric = ftype in ("percent", "duration", "number")
        visible = {k for k in ("default", "options", "min", "max", "step")
                   if (k == "default" and ftype != "preset")
                   or (k == "options" and ftype == "select")
                   or (k in ("min", "max", "step") and numeric)}
        order = ["key", "type", "label", "description", "default",
                 "options", "min", "max", "step"]
        for k in order:
            self._detail_row_frames[k].pack_forget()
        for k in order:
            # 条件行按 visible 显隐；其余行恒显示
            if k in ("default", "options", "min", "max", "step")                     and k not in visible:
                continue
            self._detail_row_frames[k].pack(fill="x", pady=2)
        # default 控件按 type 重建（切换 type 不保留旧值——与旧对话框一致）
        self._rebuild_default_widget(ftype)

    def _save_detail_field(self) -> None:
        """把详情表单写回 sec["fields"][idx]（或新建字段）并自动保存。"""
        sec = self._get_current_section()
        if sec is None:
            return
        idx = self._selected_field
        if idx < 0 or idx >= len(sec["fields"]):
            return
        field = sec["fields"][idx]
        ftype = self._detail_type.get()

        key = self._entry_text("key")
        label = self._entry_text("label")
        if not key or not label:
            return  # key/label 必填，缺失时不写入
        field["key"] = key
        field["type"] = ftype
        field["label"] = label
        desc = self._entry_text("description")
        if desc:
            field["description"] = desc
        else:
            field.pop("description", None)
        # default 按类型转换（读动态控件）
        raw = self._default_value()
        field.pop("default", None)
        if raw:
            if ftype == "bool":
                field["default"] = (raw.lower() in ("true", "1", "yes"))
            elif ftype in ("percent", "duration", "number"):
                try:
                    field["default"] = int(raw) if ftype == "percent" \
                        else (float(raw) if "." in raw else int(raw))
                except ValueError:
                    pass
            else:
                field["default"] = raw
        # min/max/step
        for k in ("min", "max", "step"):
            raw = self._entry_text(k)
            field.pop(k, None)
            if raw:
                try:
                    field[k] = float(raw) if "." in raw else int(raw)
                except ValueError:
                    pass
        # options（select，按钮列表写回——服务端要求的条目列表格式）
        field.pop("options", None)
        if ftype == "select" and self._detail_options:
            field["options"] = [{"value": v, "label": l}
                                for v, l in self._detail_options]
        self._refresh_fields_display()
        self._auto_save()

    def _entry_text(self, key: str) -> str:
        w = self._detail_edits.get(key)
        return w.get().strip() if isinstance(w, ctk.CTkEntry) else ""


    # ------------------------------------------------------------------
    # directory selection
    # ------------------------------------------------------------------

    def set_plugin_dir(self, d: str, pm: ProjectManager | None = None) -> None:
        """Set plugin directory and load manifest from project manager."""
        if pm:
            self._pm = pm
        self._set_enabled(True)
        self._plugin_dir = d

        if self._pm:
            data = self._pm.read_manifest()
            self._load_manifest(data)
            self._auto_save_enabled = True

    # ------------------------------------------------------------------
    # load / save
    # ------------------------------------------------------------------

    def _get_field_value(self, key: str) -> str:
        """Get value from a basic-info field widget (CTkEntry or CTkTextbox)."""
        w = self._fields[key]
        if isinstance(w, ctk.CTkTextbox):
            return w.get("1.0", "end").strip()
        return w.get().strip()

    def _set_field_value(self, key: str, val: str) -> None:
        """Set value of a basic-info field widget (CTkEntry or CTkTextbox)."""
        w = self._fields[key]
        if isinstance(w, ctk.CTkTextbox):
            w.delete("1.0", "end")
            w.insert("1.0", val)
        else:
            w.delete(0, "end")
            if val:  # 空值不 insert——insert(0, "") 会撤销 placeholder 显示
                w.insert(0, val)

    def _load_manifest(self, data: dict) -> None:
        """Populate the form from an existing manifest dict."""
        for key in self._fields:
            if key in data:
                val = data[key]
                if isinstance(val, bool):
                    val = str(val).lower()
                self._set_field_value(key, str(val) if val is not None else "")
            else:
                self._set_field_value(key, "")

        caps = data.get("capabilities", {})
        self._cb_startup_check.deselect()
        if caps.get("startup_check"):
            self._cb_startup_check.select()

        # sections（加载后默认选中第一个字段）
        self._sections = list(data.get("config_schema", []))
        self._selected_field = 0
        self._refresh_section_list()
        self._refresh_fields_display()
        self._refresh_section_detail()
        self._refresh_field_detail()

    def _build_manifest(self) -> dict:
        """Build manifest dict from form state."""
        data: dict[str, Any] = {}
        for key in self._fields:
            val = self._get_field_value(key)
            if val:
                data[key] = val

        data["sdk"] = "1"

        if self._cb_startup_check.get():
            data["capabilities"] = {"startup_check": True}

        if self._sections:
            data["config_schema"] = self._sections

        return data

    # ------------------------------------------------------------------
    # field level feedback
    # ------------------------------------------------------------------

    _FIELD_KEYWORDS: dict[str, str] = {
        "id ": "id",
        "name ": "name",
        "version ": "version",
        "entry ": "entry",
        "缺少必需字段: id": "id",
        "缺少必需字段: name": "name",
        "缺少必需字段: version": "version",
    }

    def _clear_field_borders(self) -> None:
        for key, widget in self._fields.items():
            if isinstance(widget, ctk.CTkEntry):
                widget.configure(border_width=0)
                if key in self._field_errors:
                    widget.configure(text_color=("gray10", "gray90"))
        self._field_errors.clear()

    def _highlight_field(self, key: str, error_text: str = "") -> None:
        widget = self._fields.get(key)
        if isinstance(widget, ctk.CTkEntry):
            widget.configure(border_width=2, border_color="red", text_color="red")
            if error_text:
                self._field_errors[key] = error_text
                widget.delete(0, "end")
                widget.insert(0, error_text)

    def _highlight_errors_from_validation(self, errors: list[str]) -> None:
        """Parse validation error messages and highlight corresponding fields."""
        for err in errors:
            for keyword, field_key in self._FIELD_KEYWORDS.items():
                if err.startswith(keyword):
                    self._highlight_field(field_key, err)
                    break

    def _auto_save(self) -> None:
        """Write current form state to project manager (no-op until enabled)."""
        if not self._auto_save_enabled or not self._pm:
            return
        data = self._build_manifest()
        self._pm.write_manifest(data)

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------



    # ------------------------------------------------------------------
    # external access
    # ------------------------------------------------------------------

    def get_plugin_dir(self) -> str | None:
        return self._plugin_dir

    def get_manifest_data(self) -> dict:
        return self._build_manifest()


import os  # noqa: E402 (needed for _load_manifest / _save_manifest)
