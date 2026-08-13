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
    "manifest": "pyproject.toml"
  },
  "builder": {
    "files": [
      { "path": "my-plugin.exe", "tags": ["entry"] },
      { "dir": "assets" },
      { "pattern": "dist/**" }
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

**builder 节**（打包配置）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `files` | list | 打包内容条目（见下） |
| `output_dir` | string | 输出目录（空 = 插件目录/output） |
| `packer_name` | string | 自定义包名（空 = 插件目录名） |

**files 条目**：`path` / `dir` / `pattern` 三选一；`tags` 可含 `"entry"`
（入口标记，恰好一个，缺失/重复校验报错）；编译产物条目带 `derived: true`
（自动声明，勿手工维护）。

编译入口不在 project.json：Python 由 `pyproject.toml` 的 `[tool.dghub].entry`
声明，Node.js 由 `package.json` 的 `main` 字段声明，CLI 构建时直接读取。

## CI 示例

```yaml
# GitHub Actions
- name: Build plugin
  run: dgpacker-cli build ./my-plugin
```
