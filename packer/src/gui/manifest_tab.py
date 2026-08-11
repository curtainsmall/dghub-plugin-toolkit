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
        self._selected_field: int = 0
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
        try:
            self._preview._textbox.configure(state=entry_state, takefocus=bool(enabled))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # header
        self.grid_rowconfigure(1, weight=1)  # main content

        # -- header --
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header, text="Manifest 编辑器",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left")

        # -- main area: left (form) + right (preview) --
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
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

        # -- right side: preview --
        preview_header = ctk.CTkFrame(right, fg_color="transparent")
        preview_header.pack(anchor="nw", fill="x", pady=(0, 5))
        ctk.CTkLabel(preview_header, text="JSON 预览",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        self._preview_wrap_var = ctk.BooleanVar(value=False)
        self._preview_wrap_cb = ctk.CTkCheckBox(preview_header, text="换行", variable=self._preview_wrap_var,
                        command=self._toggle_preview_wrap)
        self._preview_wrap_cb.pack(side="right", padx=5)
        self._controls.append(self._preview_wrap_cb)
        self._preview = ctk.CTkTextbox(right, wrap="none", font=("Consolas", 12))
        self._preview.pack(fill="both", expand=True)
        self._controls.append(self._preview)

        # -- bottom bar --
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
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
        self._refresh_preview()
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
                                                  command=self._refresh_preview)
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

        ctk.CTkLabel(sec_left, text="配置分组 (Section)",
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
        dialog = ctk.CTkInputDialog(text="输入分组名称 (section):", title="添加分组")
        dialog.withdraw()
        self._center_dlg(dialog, self.winfo_toplevel())
        dialog.deiconify()
        name = dialog.get_input()
        if name and name.strip():
            self._sections.append({"section": name.strip(), "fields": []})
            self._selected_section = len(self._sections) - 1  # auto-select new
            self._section_container.configure(border_width=0)
            self._refresh_section_list()
            self._refresh_fields_display()
            self._refresh_preview()

    def _delete_section(self) -> None:
        sel = self._get_selected_section_index()
        if sel is not None and 0 <= sel < len(self._sections):
            if messagebox.askyesno("确认", f"删除分组 '{self._sections[sel]['section']}'？"):
                self._sections.pop(sel)
                # keep selection valid
                if self._selected_section >= len(self._sections):
                    self._selected_section = max(0, len(self._sections) - 1)
                self._refresh_section_list()
                self._refresh_fields_display()
                self._refresh_preview()

    def _on_section_click(self, idx: int) -> None:
        """Handle click on a section button - update selection and highlight."""
        if 0 <= idx < len(self._sections):
            self._selected_section = idx
            self._selected_field = 0
            self._section_container.configure(border_width=0)
            self._refresh_section_list()
            self._refresh_fields_display()
    
    def _on_field_click(self, idx: int) -> None:
        """双击字段行 → 编辑；同时记录当前字段供删除按钮定位。"""
        sec = self._get_current_section()
        if sec is None or idx >= len(sec["fields"]):
            return
        self._selected_field = idx  # 操作目标（无视觉选中态）
        self._edit_field_at(idx)

    def _edit_field_at(self, idx: int) -> None:
        """Open editor for the field at given index (used by double-click)."""
        sec = self._get_current_section()
        if sec is None or idx >= len(sec["fields"]):
            return
        old = sec["fields"][idx]
        updated = self._field_dialog(existing=old)
        if updated:
            sec["fields"][idx] = updated
            self._refresh_fields_display()
            self._refresh_preview()

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

            # 卡片式行（斑马纹 + 圆角；字段无持久选中态，恒斑马底色）
            leave_color = (("gray94", "gray19") if j % 2
                           else ("gray88", "gray23"))
            row = ctk.CTkFrame(
                self._field_container,
                fg_color=leave_color,
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

            # 整行可双击 → 编辑字段（无选中态，单击不做事）
            row.bind("<Double-1>",
                     lambda e, idx=j: self._on_field_click(idx))
            for child in row.winfo_children():
                child.bind(
                    "<Double-1>", lambda e, idx=j: self._on_field_click(idx))

            # hover 高亮：进入行区域提升底色，离开恢复斑马底色
            hover_color = ("#D6E4F2", "gray28")
            for w in (row, *row.winfo_children()):
                w.bind("<Enter>",
                       lambda e, r=row, hc=hover_color:
                       r.configure(fg_color=hc))
                w.bind("<Leave>",
                       lambda e, r=row, lc=leave_color:
                       r.configure(fg_color=lc))
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
            self._field_error_label.configure(text="请先选择一个配置分组")
            self._field_error_label.grid(row=0, column=0)
            self._error_label.configure(text="", text_color="red")
            return
        field = self._field_dialog()
        if field:
            sec["fields"].append(field)
            self._refresh_section_list()  # 字段数变化 → 刷新 section 计数
            self._refresh_fields_display()
            self._refresh_preview()

    def _delete_field(self) -> None:
        sec = self._get_current_section()
        if sec is None or not sec["fields"]:
            return
        idx = self._selected_field
        if idx >= len(sec["fields"]):
            return
        if messagebox.askyesno("确认", f"删除字段 '{sec['fields'][idx].get('key', '?')}'？"):
            sec["fields"].pop(idx)
            if self._selected_field >= len(sec["fields"]):
                self._selected_field = max(0, len(sec["fields"]) - 1)
            self._refresh_section_list()  # 字段数变化 → 刷新 section 计数
            self._refresh_fields_display()
            self._refresh_preview()

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

    def _center_dlg(self, child: ctk.CTkToplevel, parent_win: Any) -> None:
        """Center child dialog on parent window, clamped within parent bounds."""
        center_dialog(child, parent_win)

    def _field_dialog(self, existing: dict | None = None) -> dict | None:
        """Open a dialog for adding/editing a field. Returns field dict or None."""
        win = ctk.CTkToplevel(self)
        win.title("编辑字段" if existing else "添加字段")
        win.geometry("420x520")
        win.resizable(False, False)
        win.grid_columnconfigure(0, weight=1)
        win.transient(self)
        win.grab_set()

        self._center_dlg(win, self.winfo_toplevel())

        entries: dict[str, Any] = {}
        error_labels: dict[str, ctk.CTkLabel] = {}
        row_frames: dict[str, ctk.CTkFrame] = {}
        result: dict | None = None
        row = 0

        # For select type interactive options list
        _options_list: list[str] = []
        _options_buttons: list[ctk.CTkButton] = []
        _options_area: ctk.CTkFrame | None = None

        # Placeholder hints for constrained entry fields
        _PLACEHOLDER_MAP: dict[str, str] = {
            "min": "number",
            "max": "number",
            "step": "> 0",
        }

        def add_row(label: str, key: str,
                    widget_type: str = "entry",
                    options: list[str] | None = None,
                    pady: int = 1,
                    required: bool = False) -> ctk.CTkFrame:
            """Add a labelled row with optional inline error label."""
            nonlocal row
            frame = ctk.CTkFrame(win, fg_color="transparent")
            frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=pady)
            frame.grid_columnconfigure(0, minsize=85)
            frame.grid_columnconfigure(1, weight=1)
            # Label area — supports red * for required fields
            label_area = ctk.CTkFrame(frame, fg_color="transparent")
            label_area.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(label_area, text=label, anchor="w").pack(side="left")
            if required:
                ctk.CTkLabel(label_area, text="*", text_color="red",
                             font=ctk.CTkFont(size=12)).pack(side="left")
            if widget_type == "entry":
                e = ctk.CTkEntry(frame, width=250)
                e._is_focused = False  # placeholder 统一激活（6.0.0 初始聚焦态）
                e.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing and key in existing:
                    val = existing[key]
                    if isinstance(val, (int, float)):
                        val = str(val)
                    elif isinstance(val, list):
                        val = ", ".join(str(v) for v in val)
                    elif isinstance(val, bool):
                        val = "true" if val else "false"
                    if val is not None and str(val) != "":
                        # 空值不 insert——insert(0, "") 会撤销 placeholder 显示
                        e.insert(0, str(val))
                entries[key] = e
                # Placeholder hint for constrained fields
                _ph = _PLACEHOLDER_MAP.get(key, "")
                if _ph:
                    e.configure(placeholder_text=_ph)
                # Inline error label (hidden initially, only shown on error)
                err = ctk.CTkLabel(frame, text="", text_color="#FF4444",
                                   font=ctk.CTkFont(size=10), anchor="w")
                err.grid(row=2, column=0, columnspan=2, sticky="w", padx=(85, 0))
                err.grid_remove()
                error_labels[key] = err
            elif widget_type == "combo":
                cb = ctk.CTkOptionMenu(frame, values=options or [], width=250)
                cb.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing and key in existing:
                    cb.set(str(existing[key]))
                else:
                    cb.set(options[0] if options else "")
                entries[key] = cb
            row += 1
            return frame

        # Always-visible rows (no spacing between them)
        add_row("键名 (key)", "key", pady=0, required=True)
        type_frame = add_row("类型 (type)", "type", "combo",
                             list(FIELD_TYPE_LABELS.keys()), pady=0, required=True)
        add_row("标签 (label)", "label", pady=0, required=True)

        # Create all optional rows up front, hidden initially
        optional_keys = ["description", "min", "max", "step"]
        labels_map = {
            "description": "描述 (description)",
            "min": "最小值 (min)",
            "max": "最大值 (max)",
            "step": "步长 (step)",
        }
        for k in optional_keys:
            f = add_row(labels_map[k], k)
            f.grid_remove()
            row_frames[k] = f

        # Create "default" row separately — widget type depends on field type
        _default_frame = ctk.CTkFrame(win, fg_color="transparent")
        _default_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=10, pady=1)
        _default_frame.grid_columnconfigure(1, weight=1)
        _default_label_area = ctk.CTkFrame(_default_frame, fg_color="transparent")
        _default_label_area.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(_default_label_area, text="默认值 (default)", anchor="w", width=80).pack(side="left")
        _default_entry = ctk.CTkEntry(_default_frame, width=250)
        _default_entry._is_focused = False  # placeholder/焦点状态统一
        _default_entry.grid(row=0, column=1, padx=(5, 0), sticky="e")
        if existing and "default" in existing:
            val = existing["default"]
            if isinstance(val, bool):
                _default_entry.insert(0, "true" if val else "false")
            else:
                _default_entry.insert(0, str(val))
        entries["default"] = _default_entry
        # Inline error for default
        _default_err = ctk.CTkLabel(_default_frame, text="", text_color="#FF4444",
                                    font=ctk.CTkFont(size=10), anchor="w")
        _default_err.grid(row=2, column=0, columnspan=2, sticky="w", padx=(85, 0))
        _default_err.grid_remove()
        error_labels["default"] = _default_err
        row_frames["default"] = _default_frame
        row += 1

        def _rebuild_default_widget(new_type: str, restore: bool = True) -> None:
            """Replace default widget with appropriate type (Entry/Combo).

            ``restore=True``（仅初始加载）恢复 existing 字段的原默认值；
            用户切换类型后不保留上一类型的默认值，改用新类型默认。
            """
            frame = row_frames["default"]
            # Destroy old widget in column 1
            for w in frame.grid_slaves(row=0, column=1):
                w.destroy()
        
            # 仅初始加载恢复旧值；切换类型后不保留
            existing_default = None
            if restore and existing and "default" in existing:
                existing_default = existing["default"]
        
            if new_type == "bool":
                widget = ctk.CTkOptionMenu(frame, values=["true", "false"], width=250)
                widget.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing_default is not None and isinstance(existing_default, bool):
                    widget.set("true" if existing_default else "false")
                else:
                    widget.set("false")
            elif new_type == "channel":
                widget = ctk.CTkOptionMenu(frame, values=["A", "B", "Both"], width=250)
                widget.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing_default is not None and existing_default in ("a", "b", "both"):
                    widget.set(existing_default.upper())
                else:
                    widget.set("A")
            elif new_type == "select":
                opts = _options_list[:] if _options_list else ["(No Option)"]
                widget = ctk.CTkOptionMenu(frame, values=opts, width=250)
                widget.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing_default is not None and existing_default in opts:
                    widget.set(existing_default)
                else:
                    widget.set(opts[0])
            else:
                widget = ctk.CTkEntry(frame, width=250)
                widget._is_focused = False  # placeholder 统一激活
                widget.grid(row=0, column=1, padx=(5, 0), sticky="e")
                if existing_default is not None:
                    val_str = str(existing_default)
                    if isinstance(existing_default, bool):
                        val_str = "true" if existing_default else "false"
                    widget.insert(0, val_str)
                # Placeholder by type
                if new_type == "percent":
                    widget.configure(placeholder_text="0-100")
                elif new_type == "duration":
                    widget.configure(placeholder_text=">= 0")
                elif new_type == "number":
                    widget.configure(placeholder_text="number")
            entries["default"] = widget

        # 当前对话框显示的类型（None = 尚未初始化，首次调用视为初始加载）
        _current_dlg_type: list[str | None] = [None]

        def on_type_change(new_type: str) -> None:
            """Show/hide optional rows based on selected type."""
            visible = set(self._TYPE_EXTRA.get(new_type, []))
            for k in optional_keys:
                if k in visible:
                    row_frames[k].grid()
                else:
                    row_frames[k].grid_remove()
            # Show/hide default row (handled separately)
            if "default" in visible:
                row_frames["default"].grid()
            else:
                row_frames["default"].grid_remove()
            # Show/hide select options list
            if new_type == "select":
                if _options_area is not None:
                    _options_area.grid()
            else:
                if _options_area is not None:
                    _options_area.grid_remove()
            # Rebuild default widget to match type；仅初始加载恢复旧值，
            # 切换类型时清空（不保留上一类型的默认值）
            restore = (_current_dlg_type[0] is None)
            _rebuild_default_widget(new_type, restore)
            _current_dlg_type[0] = new_type
            _clear_errors()

        # ----------------------------------------------------------------
        # Select options list
        # ----------------------------------------------------------------

        def _refresh_options_display() -> None:
            """Rebuild the options button list."""
            if _options_container is None:
                return
            for btn in _options_buttons:
                btn.destroy()
            _options_buttons.clear()
            for i, opt in enumerate(_options_list):
                row_f = ctk.CTkFrame(_options_container, fg_color="transparent")
                row_f.pack(fill="x", padx=2, pady=1)
                btn = ctk.CTkButton(
                    row_f, text=opt, anchor="w", height=26,
                    fg_color="transparent", hover_color="#1F5380",
                    command=lambda idx=i: _edit_option(idx),
                )
                btn.pack(side="left", fill="x", expand=True)
                del_btn = ctk.CTkButton(
                    row_f, text="X", width=28, height=26,
                    fg_color="transparent", hover_color="#8B0000",
                    command=lambda idx=i: _delete_option(idx),
                )
                del_btn.pack(side="right", padx=(2, 0))
                _options_buttons.append(row_f)

        def _add_option() -> None:
            """Add a new option via dialog."""
            dlg = ctk.CTkToplevel(win)
            dlg.title("添加选项")
            dlg.geometry("350x120")
            dlg.transient(win)
            dlg.grab_set()
            self._center_dlg(dlg, win)
            ctk.CTkLabel(dlg, text="选项文本:").grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
            entry = ctk.CTkEntry(dlg, width=250)
            entry._is_focused = False  # placeholder/焦点状态统一
            entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 0))
            entry.focus_set()
            result_opt: str | None = None
            def on_ok_opt() -> None:
                nonlocal result_opt
                val = entry.get().strip()
                if not val:
                    return
                if val in _options_list:
                    ctk.CTkLabel(dlg, text="选项已存在", text_color="red",
                                 font=ctk.CTkFont(size=10)).grid(row=2, column=0, columnspan=2)
                    return
                result_opt = val
                dlg.destroy()
            def on_cancel_opt() -> None:
                dlg.destroy()
            ctk.CTkButton(dlg, text="确定", command=on_ok_opt).grid(row=1, column=0, pady=15)
            ctk.CTkButton(dlg, text="取消", command=on_cancel_opt).grid(row=1, column=1)
            entry.bind("<Return>", lambda _: on_ok_opt())
            self._center_dlg(dlg, win)
            self.wait_window(dlg)
            if result_opt is not None:
                _options_list.append(result_opt)
                _refresh_options_display()
                _rebuild_default_widget("select")

        def _edit_option(idx: int) -> None:
            """Edit an existing option via dialog."""
            old_val = _options_list[idx]
            dlg = ctk.CTkToplevel(win)
            dlg.title("编辑选项")
            dlg.geometry("350x120")
            dlg.transient(win)
            dlg.grab_set()
            self._center_dlg(dlg, win)
            ctk.CTkLabel(dlg, text="选项文本:").grid(row=0, column=0, padx=10, pady=(10, 0), sticky="w")
            entry = ctk.CTkEntry(dlg, width=250)
            entry._is_focused = False  # placeholder/焦点状态统一
            entry.grid(row=0, column=1, padx=(5, 10), pady=(10, 0))
            entry.insert(0, old_val)
            entry.focus_set()
            result_opt: str | None = None
            def on_ok_opt() -> None:
                nonlocal result_opt
                val = entry.get().strip()
                if not val:
                    return
                if val != old_val and val in _options_list:
                    ctk.CTkLabel(dlg, text="选项已存在", text_color="red",
                                 font=ctk.CTkFont(size=10)).grid(row=2, column=0, columnspan=2)
                    return
                result_opt = val
                dlg.destroy()
            def on_cancel_opt() -> None:
                dlg.destroy()
            ctk.CTkButton(dlg, text="确定", command=on_ok_opt).grid(row=1, column=0, pady=15)
            ctk.CTkButton(dlg, text="取消", command=on_cancel_opt).grid(row=1, column=1)
            entry.bind("<Return>", lambda _: on_ok_opt())
            self.wait_window(dlg)
            if result_opt is not None:
                _options_list[idx] = result_opt
                # If default was set to the old value, update it
                default_w = entries["default"]
                if isinstance(default_w, ctk.CTkOptionMenu) and default_w.get() == old_val:
                    default_w.set(result_opt)
                _refresh_options_display()
                _rebuild_default_widget("select")

        def _delete_option(idx: int) -> None:
            """Delete an option with confirmation."""
            if not messagebox.askyesno("确认", f"删除选项 '{_options_list[idx]}'？", parent=win):
                return
            _options_list.pop(idx)
            _refresh_options_display()
            _rebuild_default_widget("select")

        # Build select options area (hidden initially)
        _options_area = ctk.CTkFrame(win, fg_color="transparent")
        _options_header = ctk.CTkFrame(_options_area, fg_color="transparent")
        _options_header.pack(fill="x", padx=10, pady=(5, 2))
        ctk.CTkLabel(_options_header, text="选项列表",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(_options_header, text="+ 添加", width=60, height=24,
                       command=_add_option).pack(side="right")
        _options_container = ctk.CTkScrollableFrame(_options_area, height=80)
        _options_container.pack(fill="x", padx=10, pady=(0, 5))
        _options_area.grid(row=row, column=0, columnspan=2, sticky="ew")
        _options_area.grid_remove()
        row += 1

        # Load existing options for select type
        if existing and "options" in existing and isinstance(existing["options"], list):
            _options_list = [str(o) for o in existing["options"]]

        # ----------------------------------------------------------------
        # Validation helpers
        # ----------------------------------------------------------------

        def _set_error(key: str, msg: str) -> None:
            """Mark an entry field as invalid with red border + error text."""
            w = entries.get(key)
            if isinstance(w, ctk.CTkEntry):
                w.configure(border_color="#FF4444")
            if key in error_labels:
                error_labels[key].configure(text=msg)
                error_labels[key].grid()

        def _clear_errors() -> None:
            """Reset all entry fields to normal state."""
            for key, w in entries.items():
                if isinstance(w, ctk.CTkEntry):
                    w.configure(border_color="")
            for key, lbl in error_labels.items():
                lbl.configure(text="")
                lbl.grid_remove()

        def _validate_all() -> bool:
            """Validate all visible fields. Returns True if valid."""
            _clear_errors()
            ftype = entries["type"].get()
            # key and label are always visible
            if not entries["key"].get().strip():
                _set_error("key", "Key 不能为空")
                return False
            if not entries["label"].get().strip():
                _set_error("label", "Label 不能为空")
                return False
            # Default value validation by type
            default_w = entries["default"]
            if ftype in ("bool", "channel", "select"):
                pass  # dropdown already constrains values
            elif ftype == "preset":
                pass  # no default
            elif isinstance(default_w, ctk.CTkEntry):
                raw = default_w.get().strip()
                if raw:
                    try:
                        if ftype == "percent":
                            v = int(raw)
                            if v < 0 or v > 100:
                                _set_error("default", "percent 值必须在 0-100 之间")
                                return False
                        elif ftype == "duration":
                            v = float(raw)
                            if v < 0:
                                _set_error("default", "duration 必须 >= 0")
                                return False
                        elif ftype == "number":
                            if "." in raw:
                                float(raw)
                            else:
                                int(raw)
                            # Check against min/max if both present
                            min_raw = entries["min"].get().strip()
                            max_raw = entries["max"].get().strip()
                            if min_raw and max_raw:
                                min_v = float(min_raw)
                                max_v = float(max_raw)
                                if min_v > max_v:
                                    _set_error("min", "min 必须 <= max")
                                    _set_error("max", "max 必须 >= min")
                                    return False
                    except ValueError:
                        _set_error("default", f"无效的数值: {raw}")
                        return False
            # min / max / step validation
            for k in ("min", "max", "step"):
                w = entries.get(k)
                if w and isinstance(w, ctk.CTkEntry):
                    raw = w.get().strip()
                    if raw:
                        try:
                            v = float(raw) if "." in raw else int(raw)
                            if k == "step" and v <= 0:
                                _set_error(k, "step 必须 > 0")
                                return False
                        except ValueError:
                            _set_error(k, f"无效的数值: {raw}")
                            return False
            return True

        # Bind type change — CustomTkinter OptionMenu supports command
        type_widget = entries["type"]
        if isinstance(type_widget, ctk.CTkOptionMenu):
            type_widget.configure(command=on_type_change)
            # Trigger initial show
            current_type = type_widget.get()
            on_type_change(current_type)

        def on_ok() -> None:
            nonlocal result
            if not _validate_all():
                return
            ftype = entries["type"].get()
            field: dict[str, Any] = {
                "key": entries["key"].get().strip(),
                "type": ftype,
                "label": entries["label"].get().strip(),
            }
            # Read and coerce "default"
            default_w = entries["default"]
            if isinstance(default_w, ctk.CTkOptionMenu):
                raw = default_w.get()
                if raw not in ("(No Option)", ""):
                    if ftype == "bool":
                        field["default"] = (raw == "true")
                    elif ftype == "channel":
                        field["default"] = raw.lower()  # "a"/"b"/"both"
                    elif ftype == "select":
                        field["default"] = raw
            elif isinstance(default_w, ctk.CTkEntry):
                raw = default_w.get().strip()
                if raw:
                    if ftype == "percent":
                        field["default"] = int(raw)
                    elif ftype == "duration":
                        field["default"] = float(raw)
                    elif ftype == "number":
                        field["default"] = float(raw) if "." in raw else int(raw)
                    else:
                        field["default"] = raw
            # description
            if entries["description"].get().strip():
                field["description"] = entries["description"].get().strip()
            # min / max / step (numeric)
            for k in ("min", "max", "step"):
                w = entries.get(k)
                if w and isinstance(w, ctk.CTkEntry):
                    raw = w.get().strip()
                    if raw:
                        field[k] = float(raw) if "." in raw else int(raw)
            # select options
            if ftype == "select" and _options_list:
                field["options"] = _options_list[:]
            result = field
            win.destroy()

        # 底部按钮：右对齐（确定在左、取消在最右）
        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.grid(row=row, column=0, columnspan=2, sticky="e",
                       padx=15, pady=15)
        ctk.CTkButton(btn_frame, text="取消", width=80,
                      command=win.destroy).pack(side="right")
        ctk.CTkButton(btn_frame, text="确定", width=80,
                      command=on_ok).pack(side="right", padx=(8, 0))

        self.wait_window(win)
        return result

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

        # sections
        self._sections = list(data.get("config_schema", []))
        self._selected_field = 0
        self._refresh_section_list()
        self._refresh_fields_display()
        self._refresh_preview()

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

    def _refresh_preview(self) -> None:
        data = self._build_manifest()
        self._auto_save()
        text = json.dumps(data, ensure_ascii=False, indent=2)
        self._preview.configure(state="normal")
        self._preview._textbox.configure(state="normal")
        self._preview.delete("1.0", "end")
        self._preview.insert("1.0", text)
        self._preview.configure(state="disabled")
        self._preview._textbox.configure(state="disabled")

    def _toggle_preview_wrap(self) -> None:
        """Toggle JSON preview word wrap."""
        wrap_mode = "word" if self._preview_wrap_var.get() else "none"
        self._preview.configure(wrap=wrap_mode)

    # ------------------------------------------------------------------
    # external access
    # ------------------------------------------------------------------

    def get_plugin_dir(self) -> str | None:
        return self._plugin_dir

    def get_manifest_data(self) -> dict:
        return self._build_manifest()


import os  # noqa: E402 (needed for _load_manifest / _save_manifest)
