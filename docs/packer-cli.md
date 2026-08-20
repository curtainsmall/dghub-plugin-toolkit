# DGHub SDK Packer CLI

面向持续集成的**只读构建命令行**——唯一命令 `build`，读取 `.dghub-sdk/` 两阶段
构建出包。项目配置唯一来源是 GUI 生成的 `.dghub-sdk/`（建议提交进 git 版本化）；
CLI 不修改项目配置（只写输出目录）。

## 用法

```bash
dgpacker-cli build [插件目录] [--pypi-index URL] [--no-color]
dgpacker-cli --version
```

- 默认目录为当前目录；`--pypi-index` 为运行期镜像覆盖（不落盘）
- stdout 日志（CI 可捕获；`--no-color` 禁用 ANSI 着色）
- 退出码（应用层约定，跨平台一致）：`0` 成功 / `2` 用法错误（如缺
  `.dghub-sdk/`）/ `3` 校验失败 / `4` 构建失败 / `130` 取消（Ctrl+C）
- 前置：打包环境需系统 Python + uv + PyInstaller（PyInstaller 仅 Python
  编译需要）；CLI 不加载 GUI 依赖（无需 tkinter）

## .dghub-sdk 项目结构

`.dghub-sdk/` 目录包含两个 JSON 配置文件，均由 GUI 管理（也可脚本生成）：

```
.dghub-sdk/
├── manifest.json    # 插件元信息（构建时并入产物，GUI 信息页编辑）
└── project.json     # 项目构建配置（GUI 编译/构建页编辑）
```

### project.json

```json
{
  "compiler": {
    "compile_system": "python",
    "compile": "",
    "compile_dir": "",
    "manifest": "pyproject.toml",
    "self_contained": true,
    "auto_suffix": false
  },
  "builder": {
    "files": [
      { "path": "assets/logo.png" },
      { "dir": "assets" }
    ],
    "output_dir": "",
    "packer_name": ""
  }
}
```

**compiler 节**（编译配置）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `compile_system` | `""` / `"python"` / `"node"` / `"command"` | 编译选择 |
| `compile` | string | CommandCompiler 命令（`"command"` 时必填） |
| `compile_dir` | string | CommandCompiler 执行目录（空 = 项目根） |
| `manifest` | string | Python/Node.js 编译的依赖清单（`"python"`/`"node"` 时必填） |
| `self_contained` | bool | 产物模式：`true` 自包含（默认，运行时打进 exe）/ `false` 依赖版（`vendor/` 分发，目标机需 Python/Node 运行时） |
| `auto_suffix` | bool | 构建页「按产物模式加后缀」：开启时包名自动追加 `-self_contained` / `-dependent`（后缀文本可在设置页自定义，存于 `~/.dghub-sdk-packer`） |

**builder 节**（打包配置）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `files` | list | 打包内容条目（见下） |
| `output_dir` | string | 输出目录（空 = 插件目录/output） |
| `packer_name` | string | 自定义包名（空 = 插件目录名） |

**files 条目**：`value` + `kind`（`"file"` / `"dir"` / `"pattern"`）；
旧格式 `path` / `dir` / `pattern` 三选一在读取时自动迁移。**入口
（entry）不持久化**——完全由编译系统 deduce 自动生成：Python 自包含
为 `<插件名>.exe`、依赖版为 `[tool.dghub].entry` 源码；Node.js 自包含
为 SEA exe、依赖版为 `bootstrap.py` 启动脚本。旧数据中的
`tags: ["entry"]` 读取时兼容（迁移期生效）。**编译产物条目（exe /
`_internal` / `node_modules` / `vendor` 等）不落盘**——总能从编译设置
（`compile_system` + `manifest` + `self_contained`）推导，运行时注入
视图，`project.json` 只保存手动打包内容；`manifest.json` 作为固定声明
条目始终在视图首位；旧版残留的 `derived` / `auto` 条目在加载时自动
清理。

编译入口声明（Packer 构建时读取，不写入 project.json）：Python 由
`pyproject.toml` 的 `[tool.dghub].entry` 声明，Node.js 由
`package.json` 的 `main` 字段声明。

## CI 示例

```yaml
# GitHub Actions
- name: Build plugin
  run: dgpacker-cli build ./my-plugin
```
