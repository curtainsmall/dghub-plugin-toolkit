# DGHub SDK Toolkit

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5.5%2B-blue)
![License](https://img.shields.io/badge/License-AGPLv3-green)

[DGHub](http://dghub.top/) 插件开发工具集，包含 Python / TypeScript SDK 和图形化打包工具。

## SDK

提供插件与 DGHub 主程序之间的 WebSocket 通信封装，各语言实现功能对齐：
自动连接与会话管理、配置同步、强度控制、设备状态监听。

### Python

位于 `sdk/python/`。

```bash
pip install dghub-sdk
```

```python
import dghub_sdk

with dghub_sdk.Agent() as agent:
    agent.on_config_changed = lambda key, value: print(key, value)
    agent.wait_ready(timeout=10)   # 等待握手完成后再 poll
    while True:
        agent.poll()
```

### TypeScript

位于 `sdk/typescript/`。

```bash
npm install dghub-sdk
```

```ts
import { Agent } from "dghub-sdk";

let running = true;
const agent = new Agent({
  onStop: () => { running = false; },
});
agent.start();
await agent.waitReady(10);   // 等待握手完成后再 poll
while (running) {
  agent.poll();
}
```

详细用法参见 [Python SDK 使用指南](docs/sdk-python.md) 与 [TypeScript SDK 使用指南](docs/sdk-typescript.md)。

## Packer

位于 `packer/`，图形化桌面应用，帮助开发者打包和分发 DGHub 插件（纯 GUI 工具）。

- 构建 — 编译（Python / Node (TypeScript) / 自定义命令 / 无）→ 打包；编译入口由项目清单声明，无需在 GUI 填写
- 插件信息编辑 — 可视化填写元信息与 `config_schema`（分组/字段编辑器），产物 `manifest.json` 构建时自动生成
- 依赖管理 — 依赖由项目自身清单声明，自动下载并打进自包含 exe
- 打包内容 — 文件 / 目录 / 规则三种条目 + 入口标记；编译产物自动声明；校验错误条目级高亮
- 发布 — 固定 `.zip` 分发，Python 项目自动构建为独立 exe
- 本地调试 — 调试 tab：调试源码（uv run）或调试运行（构建后运行产物），支持自动检测 DGHub 拉取令牌
- 自动更新 — 启动检查 GitHub 最新正式版，下载 / 安装 / 忽略此版本

### 下载

从 [Releases](https://github.com/curtainsmall/dghub-sdk-toolkit/releases) 下载 `dghub-sdk-packer-setup.exe` 安装（每用户，无需管理员）。安装后：开始菜单「DGHub SDK Packer」启动 GUI；安装目录已入 PATH，CI 可用 `dgpacker-cli build`（只读构建，详见 [Packer CLI 文档](docs/packer-cli.md)）。

### 从源码运行

```bash
# 安装依赖（需要 uv）
uv sync --project packer

# 运行 GUI
uv run --project packer python packer/src/gui/main.py

# 构建 Windows 安装器（需 Inno Setup 6）
uv run --project packer python packer/build.py
```

## Demo

- `demo/tetris-py/` — 俄罗斯方块示例插件（Python + pygame），演示 SDK 集成与强度触发
- `demo/tetris-ts/` — 俄罗斯方块示例插件（TypeScript + SDL2 窗口），与 Python 版功能对齐

## License

AGPLv3 · 适用于 DGHub SDK v1

---

**另见：**[插件开发协议规范](docs/PLUGIN_DEVELOPMENT.md)
