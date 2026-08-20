"""Main application window — cross-tab layout with top/bottom bars."""

import datetime
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any


def _norm(p: str) -> str:
    """Normalize path separators to forward slashes."""
    return Path(p).as_posix()


def _norm_dir(p: str | Path) -> str:
    """显示用目录路径：正斜杠 + 尾部 "/"。"""
    return _norm(str(p)).rstrip("/") + "/"


import customtkinter as ctk

from gui.build_tab import BuildTab
from gui.debug_tab import DebugTab
from backend.builder import BuildError, Builder
from backend.compilers import get_compiler
from backend.pipeline import BuildContext, fill_builder, run_build, validate
from backend.packaging import cleanup_intermediates
from gui.log_tab import LogTab
from backend.logbus import Logger
from backend.build_control import Canceller
from gui.manifest_tab import ManifestTab
from backend.project_manager import ProjectManager, project_exists
from gui.settings_tab import SettingsTab
from gui.widgets import BG0, BG1, ToolTip
from backend import settings_store


class App(ctk.CTk):
    """DGHub SDK Packer main window."""

    TITLE = "DGHub SDK Packer"
    WINDOW_SIZE = "1400x1100"

    def __init__(self) -> None:
        super().__init__()

        self.title(self.TITLE)
        self.geometry(self.WINDOW_SIZE)
        self.minsize(1400, 1100)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # -- state --
        self._plugin_dir: str | None = None
        self._output_dir: str | None = None
        self._output_auto = True
        self._pm: ProjectManager | None = None
        self._running = False
        self._build_success = False
        self._canceller: Canceller | None = None  # 当前构建的取消令牌
        # 错误高亮登记表：tab 名 → 当前高亮的控件集合（用于级联清除）
        self._error_fields: dict[str, set] = {"信息": set(), "构建": set()}

        # -- 线程安全 UI 调度（后台线程更新 UI 必须经此）--
        import gui.ui_dispatch as ui_dispatch

        ui_dispatch.init(self)

        # -- top bar (cross-tab) --
        self._build_top_bar()

        # -- tab view（tab 导航固定；内容区占满顶部栏与日志面板之间，
        #    页面内容 fill 视口，超高时由页面内部滚动自管）--
        self._tab_view = ctk.CTkTabview(self, anchor="nw", fg_color=BG0)
        self._tab_view.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)

        # -- tabs --
        self._info_tab = self._tab_view.add("信息")
        self._dist_tab = self._tab_view.add("构建")
        self._debug_tab = self._tab_view.add("调试")
        self._settings_tab = self._tab_view.add("设置")

        # -- populate tabs --
        self._info_view = ManifestTab(
            self._info_tab, on_field_edit=self._on_info_field_edit
        )
        self._info_view.pack(fill="both", expand=True)

        self._dist_view = BuildTab(
            self._dist_tab,
            on_compile_changed=self._on_compile_changed,
            on_error_cleared=self._on_dist_errors_cleared,
            on_build_clicked=self._start_build,
        )
        self._dist_view.pack(fill="both", expand=True)

        # -- bottom: 全局日志面板（构建/调试双输出，可折叠）--
        self._log_view = LogTab(self)
        self._log_view.grid(row=3, column=0, sticky="sew", padx=10, pady=(0, 4))
        self._logger = Logger(self._log_view.emit_build)
        self._debug_logger = Logger(self._log_view.emit_debug)

        self._debug_view = DebugTab(
            self._debug_tab,
            logger=self._debug_logger,
            on_state_change=self._on_debug_state_changed,
        )
        self._debug_view.pack(fill="both", expand=True)

        self._settings_view = SettingsTab(
            self._settings_tab,
            on_pypi_index_changed=lambda url: self._save_state_key("pypi_index", url),
            on_suffix_changed=lambda: self._dist_view.refresh_preview(),
        )
        self._settings_view.pack(fill="both", expand=True)

        # -- 构建按钮移入构建页（右栏底部）——app 侧只持有引用管理状态 --
        self._build_btn = self._dist_view.get_build_button()
        self._build_status = self._dist_view.get_build_status()

        # -- restore global settings --
        self._settings_view.set_pypi_index(self._read_state().get("pypi_index", ""))

        # -- auto-load last plugin dir --
        self._auto_open_last_plugin_dir()

        # 启动即检查更新（后台线程，不阻塞 UI）
        self._auto_check_update()

        # 退出时终止正在运行的构建（避免残留子进程）
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # top bar
    # ------------------------------------------------------------------

    def _build_top_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=BG0)
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        # 插件目录 + 输出目录放入同一浮动卡片（第一层 BG1）
        card = ctk.CTkFrame(bar, fg_color=BG1, corner_radius=8)
        card.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        card.grid_columnconfigure(1, weight=1)
        bar.grid_columnconfigure(0, weight=1)

        BTN_W = 100

        # Store buttons for state management
        self._out_btns: list[ctk.CTkButton] = []

        def _make_dir_row(card, row, label, text, select_cmd, reset_cmd=None):
            """Helper to build a uniform directory selector row.
            Returns (frame, lbl, [buttons...]).
            """
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(weight="bold")).grid(
                row=row, column=0, padx=(10, 5), pady=6, sticky="w"
            )
            frame = ctk.CTkFrame(card, fg_color="transparent", border_width=0, corner_radius=6)
            frame.grid(row=row, column=1, sticky="ew", padx=5, pady=6)
            frame.grid_columnconfigure(0, weight=1)
            lbl = ctk.CTkLabel(frame, text=text, fg_color="transparent", anchor="w")
            lbl.pack(fill="x", expand=True, padx=8, pady=4)

            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=row, column=2, padx=5, pady=6, sticky="w")
            btn = ctk.CTkButton(
                btn_frame, text="选择目录", width=BTN_W, command=select_cmd
            )
            btn.pack(side="left")
            btns = [btn]
            # Fixed-width slot reserves reset button space so the
            # select button column never shifts when reset toggles
            slot = ctk.CTkFrame(btn_frame, fg_color="transparent", width=33, height=28)
            slot.pack(side="left")
            slot.pack_propagate(False)
            if reset_cmd:
                reset_btn = ctk.CTkButton(
                    slot,
                    text="↺",
                    width=28,
                    command=reset_cmd,
                    fg_color="transparent",
                    hover_color=("gray70", "gray40"),
                    font=ctk.CTkFont(size=16),
                )
                # Hidden by default; shown only when dir is manually set
                ToolTip(reset_btn, "恢复默认")
                btns.append(reset_btn)
            return frame, lbl, btns

        # Row 0: 插件目录（始终可用）
        self._dir_path_frame, self._dir_label, self._dir_btns = _make_dir_row(
            card, 0, "插件目录:", "未选择", self._select_shared_dir
        )

        # Row 1: 输出目录（初始禁用；源码/收集目录已移入构建 tab 各系统视图）
        self._out_path_frame, self._out_label, self._out_btns = _make_dir_row(
            card,
            1,
            "输出目录:",
            "",
            self._select_output_dir,
            reset_cmd=self._reset_output_dir,
        )
        self._out_reset_btn = self._out_btns[1]

        # Initially disable output row
        for b in self._out_btns:
            b.configure(state="disabled")

    @staticmethod
    def _set_reset_visible(btn: Any, visible: bool) -> None:
        """Show/hide a reset button (visible only when dir is manually set)."""
        if visible:
            btn.pack(side="left", padx=(5, 0))
        else:
            btn.pack_forget()

    def _on_compile_changed(self) -> None:
        """编译设置变更（构建页内嵌编译设置回调）→ 自动重新填充。

        编译系统/产物模式/清单变化后旧 deduce 条目失效——直接执行
        fill_builder（清旧 derived + 按 deduce 补新，幂等只填空），
        无需手动「从编译填充」。
        """
        self._debug_view._update_hint()
        view = getattr(self, "_dist_view", None)
        if view is None:
            return
        view.refresh_preview(self._output_dir)
        if not self._pm or not self._plugin_dir:
            return
        try:
            ctx = self._make_build_context()
            applied = fill_builder(ctx) or []
            for line in applied:
                self._logger.info(f"已应用: {line}")
            if applied:
                # 条目已变化：重载列表（derived 优先显示）并刷新预览
                view.set_plugin_dir(self._plugin_dir, self._pm)
                view.refresh_preview(self._output_dir)
        except Exception as exc:  # 填充失败不阻断编辑（构建时再报）
            self._logger.error(f"自动填充失败: {exc}")

    def _on_tab_changed(self, _tab: str = "") -> None:
        """tab 切换（保留：页面内部滚动结构无需额外处理）。"""
        return

    # ------------------------------------------------------------------
    # directory selection
    # ------------------------------------------------------------------

    def _select_output_dir(self) -> None:
        d = filedialog.askdirectory(title="选择输出目录")
        if not d:
            return
        self._output_dir = d
        self._out_label.configure(text=_norm_dir(d), text_color=("gray10", "gray90"))
        self._output_auto = False
        self._out_path_frame.configure(border_width=0)
        self._set_reset_visible(self._out_reset_btn, True)
        self._dist_view.refresh_preview(_norm_dir(d))
        self._save_output_dir(_norm(d))
        self._clear_field_error("构建", self._out_path_frame)

    def _reset_output_dir(self) -> None:
        """Reset output dir to default (plugin_dir/output)."""
        if self._plugin_dir:
            default_out = _norm_dir(Path(self._plugin_dir) / "output")
            self._output_dir = default_out
            self._out_label.configure(text=default_out, text_color=("gray60", "gray60"))
            self._output_auto = True
            self._out_path_frame.configure(border_width=0)
            self._set_reset_visible(self._out_reset_btn, False)
            self._dist_view.refresh_preview(default_out)
            self._save_output_dir("")
            self._clear_field_error("构建", self._out_path_frame)

    def _save_output_dir(self, out_dir: str) -> None:
        """Persist output dir setting to builder 节（存相对插件目录）。"""
        if self._pm:
            project = self._pm.read_project()
            builder = dict(project.get("builder", {}))
            builder["output_dir"] = self._pm.to_relative(out_dir)
            project["builder"] = builder
            self._pm.write_project(project)

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------

    def _clear_error_styles(self) -> None:
        """Reset all error states."""
        self._dir_path_frame.configure(border_width=0, border_color="")
        self._dir_label.configure(text_color=("gray10", "gray90"))
        self._out_path_frame.configure(border_width=0, border_color="")
        # 输出目录：自动默认时保持灰字，手动设置时用正常深色
        self._out_label.configure(
            text_color=(
                ("gray60", "gray60") if self._output_auto else ("gray10", "gray90")
            )
        )
        # 视图内目录行红框复位
        self._dist_view.clear_errors()

        # 信息页必填字段红框复位（恢复默认灰边）
        self._info_view.reset_field_borders()
        # Reset tab colors
        self._tab_view._segmented_button._buttons_dict["信息"].configure(
            text_color=("gray10", "gray90")
        )
        self._tab_view._segmented_button._buttons_dict["构建"].configure(
            text_color=("gray10", "gray90")
        )
        # 清空错误登记表
        self._error_fields = {"信息": set(), "构建": set()}

    def _tab_color(self, name: str, color: str | tuple[str, str]) -> None:
        """Set a tab's title color."""
        try:
            btn = self._tab_view._segmented_button._buttons_dict.get(name)
            if btn:
                btn.configure(text_color=color)
        except Exception:
            pass

    def _highlight_tab(self, tab_name: str) -> None:
        self._tab_color(tab_name, "#FF4444")

    def _clear_tab_highlight(self, tab_name: str) -> None:
        self._tab_color(tab_name, ("gray10", "gray90"))

    def _highlight_field(self, widget: Any, tab: str) -> None:
        """Apply red border to a CTkEntry and register it under its tab."""
        try:
            widget.configure(border_width=2, border_color="#FF4444")
        except Exception:
            pass
        self._error_fields.setdefault(tab, set()).add(widget)

    def _clear_field_error(self, tab: str, widget: Any = None) -> None:
        """字段修正后的级联清除：移出登记表 → tab 无错则清标题 → 复位状态。

        控件自身的红框由各来源（信息页 keyrelease / 构建页 entry / 输出目录
        选择）就地清除，此处只负责跨控件的 tab 标题高亮与「构建失败」标签。
        """
        fields = self._error_fields.get(tab)
        if fields is not None and widget is not None:
            fields.discard(widget)
        if not self._error_fields.get(tab):
            self._clear_tab_highlight(tab)
        self._reset_build_status_if_failed()

    def _reset_build_status_if_failed(self) -> None:
        """用户开始修正错误时，移除过时的「构建失败/成功」状态标签。"""
        if self._running:
            return
        self._build_status.configure(text="", text_color=("gray10", "gray90"))

    def _on_info_field_edit(self, key: str) -> None:
        """信息页字段被编辑（来自 ManifestTab 回调）→ 级联清除高亮。"""
        self._clear_field_error("信息", self._info_view._fields.get(key))

    def _on_dist_errors_cleared(self) -> None:
        """构建页错误高亮被清除（内容修改）→ 级联清除 tab 标题高亮。"""
        self._clear_tab_highlight("构建")

    def _validate_info_tab(self) -> bool:
        """Validate 信息 tab fields，一次性检测所有必填项。Returns True if valid."""
        manifest = self._info_view._build_manifest()
        ok = True
        for key, label in (("id", "id"), ("name", "name"), ("version", "version")):
            if not manifest.get(key, ""):
                self._logger.error(f"信息 → {label} 不能为空")
                self._highlight_tab("信息")
                w = self._info_view._fields.get(key)
                if w:
                    self._highlight_field(w, "信息")
                ok = False
        return ok

    def _validate_dist_tab(self) -> bool:
        """Validate 构建页（含编译设置状态），一次性检测。Returns True if valid."""
        self._dist_view.get_compile_view().save_settings()
        self._dist_view.save_settings()
        ctx = self._make_build_context()
        ok = True
        # 先清除过时的条目错误高亮，再收集新错误
        self._dist_view.clear_errors()
        errors = validate(ctx)
        try:
            # 收集打包内容条目的缺失错误（不落盘）；无实际编译输入时
            # 入口缺失不豁免 → 进入条目级高亮
            ctx.builder.resolve(
                ctx.source_dir,
                entry_exempt=bool(
                    ctx.compile_cfg.get("command") or ctx.compile_cfg.get("manifest")
                ),
            )
        except BuildError as exc:
            errors += exc.errors
        if errors:
            # 条目级错误 → 对应行红框红字
            rels = {msg.split("不存在: ", 1)[1] for msg in errors if "不存在: " in msg}
            # 「入口必须是单个文件」→ 定位到该入口条目行
            if any("入口必须是单个文件" in m for m in errors):
                it = ctx.builder.entry_item()
                if it is not None and it.value is not None:
                    rels.add(it.value)
            # 「入口条目重复」→ 高亮所有 entry 条目行
            if any("入口条目重复" in m for m in errors):
                for it in ctx.builder.items():
                    if "entry" in it.tags and it.value is not None:
                        rels.add(it.value)
            if rels:
                self._dist_view.mark_errors(rels)
            # 区域级错误（如打包内容为空 / 缺少入口）→ 容器红框 + 提示
            area_msg = next(
                (m for m in errors if "入口" in m and "不存在: " not in m), ""
            )
            if area_msg:
                self._dist_view.mark_errors(rels, area_msg)
            for msg in errors:
                self._logger.error(f"构建 → {msg}")
            self._highlight_tab("构建")
            ok = False
        if not self._output_dir:
            self._logger.error("输出目录未选择")
            self._out_path_frame.configure(border_width=2, border_color="red")
            self._out_label.configure(text_color="red")
            self._highlight_tab("构建")
            self._error_fields["构建"].add(self._out_path_frame)
            ok = False
        return ok

    def _make_build_context(self) -> BuildContext:
        """组装校验/构建共用的上下文（构建页内嵌编译设置状态）。"""
        plugin_dir = Path(self._plugin_dir or ".")
        compile_view = self._dist_view.get_compile_view()
        return BuildContext(
            plugin_dir=plugin_dir,
            source_dir=Path(self._plugin_dir or "."),
            output_dir=(
                Path(self._output_dir) if self._output_dir else plugin_dir / "output"
            ),
            plugin_name=plugin_dir.name,
            compile_system=compile_view.get_compile_system(),
            builder=self._dist_view.get_builder()
            or Builder(ProjectManager(str(plugin_dir))),
            log=self._logger,
            pm=self._pm,
            pypi_index=self._settings_view.get_pypi_index(),
            canceller=self._canceller,
            compile_cfg=compile_view.get_compile_cfg(),
        )

    # ------------------------------------------------------------------
    # build pipeline
    # ------------------------------------------------------------------

    def _lock_controls(self, locked: bool) -> None:
        """构建期间锁定目录按钮与编辑 tab；结束后恢复。"""
        state = "disabled" if locked else "normal"
        for b in getattr(self, "_dir_btns", []) + self._out_btns:
            try:
                b.configure(state=state)
            except Exception:
                pass
        self._info_view._set_enabled(not locked)
        self._dist_view._set_enabled(not locked)  # 含内嵌编译设置
        # 构建按钮独立于控件锁：构建中保持可点（取消构建）
        try:
            self._build_btn.configure(state="normal")
        except Exception:
            pass
        # 调试运行期间构建按钮同样禁用（互斥），见 _on_debug_state_changed
        self._debug_view._set_enabled(not locked)

    def _start_build(self) -> None:
        if self._running:
            return
        if self._debug_view.is_running():
            self._build_status.configure(
                text="调试运行中，请先停止调试", text_color="red"
            )
            self._logger.error("调试运行中，请先停止调试")
            return
        if not self._plugin_dir:
            self._build_status.configure(text="请先选择插件目录", text_color="red")
            self._logger.error("请先选择插件目录")
            self._dir_path_frame.configure(border_width=2, border_color="red")
            self._dir_label.configure(text="请选择插件目录", text_color="red")
            return

        self._clear_error_styles()
        self._logger.separator(f"构建 {datetime.datetime.now().strftime('%H:%M:%S')}")
        self._build_success = False
        self._build_status.configure(text="构建中...", text_color=("gray40", "gray60"))
        self._running = True
        self._canceller = Canceller()
        # 按钮转为「取消构建」（构建中其它控件锁定，唯此键可点）
        self._build_btn.configure(text="取消构建", command=self._cancel_build)
        # 锁定构建系统选择与所有编辑控件，避免构建期间状态被改动
        self._lock_controls(True)

        # 校验 + 配置收集在主线程执行（Tcl 变量只能主线程读写）；
        # 通过后开后台线程跑构建管线
        self.after(10, self._begin_build)

    def _begin_build(self) -> None:
        """主线程：校验 → 收集配置 → 启动构建线程。"""
        import gui.ui_dispatch as ui_dispatch

        self._logger.info("开始校验")
        info_ok = self._validate_info_tab()
        dist_ok = self._validate_dist_tab()
        if not (info_ok and dist_ok):
            self._tab_view.set("信息" if not info_ok else "构建")
            ui_dispatch.ui(self._finish_build_ui)
            return
        self._logger.info("校验通过")
        # 主线程收集配置（StringVar / OptionMenu 等 Tcl 状态）
        self._dist_view.get_compile_view().save_settings()
        self._dist_view.save_settings()
        self._logger.detail("配置已保存")
        ctx = self._make_build_context()
        manifest_data = self._info_view._build_manifest()
        threading.Thread(
            target=self._run_build, args=(ctx, manifest_data), daemon=True
        ).start()

    def _on_debug_state_changed(self) -> None:
        """调试运行状态变化：运行中禁用构建按钮（互斥，同一时间只跑一个子进程）。"""
        state = "disabled" if self._debug_view.is_running() else "normal"
        try:
            self._build_btn.configure(state=state)
        except Exception:
            pass

    def _cancel_build(self) -> None:
        """取消构建：对话框二次确认后硬终止子进程树。"""
        if not self._running:
            return
        if not messagebox.askyesno(
            "取消构建",
            "确定取消当前构建？\n正在运行的命令（compile / 依赖安装 / "
            "打包）将被立即终止。",
        ):
            return
        if not self._running or self._canceller is None:
            return  # 对话框期间构建可能已结束
        self._canceller.cancel()
        self._logger.warning("正在取消构建...")
        self._build_status.configure(
            text="正在取消...", text_color=("gray50", "gray60")
        )

    def _on_close(self) -> None:
        """窗口关闭：若构建进行中，先终止子进程再退出（不弹框）。"""
        if self._running and self._canceller is not None:
            self._canceller.cancel()
        self.destroy()

    # ------------------------------------------------------------------
    # in-app update
    # ------------------------------------------------------------------

    def _auto_check_update(self) -> None:
        """启动即检查更新（每次启动都查，弹窗条件按版本判断）。

        dev / 无版本构建（本地源码运行）跳过检查。
        """
        from backend.updater import get_current_version, check_latest, should_notify

        version = get_current_version()
        if version in ("dev", "No Version"):
            return

        def _check() -> None:
            import gui.ui_dispatch as ui_dispatch

            latest, url, size = check_latest()
            if latest and url and should_notify(latest, version):
                ui_dispatch.ui(lambda: self._on_new_version_found(latest, url, size))

        threading.Thread(target=_check, daemon=True).start()

    def _on_new_version_found(self, latest: str, url: str, size: int) -> None:
        """自动检测到新版本：弹自定义对话框询问，是则切到设置页。

        对话框提供「下载 / 安装」与「取消」按钮及「不要此版本」复选框
        （勾选后点取消 → 跳过该版本）。
        """
        if self._ask_new_version(latest, url, size):
            self._tab_view.set("设置")
            self._settings_view.show_update(latest, url, size)
            # 未下载过 → 弹窗点「下载」后自动开始下载
            from backend.updater import update_dest

            if not update_dest(latest).is_file():
                self._settings_view.start_download()

    def _ask_new_version(self, latest: str, url: str, size: int) -> bool:
        """自定义更新询问对话框。返回 True = 用户选择下载/安装。"""
        from backend.updater import skip_version, update_dest

        dest = update_dest(latest)
        has_installer = dest.is_file()

        dialog = ctk.CTkToplevel(self)
        dialog.title("发现新版本")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        text = (
            f"发现 DGHub SDK Packer {latest}，安装包已下载，是否安装？"
            if has_installer
            else f"发现 DGHub SDK Packer {latest}，是否下载？"
        )
        ctk.CTkLabel(
            dialog, text=text, font=ctk.CTkFont(size=14), wraplength=380, justify="left"
        ).pack(padx=24, pady=(24, 10))

        result = {"ok": False}

        def _on_ok() -> None:
            result["ok"] = True
            dialog.destroy()

        def _on_ignore() -> None:
            """忽略此版本：记录跳过并关闭对话框。"""
            skip_version(latest)
            dialog.destroy()

        def _on_cancel() -> None:
            dialog.destroy()

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack()
        # 右对齐：side=right 从右向左排，pack 顺序与显示顺序相反；padx=5 统一间距
        ctk.CTkButton(btns, text="取消", width=100, command=_on_cancel).pack(
            side="right", padx=5
        )
        ctk.CTkButton(
            btns, text="安装" if has_installer else "下载", width=100, command=_on_ok
        ).pack(side="right", padx=5)
        ctk.CTkButton(btns, text="忽略此版本", width=100, command=_on_ignore).pack(
            side="right", padx=5
        )

        # 居中于主窗口
        dialog.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dialog.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.wait_window()
        return result["ok"]

    def _run_build(self, ctx: BuildContext, manifest_data: dict[str, Any]) -> None:
        """构建管线（后台线程；UI 更新经 ui_dispatch 回主线程）。

        校验与配置收集已由主线程完成（_begin_build）——本线程只跑
        后端 run_build（日志经线程安全 LogTab，UI 状态经调度）。
        """
        import gui.ui_dispatch as ui_dispatch

        self._build_success = True
        try:
            ctx.output_dir.mkdir(parents=True, exist_ok=True)
            try:
                artifact = run_build(ctx, manifest_data)
            except BuildError as be:
                for msg in be.errors:
                    self._logger.error(msg)
                ui_dispatch.ui(lambda: self._highlight_tab("构建"))
                self._build_success = False
                return
            if artifact is None:
                self._build_success = False
                return
        except Exception as exc:
            self._logger.error(f"构建失败: {exc}")
            self._build_success = False
        finally:
            if self._canceller is not None and self._canceller.cancelled:
                # 取消后清理已产生的中间产物（仅 output_dir，不动用户源目录）
                cleanup_intermediates(ctx.output_dir, ctx.plugin_name)
                self._logger.warning("构建已取消")
            ui_dispatch.ui(self._finish_build_ui)

    def _finish_build_ui(self) -> None:
        """主线程：构建结束恢复按钮/状态/解锁（校验失败路径同样调用）。"""
        self._running = False
        self._build_btn.configure(
            text="开始构建", state="normal", command=self._start_build
        )
        self._lock_controls(False)
        cancelled = self._canceller is not None and self._canceller.cancelled
        if cancelled:
            self._build_status.configure(
                text="⏹ 已取消", text_color=("gray50", "gray60")
            )
        elif self._build_success:
            self._build_status.configure(text="✅ 构建成功", text_color="green")
        else:
            self._build_status.configure(text="❌ 构建失败", text_color="red")
        self._canceller = None

    def _read_state(self) -> dict:
        """读取全局状态（委托 backend.settings_store）。"""
        return settings_store.read_state()

    def _save_state_key(self, key: str, value: Any) -> None:
        """更新全局状态的单个键（委托 backend.settings_store）。"""
        settings_store.save_state_key(key, value)

    def _save_last_plugin_dir(self, d: str) -> None:
        self._save_state_key("last_plugin_dir", d)

    def _auto_open_last_plugin_dir(self) -> None:
        try:
            last = self._read_state().get("last_plugin_dir", "")
            if last and Path(last).is_dir():
                self._select_shared_dir(last)
        except Exception:
            pass

    def _select_shared_dir(self, d: str = "") -> None:
        if not d:
            d = filedialog.askdirectory(title="选择插件根目录")
            if not d:
                return
        self._plugin_dir = d
        self._dir_label.configure(text=_norm_dir(d), text_color=("gray10", "gray90"))
        self._dir_path_frame.configure(border_width=0)

        # Initialize project manager
        self._pm = ProjectManager(d, log=self._logger)
        project = self._pm.read_project()

        # Push to all tabs
        self._info_view.set_plugin_dir(d, self._pm)
        self._dist_view.set_plugin_dir(d, self._pm)  # 含内嵌编译设置
        self._debug_view.set_plugin_dir(d, self._pm)

        # Source dir（顶层 source_dir；未设置回退插件目录）

        # Enable output dir row
        for b in self._out_btns:
            b.configure(state="normal")

        # Output dir（builder 节，存储为相对插件目录，解析为绝对后使用）
        saved_out = project.get("builder", {}).get("output_dir", "")
        if saved_out:
            self._output_dir = self._pm.to_absolute(saved_out)
            self._out_label.configure(
                text=_norm_dir(self._output_dir), text_color=("gray10", "gray90")
            )
            self._output_auto = False
        else:
            default_out = _norm_dir(Path(d) / "output")
            self._out_label.configure(text=default_out, text_color=("gray60", "gray60"))
            self._output_dir = default_out
            self._output_auto = True
        self._set_reset_visible(self._out_reset_btn, not self._output_auto)
        self._dist_view.refresh_preview(self._output_dir)

        self._logger.info(f"已加载项目: {d}")
        self._save_last_plugin_dir(d)
        # 加载后同步编译产物条目（幂等只填空：正常项目无变化；
        # 新项目/旧版升级缺 deduce 条目时自动补全，替代原「从编译填充」）
        self._on_compile_changed()
