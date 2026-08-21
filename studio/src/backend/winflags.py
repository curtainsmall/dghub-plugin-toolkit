"""子进程创建标志：抑制 Windows 控制台窗口弹出（单一来源）。

GUI 为 windowed 应用，spawn 控制台工具（uv/PyInstaller/taskkill 等）时若不带
此标志会闪黑窗；非 Windows 平台取 0（该标志为 Windows 特有）。
"""

import os
import subprocess

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
