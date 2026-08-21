"""DGHub SDK Studio — GUI 入口。

用法：
    python -m gui.main            # 从 packer/src 运行
    # 或 PyInstaller 构建后：dgstudio-gui.exe（windowed）
"""

from pathlib import Path
import sys

# 确保 packer/src 在 sys.path 上，使 backend/gui/cli 作为顶层包可导入
# （源码直接运行需要；PyInstaller 冻结后 sys.path 已由打包器处理）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> None:
    # 导入 App 前先设定 CustomTkinter 外观
    import customtkinter as ctk
    ctk.set_appearance_mode("system")   # 跟随系统主题
    ctk.set_default_color_theme("blue")

    # PyInstaller onefile 模式下 Windows 需要此调用以正确处理 filedialog / DPI
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)

    from gui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
