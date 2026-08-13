"""Debug tab — 调试源码 / 调试运行（全中文 UI）。

- 调试源码：编译系统 API 判定支持（debug_source_command），注入
  DGHUB_MANIFEST_DIR=插件根/.dghub-sdk 后运行源码（uv run）
- 调试运行：Packer 构建（始终 folder + 固定输出 plugin_dir/debug/），
  在产物文件夹内运行插件入口
- 环境变量区：主机 / 端口 / 令牌，支持本机 DGHub 探测自动填充与手动填写
- 插件 stdout/stderr 统一进日志 tab（logbus external）；本页仅状态行
"""

import os
import threading
from pathlib import Path
from typing import Any

import customtkinter as ctk

from backend import settings_store
from backend.build_control import Canceller
from backend.compilers import get_compiler
from backend.debug_runner import (build_for_debug, detect_dghub,
                                  fetch_token, locate_debug_entry,
                                  run_process)
from backend.builder import Builder
from backend.logbus import Logger
from backend.pipeline import BuildContext
from backend.project_manager import ProjectManager

# 右栏各行统一的前导标签宽度（像素）
_LABEL_W = 92

# 调试模式选项：显示名 → 键
_MODE_CHOICES = (("调试源码", "source"), ("调试运行", "run"))


class DebugTab(ctk.CTkFrame):
    """调试页：模式选择 + 环境变量 + 启动/停止 + 状态行。"""

    def __init__(self, master: Any, logger: Logger,
                 on_state_change: Any | None = None,
                 **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._pm: ProjectManager | None = None
        self._plugin_dir: str | None = None
        self._logger = logger
        self._on_state_change = on_state_change  # 运行状态变化回调（锁定互斥）
        self._controls: list[ctk.CTkBaseClass] = []
        self._enabled = False
        self._running = False
        self._canceller: Canceller | None = None

        # 状态变量
        self._mode_var = ctk.StringVar(value="调试源码")
        self._token_var = ctk.StringVar(
            value=os.environ.get("DGHUB_TOKEN", ""))

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
        self._update_hint()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(1, weight=1)

        # ---- 调试模式（下拉单选） ----
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=10, pady=(10, 0))
        ctk.CTkLabel(row, text="调试模式", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        self._mode_menu = ctk.CTkOptionMenu(
            row, width=160,
            values=[label for label, _ in _MODE_CHOICES],
            command=self._on_mode_changed)
        self._mode_menu.grid(row=0, column=1, sticky="w", padx=5)
        self._controls.append(self._mode_menu)
        self._mode_hint = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"), anchor="w", wraplength=560,
            justify="left")
        self._mode_hint.grid(row=0, column=2, sticky="w", padx=(10, 0))

        # ---- 环境变量区 ----
        env_frame = ctk.CTkFrame(self, fg_color="transparent")
        env_frame.grid(row=1, column=0, columnspan=2, sticky="ew",
                       padx=10, pady=(12, 0))
        env_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(env_frame, text="环境变量", width=_LABEL_W,
                     anchor="w", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")

        ctk.CTkLabel(env_frame, text="令牌（DGHUB_TOKEN）", width=_LABEL_W,
                     anchor="w").grid(
            row=1, column=0, padx=(0, 5), sticky="w", pady=3)
        token_row = ctk.CTkFrame(env_frame, fg_color="transparent")
        token_row.grid(row=1, column=1, sticky="w", padx=5, pady=3)
        entry = ctk.CTkEntry(token_row, textvariable=self._token_var,
                             width=240)
        entry._is_focused = False  # placeholder/焦点状态统一
        entry.pack(side="left")
        self._controls.append(entry)

        detect_row = ctk.CTkFrame(token_row, fg_color="transparent")
        detect_row.pack(side="left", padx=(5, 0))
        self._detect_btn = ctk.CTkButton(
            detect_row, text="检测 DGHub", width=100,
            command=self._detect_clicked)
        self._detect_btn.pack(side="left")
        self._controls.append(self._detect_btn)
        self._detect_hint = ctk.CTkLabel(
            detect_row, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"), anchor="w")
        self._detect_hint.pack(side="left", padx=(10, 0))

        ctk.CTkLabel(
            env_frame,
            text="主机与端口在「设置」页填写；点击右侧按钮检测 DGHub"
                 "并自动拉取令牌。",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            wraplength=560, justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w",
               padx=(0, 5), pady=(0, 6))

        # ---- 启动/停止 + 状态行 ----
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew",
                    padx=10, pady=(14, 0))
        self._start_btn = ctk.CTkButton(
            bottom, text="启动调试", width=110,
            command=self._start_clicked)
        self._start_btn.pack(side="left")
        self._controls.append(self._start_btn)
        self._stop_btn = ctk.CTkButton(
            bottom, text="停止", width=90,
            command=self._stop_clicked)
        self._stop_btn.pack(side="left", padx=(8, 0))
        self._controls.append(self._stop_btn)
        self._status_lbl = ctk.CTkLabel(
            bottom, text="空闲", font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"), anchor="w")
        self._status_lbl.pack(side="left", padx=(16, 0))

    # ------------------------------------------------------------------
    # 状态与提示
    # ------------------------------------------------------------------

    def _on_mode_changed(self, _label: str) -> None:
        self._mode_var.set(_label)
        self._update_hint()

    def _update_hint(self) -> None:
        """按模式与编译系统刷新说明/不匹配提示（入口问题在调试时才检测）。"""
        if self._mode_var.get() == "调试运行":
            self._mode_hint.configure(
                text="构建后运行，位于 插件目录/debug/ 下",
                text_color=("gray40", "gray60"))
            return
        comp = self._current_compiler()
        if comp is None:
            self._mode_hint.configure(
                text="请先在编译页选择编译系统", text_color=("gray40", "gray60"))
            return
        # 清单格式与编译系统匹配性检查（优先级最高）
        manifest = ""
        if self._pm:
            manifest = self._pm.read_project().get("compiler", {}).get("manifest", "") or ""
        if manifest and not comp.is_known_manifest(Path(manifest).name):
            need = "package.json" if comp.id == "node" else "pyproject.toml"
            self._mode_hint.configure(
                text=f"清单格式与编译系统不匹配，{comp.label} 需要 {need}",
                text_color=("#C0504D", "#E57373"))
            return
        # 入口问题检查（调试前检测，优先级低于不匹配）
        if comp.debug_source_command(Path(self._plugin_dir or ".")) is None:
            if comp.id == "python":
                text = "pyproject.toml 缺少 [tool.dghub].entry，无法调试源码"
            elif comp.id == "node":
                text = "插件目录缺少 package.json，无法调试源码"
            else:
                text = f"编译系统 '{comp.label}' 不支持「调试源码」"
            self._mode_hint.configure(
                text=text, text_color=("#C0504D", "#E57373"))
            return
        # 正常提示：按编译区分入口来源
        entry_src = ("package.json main 入口" if comp.id == "node"
                     else "[tool.dghub].entry 源码")
        self._mode_hint.configure(
            text=f"运行 {entry_src}，注入 .dghub-sdk manifest",
            text_color=("gray40", "gray60"))

    def _current_compiler(self):
        if not self._pm:
            return None
        bs_id = self._pm.read_project().get("compiler", {}).get("compile_system", "")
        return get_compiler(bs_id)

    def _set_status(self, text: str,
                    color: tuple[str, str] = ("gray40", "gray60")) -> None:
        self._status_lbl.configure(text=text, text_color=color)

    def _notify_state(self) -> None:
        if self._on_state_change:
            self._on_state_change()

    # ------------------------------------------------------------------
    # env / 探测
    # ------------------------------------------------------------------

    @staticmethod
    def _read_host_port() -> tuple[str, int]:
        """从全局设置读取主机与端口。"""
        saved = settings_store.get_state("debug_env", {})
        host = saved.get("host", "") if isinstance(saved, dict) else ""
        port = saved.get("port", "") if isinstance(saved, dict) else ""
        return (host or "localhost", int(port or "8000"))

    def _detect_clicked(self) -> None:
        self._detecting = True
        self._detect_hint.configure(text="检测中...",
                                    text_color=("#B8860B", "#E6B84B"))
        threading.Thread(target=self._detect_work, daemon=True).start()

    def _detect_work(self) -> None:
        host, port = self._read_host_port()
        ok = detect_dghub(host, port)
        if ok:
            token = fetch_token(host, port)
            self.after(0, self._on_detect_success, token)
        else:
            self.after(0, self._on_detect_fail)

    def _on_detect_success(self, token: str | None = None) -> None:
        settings_store.save_state_key("debug_env", {
            "host": "localhost", "port": "8000",
        })
        if token:
            self._token_var.set(token)
        self._detect_hint.configure(text="已检测到 DGHub", text_color="green")
        self._detecting = False

    def _on_detect_fail(self) -> None:
        self._detect_hint.configure(
            text="未检测到（可手动填写）",
            text_color=("#C0504D", "#E57373"))
        self._detecting = False

    # ------------------------------------------------------------------
    # 启动 / 停止
    # ------------------------------------------------------------------

    def _start_clicked(self) -> None:
        if self._running or not self._pm or not self._plugin_dir:
            return
        self._running = True
        self._set_status("启动中...", ("#2E7D32", "#4CAF50"))
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._notify_state()
        threading.Thread(target=self._run, daemon=True).start()

    def _stop_clicked(self) -> None:
        if self._canceller is not None:
            self._canceller.cancel()

    def _build_env(self) -> dict:
        host, port = self._read_host_port()
        env = {**os.environ,
               "DGHUB_HOST": host,
               "DGHUB_PORT": str(port),
               "DGHUB_TOKEN": self._token_var.get().strip()}
        return env

    def _make_debug_ctx(self, canceller: Canceller) -> BuildContext:
        """组装调试构建上下文：输出目录固定 插件目录/debug/。"""
        plugin_dir = Path(self._plugin_dir or ".")
        project = self._pm.read_project() if self._pm else {}
        compile_system = project.get("compiler", {}).get("compile_system", "")
        if compile_system == "python":
            compile_cfg = {"manifest": project.get("compiler", {}).get("manifest", "")}
        elif compile_system == "node":
            compile_cfg = {"manifest": project.get("compiler", {}).get("manifest", "")}
        elif compile_system == "command":
            compile_cfg = {"command": project.get("compiler", {}).get("command", ""),
                           "compile_dir": project.get("compiler", {}).get("compile_dir", "")}
        else:
            compile_cfg = {}
        return BuildContext(
            plugin_dir=plugin_dir,
            source_dir=plugin_dir,
            output_dir=plugin_dir / "debug",
            plugin_name=plugin_dir.name,
            compile_system=compile_system,
            builder=Builder(self._pm),
            log=self._logger,
            pm=self._pm,
            pypi_index=settings_store.get_state("pypi_index", ""),
            canceller=canceller,
            compile_cfg=compile_cfg,
            keep_cache=True,  # 调试构建保留 .deps / cache（PyInstaller 增量）
        )

    def _run(self) -> None:
        plugin_dir = Path(self._plugin_dir or ".")
        canceller = Canceller()
        self._canceller = canceller
        env = self._build_env()
        rc = -1
        try:
            if self._mode_var.get() == "调试源码":
                comp = self._current_compiler()
                if comp is None:
                    self._logger.error("请先在编译页选择编译系统")
                    return
                cmd = comp.debug_source_command(plugin_dir)
                if cmd is None:
                    if comp.id == "python":
                        self._logger.error(
                            "pyproject.toml 缺少 [tool.dghub].entry，"
                            "无法调试源码")
                    elif comp.id == "node":
                        self._logger.error(
                            "插件目录缺少 package.json，无法调试源码")
                    else:
                        self._logger.error(
                            f"编译系统 '{comp.label}' 不支持「调试源码」")
                    return
                # SDK 预留通道：源码调试的 manifest 来自 .dghub-sdk
                env["DGHUB_MANIFEST_DIR"] = str(plugin_dir / ".dghub-sdk")
                self._logger.info(
                    f"调试源码（{comp.label}）: {' '.join(cmd)}")
                self.after(0, lambda: self._set_status(
                    "运行中", ("#2E7D32", "#4CAF50")))
                rc = run_process(cmd, plugin_dir, env, self._logger,
                                 "调试源码", canceller)
            else:  # 调试运行：先构建（状态「构建中」），再运行（状态「运行中」）
                ctx = self._make_debug_ctx(canceller)
                self._logger.info("调试构建（文件夹输出到 插件目录/debug/）...")
                self.after(0, lambda: self._set_status(
                    "构建中...", ("#B8860B", "#E6B84B")))
                artifact = build_for_debug(ctx, self._pm.read_manifest())
                if artifact is None:
                    return
                entry = locate_debug_entry(ctx, artifact)
                if entry is None:
                    self._logger.error(f"未找到调试入口: {artifact}")
                    return
                self._logger.info(f"运行产物: {entry}")
                self.after(0, lambda: self._set_status(
                    "运行中", ("#2E7D32", "#4CAF50")))
                rc = run_process([str(entry)], artifact, env, self._logger,
                                 "调试运行", canceller)
            self._logger.info(f"调试进程退出码: {rc}")
        finally:
            self._canceller = None
            self._running = False
            self.after(0, self._finish_run)

    def _finish_run(self) -> None:
        self._set_status("已停止" if self._running is False else "空闲")
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")
        self._notify_state()

    # ------------------------------------------------------------------
    # 外部钩子
    # ------------------------------------------------------------------

    def set_plugin_dir(self, d: str, pm: ProjectManager | None = None) -> None:
        if pm:
            self._pm = pm
        self._plugin_dir = d
        self._set_enabled(True)
        self._update_hint()

    def is_running(self) -> bool:
        return self._running
