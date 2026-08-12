# DGHub SDK Packer 使用指南

图形化桌面工具，帮助开发者配置插件信息、打包并分发 DGHub 插件（产物
`manifest.json` 构建时自动生成）。配置与构建均在界面内完成；另附 **CI 专用
只读构建 CLI**（`dgpacker-cli build`）供持续集成出包。以插件目录下的
`.dghub-sdk/` 为项目数据源（类比 `.git/`，是「Packer 项目」的标志）。

---

## 下载与安装

从 [Releases](https://github.com/curtainsmall/dghub-sdk-toolkit/releases) 下载
`dghub-sdk-packer-setup.exe`，双击安装（每用户安装，无需管理员）。安装后
开始菜单「DGHub SDK Packer」启动 GUI；安装目录已加入用户 PATH，CI 可用
`dgpacker-cli`（见下）。

如需从源码运行（需要 [uv](https://docs.astral.sh/uv/)）：

```bash
uv sync --project packer
uv run --project packer python packer/src/gui/main.py
```

---

## 概念：两阶段构建

Packer 把「源码项目 → DGHub 插件包」拆成两阶段：

```
阶段 1：compile 编译（可选，显式单选）
   ├─ (无)          不执行任何构建步骤，直接收集打包内容
   ├─ Python          按依赖清单自动下载依赖 → PyInstaller 打包为自包含 exe（onedir）
   ├─ Node            按 package.json 安装依赖 → tsc 编译（可选）→ SEA 打包为 exe
   └─ 自定义命令       构建前执行用户命令（如编译），产物由打包内容声明
      │
      ▼
阶段 2：统一构建步骤（对所有编译一致）
   收集打包内容 + 编译产物 → 生成 manifest.json → 组装 zip / 文件夹
```

插件包结构（通用）：`manifest.json + 入口产物 + 其它资源（保留相对路径）`。
Python 编译的产物是 onedir 树（`<名>.exe` + `_internal/`），Node 编译的产物是
SEA exe（含 Node 运行时）+ `node_modules/` + 入口目录，收集时整树进入包。

---

## GUI 使用

### 工作流概览

```
选择插件目录 → （编译页）选择/配置编译 → （构建页）打包内容 → 构建
```

1. **打开插件目录** — 顶部栏选择插件目录（任意文件夹均可；Packer 在其中创建/读取 `.dghub-sdk/` 存放插件配置，首次选择即初始化新项目）
2. **编译页** — 下拉单选编译（无 / Python / Node / 自定义命令），并按所选编译填写设置（见下）
3. **信息页** — 填写插件元信息与配置 schema，产物 `manifest.json` 构建时自动生成
4. **构建页** — 打包内容（文件/目录/规则，可标记入口；Python 编译产物自动显式声明）与发布选项
5. **构建** — 导出 `.zip`（分发）或文件夹（调试）
6. **调试页** — 本地运行插件（调试源码 / 调试运行）

### 编译

编译页显式选择 compile 编译（单选下拉），选中后显示对应设置字段：

- **(无)** — 不执行 compile，构建页的打包内容直接收集（纯收集模式）
- **Python (uv + PyInstaller)** — 依赖清单必填（**仅 `pyproject.toml`**——唯一可声明编译入口 `[tool.dghub].entry` 的清单）；可选「包含 dghub-sdk」；清单格式受支持时绿色 `✓` 标注，不受支持浅红警示；旁有 PyInstaller 可用性标注（已安装绿色 `PyInstaller installed`，缺失红色 `PyInstaller required`，Packer 不自动安装）
- **Node (npm + SEA)** — 依赖清单必填（仅 `package.json`）；入口 = `main` 字段（缺省 `index.js`）；构建流程：`npm install` → 存在 `tsconfig.json` 时编译（`npm run build`，无脚本则 `npx tsc`）→ SEA 三件套打包自包含 exe（含 Node 运行时，约 50-70MB，Node 生态现状）；产物 = `<名>.exe` + `node_modules/` + 入口目录
- **自定义命令** — 编译命令必填（如 `dotnet build -c Release`），构建时先在执行目录执行（默认项目根），非零返回码视为构建失败；执行目录可单独选择（默认项目根）

「从编译填充构建内容」按钮（构建页）串联探测与推导：Python / Node 编译会自动
探测对应清单（`pyproject.toml` / `package.json`，建议清单）并把**编译产物显式
声明**为打包内容条目——Python：入口 exe（`<插件名>.exe`）与依赖目录
`_internal/`；Node：SEA exe 与 `node_modules/`、入口目录（标注「编译产物」、
只读不可编辑/删除）；只填空，不覆盖已有设置。
编译入口由用户在清单中声明（Python：`pyproject.toml` 的 `[tool.dghub].entry`；
Node：`package.json` 的 `main` 字段），Packer 构建时读取，不入 project.json。

### 构建

构建页配置打包内容与发布选项：

- **打包内容** — 统一文件选择列表，支持三种条目：
  - 文件（`添加文件` 打开系统多选对话框）
  - 目录（`添加目录`，保留相对子目录结构递归收集）
  - 规则（`添加规则`，glob 如 `dist/**`，构建时求值）
  - 入口由双击条目弹出的标签对话框标记（列表显示绿色「入口」徽标；恰好一个，缺失/重复构建校验报错）
- **输出目录** — 顶部栏选择（空 = 插件目录/output）
- **输出文件预览** — 实时树（打包内容 + Python 编译产物 = exe + `_internal/`）

依赖由项目自身的清单文件管理，Packer 只读清单并安装到中间目录（`.deps/`），
**不修改项目源文件、不修改项目外文件**（只写 `.dghub-sdk/` 与输出目录）。
Python 编译打包的 exe 完全自包含：依赖打进 `_internal/`，**DGHub 运行环境
对 exe 不可见**（websockets 等基础依赖不免费，需在清单中声明）。

### 构建执行与取消

- 点击底部「**开始构建**」启动；构建在后台运行，全过程锁定目录选择与各页编辑，避免中途改动导致状态不一致
- 校验一次性检测所有必填项（信息页 id / name / version、编译必要字段与编译入口、打包内容入口条目、输出目录），错误一次全部高亮：缺失的打包内容条目**行级红框红字**定位，打包内容整体问题（如缺少入口）**区域红框 + 提示**；修正任一字段即刻恢复其边框（tab 标题高亮一并消除），该页错误全部清除后「构建失败」状态一并消除
- 构建期间「开始构建」按钮变为「**取消构建**」：点击弹出二次确认，确认后立即终止正在运行的命令（compile / 依赖安装 / 打包，含其子进程树），并清理输出目录内已产生的中间产物（**不触碰用户源目录中的 compile 产物**）
- 关闭窗口时若构建仍在进行，会先终止子进程再退出，不残留 uv / PyInstaller / compile 进程

### 调试

- **调试源码** — `uv run` 运行入口源码，注入 `.dghub-sdk/` manifest
- **调试运行** — 构建到 `插件目录/debug/` 后在产物内运行入口
- 令牌输入 +「检测 DGHub」按钮自动拉取；主机/端口在设置页配置
- 调试期间禁用构建按钮（互斥），停止按钮终止进程树

### 设置

应用设置与关于页：

- **外观模式** — 跟随系统 / 浅色 / 深色（默认深色）
- **PyPI 镜像源** — 打包依赖（uv 下载）时使用的下载源（默认官方 pypi.org，预置清华 / 阿里云 / 中科大镜像）。网络无法访问官方源时切换为国内镜像即可；选择实时保存，全局生效（跨项目）。选「官方」时不注入任何配置，uv 自身的环境变量与配置文件照常生效
- **调试设置** — DGHUB_HOST / DGHUB_PORT（调试时注入子进程）
- **检查更新** — 每次启动自动检查 GitHub 最新正式版（dev / 无版本构建
  跳过），也可点「检查更新」按钮手动触发；发现新版弹窗可忽略此版本、
  下载（安装包已下载过则直接安装）；忽略的版本不再提示
- **恢复默认** — 一键复位（带确认对话框）
- 应用版本信息、相关链接与开源协议（AGPLv3）

### 日志

构建全过程输出集中显示：校验、compile、依赖安装、PyInstaller、打包逐步记录；校验失败与构建错误在此给出具体原因；旧版配置迁移等提示也记录于此。

- 分级着色：**错误**（红）/ **警告**（橙）/ **成功**（绿，仅最终产物 zip / 文件夹）三类着色，其余为普通信息（默认色）
- 外部工具（uv / PyInstaller 等）的原始输出以 `─── 来源 ───` 分隔块成段展示，并标注退出码
- 日志不自动清空：每次构建前插入 `━━━ 构建 时间 ━━━` 分隔行、历史累积，便于回看与对比；右上角「清空」按钮可手动清空

---

## CI 构建（dgpacker-cli）

面向持续集成的**只读构建 CLI**——唯一命令 `build`，读 `.dghub-sdk/` 两阶段
构建出包。**无任何配置命令**：项目配置唯一来源是 GUI 生成的 `.dghub-sdk/`
（建议提交进 git 版本化）；CLI 不修改项目配置（只写输出目录）。

```bash
dgpacker-cli build [插件目录] [--pypi-index URL] [--no-color]
# 源码运行：python -m cli.main build [插件目录]
```

- 默认目录为当前目录；`--pypi-index` 为运行期镜像覆盖（不落盘）
- stdout 日志（CI 可捕获；`--no-color` 禁用 ANSI 着色）
- 退出码（应用层约定，跨平台一致）：`0` 成功 / `2` 用法错误（如缺
  `.dghub-sdk/`）/ `3` 校验失败 / `4` 构建失败 / `130` 取消（Ctrl+C）
- CI 工作流：本地 GUI 配好项目并提交 → CI 里 `dgpacker-cli build` 一行出包

```yaml
# GitHub Actions 示例
- name: Build plugin
  run: dgpacker-cli build ./my-plugin
```

> CLI 不加载 GUI 依赖（无需 tkinter）；前置同 GUI：打包环境需系统 Python +
> uv + PyInstaller（PyInstaller 仅 Python 编译需要）。

---

## 项目配置（.dghub-sdk/project.json）

配置由 GUI 管理，无需手写；格式为顶层平铺 + builder 节：

```json
{
  "compile_system": "python",
  "compile": "",
  "compile_dir": "",
  "manifest": "pyproject.toml",
  "include_sdk": true,
  "builder": {
    "files": [
      { "path": "my-plugin.exe", "tags": ["entry"] },
      { "dir": "assets" },
      { "pattern": "dist/**" }
    ],
    "no_zip": false,
    "output_dir": ""
  }
}
```


---

## 从源码构建安装器

将 Packer 打包为 Windows 安装器（一步完成「源码 → onedir → 安装器」）：

```bash
uv sync --project packer
uv run --project packer python packer/build.py            # 可选 --version X.Y.Z
```

- 单 GUI exe（onedir：`dgpacker-gui.exe` + 共享 `_internal/`，无每次启动解压 → 启动更快）
- 产物：`packer/installer/dghub-sdk-packer-setup.exe`（onedir 中间物在 `packer/bin/dghub-sdk-packer/`）
- **前置**：本机需装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)（`ISCC` 在 PATH 或默认安装目录）；若 `[Languages]` 用到简体中文，需 `ChineseSimplified.isl` 在 Inno 的 `Languages\` 目录

> 依赖（含 PyInstaller）由 `packer/pyproject.toml` 声明，`uv sync` 会自动安装；Inno Setup 需单独安装。
