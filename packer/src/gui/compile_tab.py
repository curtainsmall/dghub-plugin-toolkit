"""Compile tab — compile 编译选择与设置（下拉单选 + 字段联动）。

编译由 ``compile_system`` 字段显式单选：""（无）/ "python" / "node" / "command"。
选中后显示对应设置字段；一切语言相关解析（清单识别、[tool.dghub].entry）
在编译内（backend.compilers），本页只做 UI 呈现与持久化。
"""

import subprocess
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from backend.py_compiler import _get_python_exe
from backend.compilers import COMPILERS, COMPILER_CHOICES, get_compiler
from backend.project_manager import ProjectManager
from backend.winflags import _NO_WINDOW
from gui.widgets import ToolTip

# 右栏各行统一的前导标签宽度（像素）
_LABEL_W = 92


class CompileTab(ctk.CTkFrame):
    """编译页：下拉单选 + 对应设置字段（Python / Command / 无）。"""

    def __init__(self, master: Any,
                 on_changed: Callable[[], None] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._pm: ProjectManager | None = None
        self._plugin_dir: str | None = None
        self._loading = False
        self._on_changed = on_changed
        self._controls: list[ctk.CTkBaseClass] = []
        self._enabled = False

        # 状态变量
        self._compile_system_var = ctk.StringVar(value="")
        self._manifest_var = ctk.StringVar(value="")
        self._include_sdk_var = ctk.BooleanVar(value=True)
        self._compile_var = ctk.StringVar(value="")   # 编译命令字符串
        self._compile_dir = ""  # 执行目录（绝对路径；空 = 项目根）

        self._build_ui()
        self._set_enabled(False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        state = "normal" if enabled else "disabled"
        for w in self._controls:
            try:
                w.configure(state=state)
            except Exception:
                pass
        self._update_visibility()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # 编译选择（下拉单选）
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=10, pady=(10, 0))
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text="编译系统", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        self._proc_menu = ctk.CTkOptionMenu(
            row, width=220, values=[label for _, label in COMPILER_CHOICES],
            command=self._on_compile_changed)
        self._proc_menu.grid(row=0, column=1, sticky="w", padx=5)
        self._controls.append(self._proc_menu)
        self._proc_hint = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"), anchor="w", wraplength=600,
            justify="left")
        self._proc_hint.grid(row=0, column=2, sticky="w", padx=(10, 0))

        # ---- (None) 设置区（compile_system="" 时显示）----
        self._none_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._none_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                              padx=10, pady=(10, 0))
        ctk.CTkLabel(
            self._none_frame, text="不执行编译：直接收集打包内容（构建页配置）",
            font=ctk.CTkFont(size=13), text_color=("gray40", "gray60"),
            anchor="w", wraplength=700, justify="left").pack(
            anchor="w", padx=4, pady=8)

        # ---- Python 设置区（compile_system="python" 时显示）----
        self._py_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._py_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                            padx=10, pady=(10, 0))
        self._py_frame.grid_columnconfigure(1, weight=1)
        self._py_frame.grid_remove()

        ctk.CTkLabel(self._py_frame, text="依赖清单", width=_LABEL_W,
                     anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        self._manifest_label = ctk.CTkLabel(
            self._py_frame, text="未选择", anchor="w",
            fg_color=("gray85", "gray25"), corner_radius=6, width=1)
        self._manifest_label.grid(row=0, column=1, sticky="ew", padx=5, pady=4)
        self._manifest_btn = ctk.CTkButton(
            self._py_frame, text="选择文件", width=90,
            command=self._pick_manifest)
        self._manifest_btn.grid(row=0, column=2, padx=(5, 0))
        self._controls.extend([self._manifest_label, self._manifest_btn])

        self._include_sdk_cb = ctk.CTkCheckBox(
            self._py_frame, text="包含 dghub-sdk",
            variable=self._include_sdk_var,
            command=self._on_setting_changed)
        self._include_sdk_cb.grid(row=1, column=1, sticky="w", padx=5, pady=4)
        self._controls.append(self._include_sdk_cb)

        self._pyinstaller_hint = ctk.CTkLabel(
            self._py_frame, text="", font=ctk.CTkFont(size=12),
            text_color="gray", anchor="w")
        self._pyinstaller_hint.grid(row=2, column=1, sticky="w", padx=5)

        # ---- Command 设置区（compile_system="command" 时显示）----
        self._cmd_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._cmd_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                             padx=10, pady=(10, 0))
        self._cmd_frame.grid_columnconfigure(1, weight=1)
        self._cmd_frame.grid_remove()

        ctk.CTkLabel(self._cmd_frame, text="编译命令", width=_LABEL_W,
                     anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        self._compile_entry = ctk.CTkEntry(
            self._cmd_frame, textvariable=self._compile_var,
            placeholder_text="可选，如 dotnet build -c Release，构建前执行")
        self._compile_entry.grid(row=0, column=1, sticky="ew", padx=5)
        self._controls.append(self._compile_entry)

        ctk.CTkLabel(self._cmd_frame, text="执行目录", width=_LABEL_W,
                     anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=1, column=0, padx=(0, 5), pady=(8, 0), sticky="w")
        exec_frame = ctk.CTkFrame(self._cmd_frame,
                                  fg_color=("gray85", "gray25"),
                                  border_width=0, corner_radius=6)
        exec_frame.grid(row=1, column=1, sticky="ew", padx=5, pady=(8, 0))
        self._compile_dir_lbl = ctk.CTkLabel(exec_frame, text="项目根（默认）",
                                          fg_color="transparent",
                                          anchor="w", width=1)
        self._compile_dir_lbl.pack(fill="x", expand=True, padx=8, pady=4)
        self._exec_pick_btn = ctk.CTkButton(self._cmd_frame, text="选择目录",
                                            width=90,
                                            command=self._pick_compile_dir)
        self._exec_pick_btn.grid(row=1, column=2, padx=(5, 0), pady=(8, 0))
        self._exec_reset_btn = ctk.CTkButton(
            self._cmd_frame, text="↺", width=28,
            command=self._reset_compile_dir, fg_color="transparent",
            hover_color=("gray70", "gray40"), font=ctk.CTkFont(size=16))
        self._exec_reset_btn.grid(row=1, column=3, padx=(2, 0), pady=(8, 0))
        # 重置按钮列固定宽度：隐藏时布局不移动
        self._cmd_frame.grid_columnconfigure(3, minsize=34)
        ToolTip(self._exec_reset_btn, "恢复默认")
        self._controls.extend([self._exec_pick_btn, self._exec_reset_btn])

        # 变更即保存
        self._compile_var.trace_add("write", self._on_setting_changed)

        self._update_exec_state()
        self._update_visibility()

    # ------------------------------------------------------------------
    # 编译下拉联动
    # ------------------------------------------------------------------

    def _compile_id(self) -> str:
        label = self._proc_menu.get()
        for cid, clabel in COMPILER_CHOICES:
            if clabel == label:
                return cid
        return ""

    def _on_compile_changed(self, label: str) -> None:
        if self._loading:
            return
        self._update_visibility()
        # 编译系统变化 → 按新编译重新标注依赖清单（✓/未知/未选择）
        self._refresh_manifest_label()
        if self._pm:
            self._pm.set_field("compile_system", self._compile_id())
        self._check_pyinstaller_bg()  # Python 选中时后台预检
        if self._on_changed:
            self._on_changed()

    def _refresh_manifest_label(self) -> None:
        """按当前编译系统重新标注依赖清单选择（切换编译时刷新错误状态）。"""
        manifest = self._manifest_var.get()
        if manifest:
            comp = get_compiler(self._compile_id())
            name = Path(manifest).name
            if comp.is_known_manifest(name):
                self._manifest_label.configure(
                    text=f"✓ {name}", text_color="green")
            else:
                self._manifest_label.configure(
                    text=f"? {name} 未知清单",
                    text_color=("#C0504D", "#E57373"))
        else:
            self._manifest_label.configure(
                text="未选择", text_color=("gray60", "gray60"))

    def _update_visibility(self) -> None:
        """按编译系统选项整区切换设置区（None / Python+Node / Command）。"""
        cid = self._compile_id()
        self._py_frame.grid_remove()
        self._cmd_frame.grid_remove()
        self._none_frame.grid_remove()
        if cid in ("python", "node"):
            # Node 与 Python 共用依赖清单区；Node 隐藏 SDK 与预检行
            if cid == "node":
                self._include_sdk_cb.grid_remove()
                self._pyinstaller_hint.grid_remove()
            else:
                self._include_sdk_cb.grid()
                self._pyinstaller_hint.grid()
            self._py_frame.grid()
        elif cid == "command":
            self._cmd_frame.grid()
        else:
            self._none_frame.grid()
        comp = get_compiler(cid)
        self._proc_hint.configure(
            text=comp.description if comp else "不执行 compile，直接收集打包内容")

    def _update_exec_state(self) -> None:
        """执行目录行始终可用——Command 区可见即 command 编译模式。"""
        state = "normal" if self._enabled else "disabled"
        self._exec_pick_btn.configure(state=state)
        self._exec_reset_btn.configure(state=state)

    # ------------------------------------------------------------------
    # 字段交互
    # ------------------------------------------------------------------

    def _pick_manifest(self) -> None:
        if not self._plugin_dir:
            return
        f = filedialog.askopenfilename(
            title="选择依赖清单（pyproject.toml / package.json）",
            initialdir=self._plugin_dir,
            filetypes=[("依赖清单", ("pyproject.toml", "package.json")),
                       ("所有文件", "*.*")])
        if not f:
            return
        rel = self._pm.to_relative(f) if self._pm else f
        self._manifest_var.set(rel)
        # 类型标注：可识别 = 绿色 ✓；否则浅红警示（按当前编译系统判断）
        comp = get_compiler(self._compile_id())
        name = Path(f).name
        if comp.is_known_manifest(name):
            self._manifest_label.configure(text=f"✓ {name}", text_color="green")
        else:
            self._manifest_label.configure(
                text=f"? {name} 未知清单", text_color=("#C0504D", "#E57373"))
        self._on_setting_changed()
        self._check_pyinstaller_bg()

    def _pick_compile_dir(self) -> None:
        d = filedialog.askdirectory(title="选择编译命令执行目录")
        if not d:
            return
        self._compile_dir = d
        self._refresh_exec_display()
        self._on_setting_changed()

    def _reset_compile_dir(self) -> None:
        self._compile_dir = ""
        self._refresh_exec_display()
        self._on_setting_changed()

    def _refresh_exec_display(self) -> None:
        if self._compile_dir:
            text = Path(self._compile_dir).as_posix().rstrip("/") + "/"
            color = ("gray10", "gray90")
            self._exec_reset_btn.grid()  # 非默认才显示重置
        else:
            text = "项目根（默认）"
            color = ("gray60", "gray60")
            self._exec_reset_btn.grid_remove()
        self._compile_dir_lbl.configure(text=text, text_color=color)

    # ------------------------------------------------------------------
    # PyInstaller 预检（后台线程，仅标注不阻断）
    # ------------------------------------------------------------------

    def _check_pyinstaller_bg(self) -> None:
        if self._compile_id() != "python":
            return
        threading.Thread(target=self._check_pyinstaller_work,
                         daemon=True).start()

    def _check_pyinstaller_work(self) -> None:
        try:
            result = subprocess.run(
                _get_python_exe() + ["-m", "PyInstaller", "--version"],
                capture_output=True, text=True, timeout=30,
                creationflags=_NO_WINDOW)
            ok = result.returncode == 0
        except Exception:
            ok = False
        text = ("PyInstaller installed" if ok
                else "PyInstaller required")
        color = ("#2E7D32" if ok else "#FF4444")
        try:
            self.after(0, lambda: self._pyinstaller_hint.configure(
                text=text, text_color=color))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _on_setting_changed(self, *args: Any) -> None:
        if self._loading:
            return
        self.save_settings()
        if self._on_changed:
            self._on_changed()

    def set_plugin_dir(self, d: str, pm: ProjectManager | None = None) -> None:
        if pm:
            self._pm = pm
        self._plugin_dir = d
        self._set_enabled(True)
        if self._pm:
            self._loading = True
            try:
                project = self._pm.read_project()
                cid = project.get("compile_system", "")
                label = next((cl for c, cl in COMPILER_CHOICES if c == cid),
                             COMPILER_CHOICES[0][1])
                self._proc_menu.set(label)
                self._manifest_var.set(project.get("manifest", ""))
                self._include_sdk_var.set(
                    bool(project.get("include_sdk", True)))
                self._compile_var.set(project.get("compile", ""))
                rel_exec = project.get("compile_dir", "")
                self._compile_dir = (self._pm.to_absolute(rel_exec)
                                  if rel_exec else "")
                self._refresh_exec_display()
                # 清单标注（按当前编译系统判断，切换/加载共用）
                self._refresh_manifest_label()
            finally:
                self._loading = False
            self._update_visibility()
            self._update_exec_state()
            self._check_pyinstaller_bg()

    def save_settings(self) -> None:
        """保存编译相关字段到 project.json 顶层。"""
        if not self._pm:
            return
        project = self._pm.read_project()
        project["compile_system"] = self._compile_id()
        project["manifest"] = self._manifest_var.get()
        project["include_sdk"] = self._include_sdk_var.get()
        project["compile"] = self._compile_var.get()
        project["compile_dir"] = (self._pm.to_relative(self._compile_dir)
                               if self._compile_dir else "")
        self._pm.write_project(project)

    def get_compile_system(self) -> str:
        return self._compile_id()

    def get_compile_cfg(self) -> dict[str, Any]:
        """供 BuildContext 组装的编译设置字段。"""
        cid = self._compile_id()
        if cid == "python":
            return {"manifest": self._manifest_var.get(),
                    "include_sdk": self._include_sdk_var.get()}
        if cid == "node":
            return {"manifest": self._manifest_var.get()}
        if cid == "command":
            return {"compile": self._compile_var.get(),
                    "compile_dir": self._compile_dir}
        return {}

    def get_manifest(self) -> str:
        """当前选定的依赖清单绝对路径（空 = 未选）。"""
        rel = self._manifest_var.get()
        if not rel or not self._pm:
            return ""
        return self._pm.to_absolute(rel)

    def get_pypi_index(self) -> str:
        return ""
