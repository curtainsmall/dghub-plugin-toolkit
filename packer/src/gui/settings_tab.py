"""Settings / About tab."""

import os
import threading
import webbrowser
from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from backend import settings_store
from backend.updater import (DownloadCancelled, check_latest,
                             cleanup_stale_installers, download_installer,
                             get_current_version, is_newer, update_dest)

try:
    from backend._version import __version__ as APP_VERSION
except ImportError:
    # 开发模式：backend/_version.py 仅在构建期生成
    APP_VERSION = "dev"
GITHUB_URL = "https://github.com/curtainsmall/dghub-sdk-toolkit"
DGHUB_URL = "http://dghub.top/"


def _fmt_size(n: int) -> str:
    """字节数 → 人类可读（KB / MB）。"""
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024:.0f} KB"

# PyPI 镜像源预设：显示名 → index URL（空 = 跟随 uv 默认，即官方源）
PYPI_INDEX_PRESETS: dict[str, str] = {
    "官方 (pypi.org)": "",
    "清华 (tuna)": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "阿里云 (aliyun)": "https://mirrors.aliyun.com/pypi/simple",
    "中科大 (ustc)": "https://mirrors.ustc.edu.cn/pypi/simple",
}

# 外观模式选项：显示名 → customtkinter 值（默认深色）
_THEME_CHOICES: list[tuple[str, str]] = [
    ("跟随系统", "system"),
    ("浅色", "light"),
    ("深色", "dark"),
]


