"""Debug tab — 调试运行（全中文 UI）。

- 调试运行：Packer 构建（始终 folder + 固定输出 plugin_dir/debug/，
  增量缓存：PyInstaller Analysis / tsc tsbuildinfo / npm lock），
  在产物文件夹内运行插件入口
- 环境变量区：主机 / 端口 / 令牌，支持本机 DGHub 探测自动填充与手动填写
- 插件 stdout/stderr 统一进底部日志面板的「调试输出」子视图
  （logbus external）；本页仅状态行
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
                                  resolve_run_command, run_process)
from backend.builder import Builder
from backend.logbus import Logger
from backend.pipeline import BuildContext
from backend.project_manager import ProjectManager
from gui.ui_dispatch import ui
from gui.widgets import BG1, FillScrollable

# 右栏各行统一的前导标签宽度（像素）
_LABEL_W = 92


class DebugTab(ctk.CTkFrame):
    """调试页：检测 DGHub + 启动/停止 + 状态行。"""

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
        # 页面级滚动（内容填满视口，日志面板压缩视口时超高内容可滚动）
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        scroll = FillScrollable(self)
        scroll.grid(row=0, column=0, sticky="nsew")
        c = scroll.content
        # 第一层浮动卡片（BG1）：tab 全部内容一个 frame，浮在全局背景上
        main_card = ctk.CTkFrame(c, fg_color=BG1, corner_radius=8)
        main_card.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        main_card.grid_columnconfigure(1, weight=1)

        # ---- row 0: 检测 DGHub ----
        row = ctk.CTkFrame(main_card, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2, sticky="ew",
                 padx=10, pady=(10, 0))
        row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(row, text="调试", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        detect_row = ctk.CTkFrame(row, fg_color="transparent")
        detect_row.grid(row=0, column=1, sticky="w", padx=5)
        self._detect_btn = ctk.CTkButton(
            detect_row, text="检测 DGHub", width=110,
            command=self._detect_clicked)
        self._detect_btn.pack(side="left")
        self._controls.append(self._detect_btn)
        self._detect_hint = ctk.CTkLabel(
            detect_row, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"), anchor="w")
        self._detect_hint.pack(side="left", padx=(8, 0))

        # ---- row 1: 启动/停止 + 状态 ----
        bottom = ctk.CTkFrame(main_card, fg_color="transparent")
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew",
                    padx=10, pady=(12, 0))
        bottom.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(bottom, text="操作", width=_LABEL_W, anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=(0, 5), sticky="w")
        action_row = ctk.CTkFrame(bottom, fg_color="transparent")
        action_row.grid(row=0, column=1, sticky="w", padx=5)
        self._start_btn = ctk.CTkButton(
            action_row, text="启动调试", width=110,
            command=self._start_clicked)
        self._start_btn.pack(side="left")
        self._controls.append(self._start_btn)
        self._stop_btn = ctk.CTkButton(
            action_row, text="停止", width=90,
            command=self._stop_clicked)
        self._stop_btn.pack(side="left", padx=(8, 0))
        self._controls.append(self._stop_btn)
        self._status_lbl = ctk.CTkLabel(
            action_row, text="空闲", font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"), anchor="w")
        self._status_lbl.pack(side="left", padx=(16, 0))

        # ---- row 2: 动态提示行（模式说明 / 校验结果） ----
        self._hint_lbl = ctk.CTkLabel(
            main_card, text="", font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"), anchor="w",
            wraplength=640, justify="left")
        self._hint_lbl.grid(row=2, column=0, columnspan=2, sticky="ew",
                            padx=(10, 10), pady=(8, 0))

    # ------------------------------------------------------------------
    # 状态与提示
    # ------------------------------------------------------------------

    def _update_hint(self) -> None:
        """编译系统校验提示（构建与运行细节在调试时展示）。"""
        comp = self._current_compiler()
        if comp is None:
            self._hint_lbl.configure(
                text="请先在编译页选择编译系统", text_color=("gray40", "gray60"))
            return
        # 清单格式与编译系统匹配性检查
        manifest = ""
        if self._pm:
            manifest = self._pm.read_project().get("compiler", {}).get("manifest", "") or ""
        if manifest and not comp.is_known_manifest(Path(manifest).name):
            need = "package.json" if comp.id == "node" else "pyproject.toml"
            self._hint_lbl.configure(
                text=f"清单格式与编译系统不匹配，{comp.label} 需要 {need}",
                text_color=("#C0504D", "#E57373"))
            return
        # 正常提示：构建后运行
        self._hint_lbl.configure(
            text="构建后运行，位于 插件目录/debug/ 下（增量缓存："
                 "PyInstaller Analysis / tsc tsbuildinfo / npm lock）",
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
            ui(lambda: self._on_detect_success(token))
        else:
            ui(self._on_detect_fail)

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
        if not self._token_var.get().strip():
            self._set_status("请先检测 DGHub", ("#C0504D", "#E57373"))
            return
        self._running = True
        self._set_status("启动中...", ("#2E7D32", "#4CAF50"))
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._notify_state()
        # env 在主线程构造（StringVar 读取限主线程），随线程传入
        env = self._build_env()
        threading.Thread(target=self._run, args=(env,), daemon=True).start()

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
            compile_cfg = {"manifest": project.get("compiler", {}).get("manifest", ""),
                           "self_contained": project.get("compiler", {}).get("self_contained", True),
                           "auto_suffix": project.get("compiler", {}).get("auto_suffix", False)}
        elif compile_system == "node":
            compile_cfg = {"manifest": project.get("compiler", {}).get("manifest", ""),
                           "self_contained": project.get("compiler", {}).get("self_contained", True),
                           "auto_suffix": project.get("compiler", {}).get("auto_suffix", False)}
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
            builder=Builder(self._pm) if self._pm else Builder(
                ProjectManager(str(plugin_dir))),
            log=self._logger,
            pm=self._pm,
            pypi_index=settings_store.get_state("pypi_index", ""),
            canceller=canceller,
            compile_cfg=compile_cfg,
            keep_cache=True,  # 调试构建保留 .deps / cache（PyInstaller 增量）
        )

    def _run(self, env: dict) -> None:
        canceller = Canceller()
        self._canceller = canceller
        rc = -1
        try:
            # 调试运行：先构建（增量缓存），再运行产物（构建过程与目标
            # 结构是调试对象本身——deps 模式同样需要 npm install + tsc）
            ctx = self._make_debug_ctx(canceller)
            self._logger.info("调试构建（文件夹输出到 插件目录/debug/）...")
            ui(lambda: self._set_status("构建中...", ("#B8860B", "#E6B84B")))
            if self._pm is None:
                return
            artifact = build_for_debug(ctx, self._pm.read_manifest())
            if artifact is None:
                return
            entry = locate_debug_entry(ctx, artifact)
            if entry is None:
                self._logger.error(f"未找到调试入口: {artifact}")
                return
            # SDK manifest 定位约定（agent.py manifest_dir 三档解析）：
            # 依赖版源码态帧解析偏移（vendor 内），注入产物根兜底
            env["DGHUB_MANIFEST_DIR"] = str(artifact)
            # 模拟宿主协议（PLUGIN_DEVELOPMENT.md：.py 入口可导入 entry
            # 所在目录、插件根、插件根 vendor/）——依赖版调试直跑源码入口
            if str(entry).lower().endswith(".py"):
                paths = [str(entry.parent), str(artifact),
                         str(artifact / "vendor")]
                merged = os.pathsep.join(
                    p for p in paths if Path(p).is_dir())
                old = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = (merged + os.pathsep + old
                                     if merged and old else merged or old)
            self._logger.info(f"运行产物: {entry}")
            ui(lambda: self._set_status("运行中", ("#2E7D32", "#4CAF50")))
            rc = run_process(resolve_run_command(entry), artifact,
                             env, self._logger, "调试运行", canceller)
            self._logger.info(f"调试进程退出码: {rc}")
        finally:
            self._canceller = None
            self._running = False
            ui(self._finish_run)

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
