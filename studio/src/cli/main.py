"""CLI 入口：dgstudio-cli（CI 专用只读构建）。

从 studio/src 运行：

    python -m cli.main build [目录]

安装后（onedir 内）：`dgstudio-cli build [目录]`。
"""

import sys

from cli.cli import dispatch


def main() -> int:
    return dispatch(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