class SettingsTab(ctk.CTkFrame):
    """Settings and about page."""

    _DEFAULT_HOST = "localhost"
    _DEFAULT_PORT = "8000"

    def __init__(self, master: Any,
                 on_pypi_index_changed: Callable[[str], None] | None = None,
                 on_suffix_changed: Callable[[], None] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._on_pypi_index_changed = on_pypi_index_changed
        self._on_suffix_changed_cb = on_suffix_changed
        self._host_var = ctk.StringVar(value=self._DEFAULT_HOST)
        self._port_var = ctk.StringVar(value=self._DEFAULT_PORT)
        # 更新状态（自动检查外部触发时填充）
        self._latest_version = ""
        self._latest_url = ""
        self._update_cancel = False
        self._build_ui()
        self._load_env()

    # -- public API ---------------------------------------------------

    def get_pypi_index(self) -> str:
        """当前生效的镜像源 URL（空 = 官方）。"""
        label = self._pypi_menu.get()
        return PYPI_INDEX_PRESETS.get(label, "")

    def set_pypi_index(self, url: str) -> None:
        """按 URL 恢复下拉选项（未知 URL 回退官方）。"""
        for label, preset_url in PYPI_INDEX_PRESETS.items():
            if preset_url == url:
                self._pypi_menu.set(label)
                return
        self._pypi_menu.set(next(iter(PYPI_INDEX_PRESETS)))

    def get_host(self) -> str:
        return self._host_var.get().strip() or self._DEFAULT_HOST

    def get_port(self) -> str:
        return self._port_var.get().strip() or self._DEFAULT_PORT

    def set_host(self, host: str) -> None:
        self._host_var.set(host)
        self._save_env()

    def set_port(self, port: str) -> None:
        self._port_var.set(port)
        self._save_env()

    # -- public API ---------------------------------------------------

    def show_update(self, latest: str, url: str, size: int) -> None:
        """外部（启动自动检查）触发：展示下载 UI。
    
        若该版本 installer 已下载过，直接进入「安装更新」态。
        """
        self._latest_version = latest
        self._latest_url = url
        self._update_cancel = False
        dest = update_dest(latest)
        if dest.is_file():
            self._update_status.configure(
                text=f"{latest} 已下载，可安装",
                text_color="green")
            self._update_btn.configure(state="normal", text="安装更新",
                                       command=lambda: self._on_install(dest))
        else:
            self._update_status.configure(
                text=f"发现新版本 {latest}（{_fmt_size(size)}）",
                text_color=("#1f6aa5", "#7eb8e0"))
            self._update_btn.configure(state="normal", text="下载更新",
                                       command=self._on_download)

    def start_download(self) -> None:
        """立即开始下载（自动检查弹窗点「下载」后由 App 调用）。"""
        if self._latest_url:
            self._on_download()

    # -- UI -----------------------------------------------------------

    def _build_update_row(self, info_frame: ctk.CTkFrame, row: int) -> None:
        """应用信息区内新增一行更新控件（检查 / 下载 / 安装状态机）。"""
        self._update_btn = ctk.CTkButton(
            info_frame, text="检查更新", width=120,
            command=self._on_check_update)
        self._update_btn.grid(row=row, column=0, sticky="w",
                              padx=(10, 5), pady=3)
        self._update_status = ctk.CTkLabel(
            info_frame, text="", font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"))
        self._update_status.grid(row=row, column=1, sticky="w", padx=5, pady=3)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        # 内容过长：整体放入滚动容器
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=0, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # -- App Info --
        info_frame = ctk.CTkFrame(self._scroll)
        info_frame.grid(row=row, column=0, sticky="ew",
                        padx=10, pady=(2, 5))
        info_frame.grid_columnconfigure(1, weight=1)
        row += 1

        ctk.CTkLabel(info_frame, text="应用信息",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        labels = [
            ("应用名称", "DGHub SDK Toolkit — Packer"),
            ("版本", APP_VERSION),
        ]
        for i, (k, v) in enumerate(labels, 1):
            ctk.CTkLabel(info_frame, text=f"{k}:",
                         font=ctk.CTkFont(size=13)).grid(
                row=i, column=0, sticky="w", padx=(10, 5), pady=3)
            ctk.CTkLabel(info_frame, text=v,
                         font=ctk.CTkFont(size=13), text_color=("gray20", "gray80")).grid(
                row=i, column=1, sticky="w", padx=5, pady=3)

        # 更新检查（dev / 无版本构建：按钮可见但禁用）
        self._build_update_row(info_frame, len(labels) + 1)
        if APP_VERSION in ("dev", "No Version"):
            self._update_btn.configure(state="disabled")
            self._update_status.configure(
                text="开发版本不支持检查更新",
                text_color=("gray30", "gray70"))

        # -- Theme --
        theme_frame = ctk.CTkFrame(self._scroll)
        theme_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkLabel(theme_frame, text="主题设置",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(theme_frame, text="外观模式:").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=10)
        self._theme_menu = ctk.CTkOptionMenu(
            theme_frame, values=[label for label, _ in _THEME_CHOICES],
            command=self._on_theme_changed)
        self._theme_menu.grid(row=1, column=1, sticky="w", padx=5, pady=10)
        self._theme_menu.set("深色")  # 默认深色
        ctk.set_appearance_mode("dark")

        # -- Build (PyPI index) --
        build_frame = ctk.CTkFrame(self._scroll)
        build_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkLabel(build_frame, text="构建设置",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(build_frame, text="PyPI 镜像源:").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=(0, 4))
        self._pypi_menu = ctk.CTkOptionMenu(
            build_frame, values=list(PYPI_INDEX_PRESETS), width=220,
            command=self._pypi_changed)
        self._pypi_menu.grid(row=1, column=1, sticky="w", padx=5, pady=(0, 4))
        self._pypi_menu.set(next(iter(PYPI_INDEX_PRESETS)))

        ctk.CTkLabel(
            build_frame,
            text="打包依赖（uv 下载）时使用的下载源；网络无法访问官方源时"
                 "可切换为国内镜像。",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
            wraplength=600, justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w",
               padx=10, pady=(0, 10))

        # 产物名后缀（构建页开启「按产物模式加后缀」时使用；
        # 留空 = 默认值，placeholder 提示；不传 textvariable——
        # customtkinter 6.x 传自定义 variable 时 placeholder 无法激活）
        ctk.CTkLabel(build_frame, text="自包含后缀:").grid(
            row=3, column=0, sticky="w", padx=(10, 5), pady=(0, 4))
        self._suffix_exe_entry = ctk.CTkEntry(
            build_frame, width=220, placeholder_text="-self-contained")
        self._suffix_exe_entry._is_focused = False
        self._suffix_exe_entry.grid(row=3, column=1, sticky="w",
                                    padx=5, pady=(0, 4))
        self._suffix_exe_entry.bind("<KeyRelease>", self._on_suffix_changed)

        ctk.CTkLabel(build_frame, text="依赖版后缀:").grid(
            row=4, column=0, sticky="w", padx=(10, 5), pady=(0, 4))
        self._suffix_deps_entry = ctk.CTkEntry(
            build_frame, width=220, placeholder_text="-dependent")
        self._suffix_deps_entry._is_focused = False
        self._suffix_deps_entry.grid(row=4, column=1, sticky="w",
                                     padx=5, pady=(0, 4))
        self._suffix_deps_entry.bind("<KeyRelease>", self._on_suffix_changed)

        ctk.CTkLabel(
            build_frame,
            text="「按产物模式加后缀」开启时追加到包名的后缀（仅字母/数字/"
                 "下划线/连字符）；留空使用默认值。",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
            wraplength=600, justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w",
               padx=10, pady=(0, 10))

        # -- Debug (DGHub host/port) --
        runtime_frame = ctk.CTkFrame(self._scroll)
        runtime_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkLabel(runtime_frame, text="调试设置",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkLabel(runtime_frame, text="主机（DGHUB_HOST）:").grid(
            row=1, column=0, sticky="w", padx=(10, 5), pady=(0, 4))
        host_entry = ctk.CTkEntry(runtime_frame, textvariable=self._host_var,
                                 width=240)
        host_entry._is_focused = False  # placeholder/焦点状态统一
        host_entry.grid(row=1, column=1, sticky="w", padx=5, pady=(0, 4))
        self._host_var.trace_add("write", lambda *_: self._save_env())

        ctk.CTkLabel(runtime_frame, text="端口（DGHUB_PORT）:").grid(
            row=2, column=0, sticky="w", padx=(10, 5), pady=(0, 4))
        port_entry = ctk.CTkEntry(runtime_frame, textvariable=self._port_var,
                                 width=240)
        port_entry._is_focused = False  # placeholder/焦点状态统一
        port_entry.grid(row=2, column=1, sticky="w", padx=5, pady=(0, 4))
        self._port_var.trace_add("write", lambda *_: self._save_env())

        ctk.CTkLabel(
            runtime_frame,
            text="Packer 调试插件时注入子进程的主机与端口（插件正式运行时"
                 "由 DGHub 主程序自行注入，无需此处配置）。",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
            wraplength=600, justify="left",
        ).grid(row=3, column=0, columnspan=2, sticky="w",
               padx=10, pady=(0, 10))

        # -- Reset defaults --
        reset_frame = ctk.CTkFrame(self._scroll)
        reset_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkButton(reset_frame, text="恢复默认", width=120,
                      command=self._reset_defaults).grid(
            row=0, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkButton(reset_frame, text="打开配置目录", width=120,
                      command=self._open_config_dir).grid(
            row=0, column=1, sticky="w", padx=(0, 10), pady=10)

        # -- License --
        license_frame = ctk.CTkFrame(self._scroll)
        license_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkLabel(license_frame, text="开源协议",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        ctk.CTkLabel(
            license_frame,
            text="AGPLv3 — 本项目基于 GNU Affero General Public License v3 开源。",
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
            wraplength=600, justify="left",
        ).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 10))

        # -- Links（置于页面底部）--
        link_frame = ctk.CTkFrame(self._scroll)
        link_frame.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        row += 1

        ctk.CTkLabel(link_frame, text="相关链接",
                     font=ctk.CTkFont(size=15, weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 5))

        ctk.CTkButton(link_frame, text="🌐 GitHub 仓库",
                      command=lambda: webbrowser.open(GITHUB_URL),
                      width=200).grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ctk.CTkButton(link_frame, text="🌐 DGHub 官网",
                      command=lambda: webbrowser.open(DGHUB_URL),
                      width=200).grid(row=2, column=0, padx=10, pady=5, sticky="w")

    def _on_theme_changed(self, label: str) -> None:
        """外观模式选项变化 → 应用对应 customtkinter 值。"""
        value = next((v for l, v in _THEME_CHOICES if l == label), "dark")
        ctk.set_appearance_mode(value)

    def _reset_defaults(self) -> None:
        """恢复默认：外观深色、镜像官方源、主机 localhost、端口 8000。"""
        if not messagebox.askyesno(
                "恢复默认",
                "确定恢复全部默认设置？"):
            return
        self._theme_menu.set("深色")
        ctk.set_appearance_mode("dark")
        self._pypi_menu.set(next(iter(PYPI_INDEX_PRESETS)))
        if self._on_pypi_index_changed:
            self._on_pypi_index_changed("")
        self._host_var.set(self._DEFAULT_HOST)
        self._port_var.set(self._DEFAULT_PORT)
        self._save_env()

    def _open_config_dir(self) -> None:
        """在文件管理器中打开全局配置目录（state.json 所在）。"""
        path = settings_store.config_dir()
        try:
            os.startfile(str(path))  # Windows
        except Exception:
            webbrowser.open(path.as_uri())

    def _pypi_changed(self, _label: str) -> None:
        """镜像源选项变化时通知外部（实时保存）。"""
        if self._on_pypi_index_changed:
            self._on_pypi_index_changed(self.get_pypi_index())

    def _load_env(self) -> None:
        saved = settings_store.get_state("debug_env", {})
        if isinstance(saved, dict):
            if saved.get("host") and saved["host"] != "localhost":
                self._host_var.set(saved["host"])
            if saved.get("port") and saved["port"] != "8000":
                self._port_var.set(saved["port"])
        # 产物名后缀（设置页可自定义；非法/空回退默认）
        suffixes = settings_store.get_state("pack_suffixes", {})
        if isinstance(suffixes, dict):
            if suffixes.get("exe"):
                self._suffix_exe_entry.insert(0, suffixes["exe"])
            if suffixes.get("deps"):
                self._suffix_deps_entry.insert(0, suffixes["deps"])

    def _save_env(self) -> None:
        settings_store.save_state_key("debug_env", {
            "host": self._host_var.get().strip(),
            "port": self._port_var.get().strip(),
        })

    def _on_suffix_changed(self, *args: Any) -> None:
        """后缀输入变化（KeyRelease）→ 保存并通知外部刷新构建预览。

        CTkEntry.get() 在 placeholder 激活时返回空串——留空即回退默认值。
        """
        settings_store.save_state_key("pack_suffixes", {
            "exe": self._suffix_exe_entry.get(),
            "deps": self._suffix_deps_entry.get(),
        })
        if self._on_suffix_changed_cb:
            self._on_suffix_changed_cb()

    # -- update 状态机 --------------------------------------------------

    def _on_check_update(self) -> None:
        """点击「检查更新」：后台线程查询 GitHub 最新正式版。"""
        self._update_btn.configure(state="disabled", text="检查中…")
        self._update_status.configure(text="正在检查更新…",
                                      text_color=("gray30", "gray70"))
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        latest, url, size = check_latest()
        self.after(0, lambda: self._on_check_done(latest, url, size))

    def _on_check_done(self, latest: str | None, url: str | None,
                       size: int) -> None:
        """检查结果落到 UI：已最新 / 发现新版 / 失败。"""
        self._update_btn.configure(state="normal", text="检查更新",
                                   command=self._on_check_update)
        if not latest or not url:
            self._update_status.configure(text="检查失败（网络异常）",
                                          text_color="red")
            return
        current = get_current_version()
        if not is_newer(latest, current):
            self._update_status.configure(text="已是最新版本",
                                          text_color=("gray30", "gray70"))
            return
        self.show_update(latest, url, size)

    def _on_download(self) -> None:
        """点击「下载更新」：后台线程下载 installer，进度回传 UI。"""
        if not self._latest_url:
            return
        self._update_cancel = False
        self._update_btn.configure(text="取消", command=self._on_cancel_download)
        self._update_status.configure(text="正在下载…",
                                      text_color=("gray30", "gray70"))
        dest = update_dest(self._latest_version)
        threading.Thread(target=self._download_worker, args=(dest,),
                         daemon=True).start()

    def _download_worker(self, dest) -> None:
        try:
            ok = download_installer(
                self._latest_url, dest, on_progress=self._on_progress,
                is_cancelled=lambda: self._update_cancel)
        except DownloadCancelled:
            self.after(0, self._on_download_cancelled)
            return
        if ok:
            self.after(0, lambda: self._on_download_done(dest))
        else:
            self.after(0, self._on_download_failed)

    def _on_progress(self, downloaded: int, total: int) -> None:
        """后台线程进度回调 → 切回主线程更新进度条与文案。"""
        if total:
            self.after(0, lambda: self._set_progress(downloaded, total))

    def _set_progress(self, downloaded: int, total: int) -> None:
        self._update_status.configure(
            text=f"{_fmt_size(downloaded)} / {_fmt_size(total)}"
                 f"（{downloaded * 100 // total}%）",
            text_color=("gray30", "gray70"))

    def _on_download_done(self, dest) -> None:
        # 清理其他版本的 installer，避免临时目录堆积孤儿文件
        cleanup_stale_installers(self._latest_version)
        self._update_status.configure(text=f"{self._latest_version} 已下载",
                                      text_color="green")
        self._update_btn.configure(state="normal", text="安装更新",
                                   command=lambda: self._on_install(dest))

    def _on_download_failed(self) -> None:
        self._update_status.configure(text="下载失败，请重试", text_color="red")
        self._update_btn.configure(state="normal", text="下载更新",
                                   command=self._on_download)

    def _on_download_cancelled(self) -> None:
        self._update_status.configure(text="下载已取消",
                                      text_color=("gray30", "gray70"))
        self._update_btn.configure(state="normal", text="下载更新",
                                   command=self._on_download)

    def _on_install(self, dest) -> None:
        """点击「安装更新」：启动 installer 后关闭 Packer。"""
        if not dest.is_file():
            self._update_status.configure(text="安装包缺失，请重新下载",
                                          text_color="red")
            self._update_btn.configure(text="下载更新", command=self._on_download)
            return
        os.startfile(str(dest))
        self.winfo_toplevel().destroy()

    def _on_cancel_download(self) -> None:
        """点击「取消」：置标志，下载线程下个 chunk 前退出。"""
        self._update_cancel = True
        self._update_btn.configure(state="disabled", text="取消中…")
