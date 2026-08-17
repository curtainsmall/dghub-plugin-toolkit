# Changelog

本项目的所有重要变更记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
版本号为 toolkit 发布批次号，Packer 与 SDK 统一使用；SDK 仅在自身有变更
的批次发布至 PyPI（Python）与 npm（TypeScript）。

## [0.13.1] - 2026-08-17

### 修复

- **Packer**：Node.js 编译的 SEA 临时配置改用独立文件名
  `sea-config.packer.json`——不再覆盖/删除项目自带的 `sea-config.json`
  （其单文件特性在目录式产物下不生效，Packer 不读取）

### 变更

- **SDK (TypeScript)**：使用指南附录重写为「Packer 如何读取 Node.js
  项目结构」——入口声明 / 构建流程 / 依赖管理（npm 为准） / 产物布局 /
  插件作者须知（sea-config 不被使用的原因）
- **SDK (Python)**：使用指南新增「Packer 如何读取 Python 项目结构」
  附录——入口声明 / 构建流程 / 产物布局 / 插件作者须知（.spec 与
  `[tool.pyinstaller]` 被固定产物契约接管）

## [0.13.0] - 2026-08-17

### 新增

- **SDK (TypeScript)**：事件驱动 API——`Agent` 继承 `EventEmitter`，消息到达
  即分发到 `AgentEvent.*` 事件，无需手动 `poll()`；`AgentEvent` 枚举：
  `Ready` / `Config` / `ConfigChanged` / `DeviceInfo` / `Stop` / `Ping` /
  `Error`；`on` / `once` / `off` 类型化重载（事件名集合封闭、参数随事件名
  类型检查）
- **SDK (TypeScript)**：`waitForClose()`——ws 关闭后 resolve 的 Promise

### 变更

- **SDK (TypeScript)**：移除 `poll()` / `getException()` / `sendTimeout` /
  `waitThreadingExit`——错误处理改订阅 `AgentEvent.Error`（无人订阅时按
  Node 惯例抛出）；构造参数 `on*` 回调保留为事件注册语法糖
- **SDK (TypeScript)**：tsconfig 显式 `types: ["node"]`
- **Demo**：tetris-ts 改用事件驱动用法；README 与 sdk-typescript.md 同步更新

### 修复

- **SDK (TypeScript)**：修复握手完成后 `connected` 被立即置回 `false`、
  `waitReady()` 实际无法成功 resolve 的问题（后台循环退出逻辑残留）

## [0.12.1] - 2026-08-15

### 修复

- **Packer**：select 字段 options 改为条目列表格式（value + label）——旧字符串
  数组格式会被 DGHub 服务端拒绝握手；选项编辑支持值/标签双输入，列表区域
  可滚动

## [0.12.0] - 2026-08-15

### 新增

- **Packer**：构建时自动收集 `.deps` 中所有依赖包的数据文件与 dist-info
  元数据——修复 litellm 等带数据文件的依赖包打包后运行缺失
- **Packer**：命名空间包（无 `__init__.py` 的插件包，如 tiktoken_ext）整体
  复制源码并收集其依赖的宿主子模块——修复 tiktoken 等依赖包打包后编码数据
  缺失

## [0.11.0] - 2026-08-13

### 新增

- **Packer**：安装器新增「启动 Packer」复选框（默认勾选，安装完成即启动
  新版本；静默安装跳过）

### 变更

- **Packer**：移除「包含 dghub-sdk」选项——Python 与 Node.js 的所有依赖
  必须在清单中声明
- **Packer**：TypeScript 编译的「Node」统一为「Node.js」命名

## [0.10.0] - 2026-08-13

### 新增

- **Packer**：信息页字段编辑改为右侧内联详情面板——分组与字段的查看/编辑
  移入面板内，移除 JSON 预览与字段/分组编辑对话框；添加分组/字段直接创建并
  自动选中；选中模型统一，分组选中联动选中其第一个字段

### 修复

- **Packer**：切换字段类型时条件行即时显隐；删除字段后写回磁盘
- **Packer**：构建页规则添加改为对话框，修复输入行与按钮行重叠

### 变更

- **Packer**：project.json 编译字段收敛为 `compiler` 节；移除 `format_version`
  版本机制与 `no_zip` 配置——v0.x 阶段每次格式变更视为唯一格式，
  不再提供旧结构迁移
- **Packer**：主窗口最小尺寸提升至 1400x1000
- **Packer**：CommandCompiler 配置键 `compile` 更名为 `command`
- **docs**：移除 Packer 使用指南，新增 CLI 文档，含 `.dghub-sdk` 项目结构说明；
  SDK 使用指南精简为功能/API 层

## [0.9.0] - 2026-08-11

### 新增

- **Packer**：构建页「包名」输入框——自定义输出包名，留空默认使用插件目录名
- **Packer**：编译产物条目在打包内容列表置顶显示

### 修复

- **Packer**：placeholder 提示统一修复；DGHub 检测中提示改为黄色

### 变更

- **Packer**：Builder 条目改为 BuilderItem dataclass；类型注解统一 `X | None`；
  清除源码 BOM

## [0.8.0] - 2026-08-09

### 新增

- **SDK**：TypeScript SDK（npm `dghub-sdk`）——Agent / codec / enums / 环境变量
  与 Python 版功能对齐，入口 = `package.json` `main`；单元测试 25 项（node:test）
- **demo**：`tetris-ts` 俄罗斯方块示例（TypeScript + SDL2 窗口 + canvas 渲染），
  与 Python 版功能对齐（Agent 集成 / 配置回调 / 惩罚触发）
- **Packer**：Node 编译体系——按 `package.json` 安装依赖、tsc 编译（可选）、
  SEA 打包自包含 exe

### 修复

- **Packer**：CLI 与调试构建读取 Node 编译配置；TS 项目入口为编译产物时
  校验放宽（由编译生成）；调试构建保留 PyInstaller 与 tsc 增量缓存
- **Packer**：调试页提示按编译系统分层（清单不匹配 > 入口缺失），状态分阶段
  显示（启动 / 构建中 / 运行中）；切换编译系统刷新依赖清单标注
- **发布流水线**：PyPI / npm 发布切换为 Trusted Publishing（OIDC）；npm 版本
  已存在时跳过；修复 provenance 校验（package.json 补 `repository` 字段）

### 变更

- **docs**：SDK 使用指南拆分为 Python / TypeScript 两册（各含完整说明），
  包 README 回归极简（PyPI / npm 展示）

## [0.7.0] - 2026-08-05

### 新增

- **Packer**：应用内更新——启动自动检查 GitHub 最新正式版，下载 / 安装 /
  忽略此版本

### 变更

- **Packer**：移除发布选项「不压缩 (No Zip)」，正式构建固定输出 `.zip` 分发包
  （调试运行仍输出文件夹）

## [0.6.1]

### 新增

- **Packer**：调试页——「调试源码」（uv run 运行入口源码）与「调试运行」
  （构建后在产物内运行）双模式，输出进日志 tab，调试中禁用构建按钮
- **Packer**：设置页新增调试设置（host/port）与「恢复默认」按钮
  （带确认对话框）

### 修复

- **SDK**：连接重试期间 `stop()` 立即响应，退出等待加超时，
  避免 DGHub 未运行时进程卡死

### 变更

- **demo**：tetris 示例 `uv.lock` 入库（依赖锁定）

## [0.6.0]

### 新增

- **SDK**：新增 `plugin_root()` 统一路径 API——模块级函数，返回插件根：
  exe 形态 = exe 所在目录，源码形态 = 调用文件所在目录；支持
  `DGHUB_PLUGIN_DIR` 环境变量注入（约定绝对路径）；显式传参原样返回
  （由调用方负责）
- **SDK**：`Agent.manifest_dir` 三档解析——显式传参（现状语义）→
  `DGHUB_MANIFEST_DIR` 环境变量（Packer 调试注入，约定绝对路径）→
  默认取 `plugin_root()`；修复 exe 插件默认推断指向解包目录的陷阱，
  源码与 exe 形态行为一致

## [0.5.0] - 2026-08-02

### 新增

- **Packer**：两阶段构建管线
  - 阶段 1 compile 编译（显式选择：`(无)` / Python `uv + PyInstaller` /
    自定义命令，编译页按选项整区切换设置）
  - 阶段 2 统一 build 步骤（收集打包内容 + 编译产物树 → 自动生成
    manifest → 打包 zip/文件夹）
- **Packer**：编译系统体系——身份 / 设置字段 / 探测 / 预检 / 校验 /
  推导 / 执行九项能力；「从编译填充」按钮串联探测与推导（probe 建议清单、
  deduce 推导编译产物条目（`<插件名>.exe` + `_internal/`），只填空）
- **Packer**：打包内容显式声明——条目可标 `入口`（恰好一个）；Python 编译产物
  （`<插件名>.exe` + `_internal/`）自动声明为只读条目（构建时从产物树兑现），
  切换编译系统自动刷新；双击条目打开**详情对话框**（完整路径 + 重选文件/目录 + 标签下拉）；
  「从编译填充」按钮左侧绿/黄反馈标签
- **Packer**：外观模式默认深色，选项中文化（跟随系统 / 浅色 / 深色）
- **Packer**：**条目级与区域级错误高亮**——校验失败的条目行红框红字（含无编译时
  入口缺失提前拦截）、打包内容区域容器红框 + 错误提示；内容修改即时清除、
  tab 标题高亮联动消除
- **Packer**：编译页 PyInstaller 状态指示（绿色 `PyInstaller installed` /
  红色 `PyInstaller required`，后台线程预检）
- **Packer**：`dgpacker-cli` 收敛为 **build-only 只读 CLI**——唯一 `build` 命令，
  读 `.dghub-sdk/` 构建出包，退出码 0/2/3/4/130；面向 CI，不提供配置命令
  （配置由 GUI 生成并建议提交版本化）

### 变更

- **Packer**：编译字段命名为 **compile**（编译命令）与 **compile_dir**
  （执行目录）；编译系统接口契约明确为九项能力（身份 / 设置字段 /
  探测 / 预检 / 校验 / 推导 / 执行）
- **Packer**：编译入口（entry）从 `project.json` 移除——Python 编译入口由
  `pyproject.toml [tool.dghub].entry` 现读，不入配置（构建页入口输入框同步移除）
- **Packer**：打包内容列表 UI 重构——原生文件/目录选择器（双按钮）、卡片式
  斑马纹行、hover 高亮、类型后缀标识（目录尾部 `/`）、入口徽章位于文件名右侧
- **Packer**：Python 编译仅接受 `pyproject.toml` 作为依赖清单
  （唯一可声明编译入口 `[tool.dghub].entry` 的清单；
  `requirements.txt` / `setup.py` 等不再支持）
- **Packer**：构建根统一为插件目录（移除 `source_dir` 字段
  与「项目根」选择 UI——各种来源的文件/产物在插件目录下天然共存）
- **Packer**：对话框统一——居中于主窗口并限制边界、按钮「确定左 / 取消右」、
  下拉全部只读（不可输入）
- **Packer**：编译 tab 执行目录重置按钮默认隐藏且保持列宽（布局不跳动）

### 修复

- Packer `project.json` 读取容忍 UTF-8 BOM（Windows 编辑器写入 BOM 不再导致
  配置静默回退默认值）
- Packer 设置页过时说明：「打包依赖到 `vendor/`」→
  「打包依赖（uv 下载）」

## [0.4.0] - 2026-07-31

### 新增

- **Packer**：新增命令行界面（CLI），面向脚本 / CI / 自动化场景，与 GUI 共用
  同一构建内核、同以 `.dghub-sdk/` 为项目数据源。命令：`build`（读项目构建）、
  `validate`（仅校验）、`init`（初始化项目，按 `pyproject.toml` 智能探测构建系统）、
  `apply`（应用 `packer-input.json`）、`export`（导出）；全局 `-V/--version`、
  `--no-color`、`-v/--verbose`、`-q/--quiet`；`Ctrl+C` 终止子进程树
- **Packer**：`packer-input.json`「输入清单」（纯 JSON）——无 GUI 地配置项目，
  按 GUI 输入语义回放落盘到 `.dghub-sdk/`（`apply` 要求项目已存在，不自动 init）；
  `apply` 打印本次**实际更新**的字段（仅变化项；把字段重置为默认因异于原值同样计为变化）
- **构建与分发**：`build.py`（取代 `build_exe.py`）一步完成「源码 → onedir → Inno Setup 安装器」；
  GUI 与 CLI 共享一份 Python 运行时（onedir + `MERGE`，无每次启动解压 → 启动更快、去重）。
  产出每用户安装器 `dghub-sdk-packer-setup.exe`：装到 `%LocalAppData%\dghub-sdk-packer`、
  将安装目录加入用户 PATH（控制台命令 `dgpacker`）、建开始菜单「DGHub SDK Packer」（GUI）与卸载器。
  exe：`dgpacker-gui.exe`（GUI）/ `dgpacker.exe`（CLI）。Release 附安装器

### 变更

- **Packer（内部）**：源码重构为 `backend` / `gui` / `cli` 三层——后端纯逻辑内核
  （禁 import customtkinter）、GUI 前端、CLI 前端，依赖单向（前端 → 后端），
  GUI/CLI 各有独立入口（`gui/main.py` / `cli/main.py`）各自打包为一个 exe
- **Packer（内部）**：从 `app` 抽出构建编排（`backend/build_runner`）、打包
  （`backend/packaging`）、全局状态（`backend/settings_store`）；去重共享组件
  （`_ToolTip` / 输入框边框复位 → `gui/widgets`，`_NO_WINDOW` → `backend/winflags`）
- **分发方式变更**：从「下载单个 exe」改为「安装器」——Packer 现须安装后使用（不再提供便携 exe/zip）
- **构建版本解析**：`build.py` 版本取值优先级 `--version`（须 SemVer）> `CI_VERSION_TAG` > `"No Version"`；不再从本地 git tag 猜测（发布 tag 在 main 合并提交上、本地报旧版本号会误导），本地未指定版本的构建显示 `No Version`

## [0.3.0] - 2026-07-30

### 新增

- **Packer**：构建选项「包含 dghub-sdk」在非 exe 模式下也生效——将本地
  dghub-sdk 复制进 `vendor/`；exe 与非 exe 模式均遵循「清单优先」，若依赖
  清单已声明 dghub-sdk 则以清单版为准并跳过本地注入（避免版本撞车）
- **Packer**：uv 依赖清单支持 `pyproject.toml` / `setup.py` / `setup.cfg` /
  `requirements*.txt`，文件选择对话框按这些格式过滤；依赖来源面板三态显示
  （绿色已选 / 黄色未选 / 浅红未知格式），未知格式在构建校验时拦截
- **Packer**：构建日志分级着色——错误（红）/ 警告（橙）/ 成功（绿）三色，
  其余为默认色；外部工具（uv / PyInstaller 等）输出以「来源分隔块」成段展示；
  日志页新增「清空」按钮
- **Packer**：支持**取消构建**——构建期间「开始构建」按钮变为「取消构建」，
  二次确认后立即终止正在运行的命令（pre-build / 依赖安装 / 打包，含子进程树，
  Windows 用 `taskkill /T`）；取消后仅清理输出目录内的中间产物；关闭窗口时若
  构建进行中会先终止子进程再退出，不残留进程

### 变更

- **Packer**：「发布」标签页更名为「构建」（内容为构建配置，与底部
  「构建」按钮呼应；"发布目标"选项名不变）；底部按钮文案改为
  「开始构建 / 正在构建」
- **Packer**：构建系统说明文案移至顶部栏选择器右侧（原在构建页内）
- **发布流程**：GitHub Release 标题精简为版本号（如 `v0.3.0`）；正文不再
  附加自动生成的「What's Changed」（其仅统计 PR，对本项目直推发布流无效），
  内容完全由本文件对应版本段落提供
- **Packer**：构建不再自动清空日志——改为保留历史，每次构建前插入
  `━━━ 构建 时间 ━━━` 分隔行；仅最终产物（zip / 文件夹）标记为成功绿，
  校验通过、依赖打包、exe 构建等中间步骤为普通信息
- **Packer**：目录显示区移除路径悬停提示（tooltip），超长路径仍截断显示
- **Packer**：构建期间锁定构建系统选择器、目录选择与信息/构建页编辑，
  避免中途改动导致状态不一致
- **Packer（内部）**：日志改为结构化分级（调用点显式声明级别，不再解析文本
  前缀）；移除遗留死代码 `vendor_packer`（系统 Python 定位函数并入 `exe_builder`）

### 修复

- Packer exe 构建入口未同步构建页配置的 entry（`src/` 布局下曾误用插件根
  的 `main.py` 导致构建失败）
- Packer 构建页入口文件输入框与上下行左边界未对齐（标签列缺 5px 间距）
- Packer 错误高亮生命周期：修正字段错误的输入框在清除时未恢复默认灰边（曾被
  抹成无边框）；修正字段修正后 tab 标题高亮与「构建失败」状态标签不消除的问题；
  校验改为一次点击检测所有必填项（原先逐个暴露、修一个冒一个）
- Packer 默认输出目录标签在构建开始时误从灰字变为正常深色，现按自动/手动状态
  保持正确颜色
- 修正 Packer 文档中过时的信息：manifest 口径统一为**构建时自动生成**
  （移除"编辑 manifest"表述）；插件目录不再要求预先存在 `manifest.json`
  （任意文件夹首次选择即初始化）；信息页字段列表与实际一致（entry 移至
  构建页按构建系统配置）；补充日志页说明；README 功能列表同步
- Packer 部分警告（清单已含 dghub-sdk、未选清单跳过依赖、glob 规则无匹配）
  此前未着色或被误标为「提示」，现统一归为警告；移除 exe 构建后过时的
  「手动修改 manifest entry」提示（产物 manifest 已自动写入 entry）

## [0.2.1] - 2026-07-29

### 修复

- 修正 README 中过时的信息：SDK 快速示例补充 `wait_ready()` 调用
  （0.2.0 起 `with Agent()` 不再自动等待握手）；Packer 功能列表更新为
  构建系统驱动模型（多构建系统、依赖由项目清单声明），移除已废弃的
  「依赖打包」旧描述；补充 SDK 的 PyPI 安装说明

## [0.2.0] - 2026-07-29

### ⚠️ 破坏性变更

- **SDK**：`Agent.wait()` 重命名为 `wait_threading_exit()`。直接调用
  `wait()` 会触发 `AttributeError`，请改名调用；使用 `with` 语句的插件
  不受影响（`__exit__` 内部已适配）
- **Packer**：发布工作流重构为「构建系统驱动」——顶部栏选择构建系统
  （`Python - uv` / `(无构建系统)`），Dependency 标签页移除，依赖改由
  项目自身清单（pyproject.toml / requirements.txt）管理；
  `.dghub-sdk/project.json` 结构升级为按系统命名空间存储

### 新增

- **SDK**：SDK 1.1 / V4 设备兼容——`DeviceType.V4`；`trigger` / `event` /
  `pulse` / `set_strength` / `adjust_strength` 新增可选字段
  （`target_id`、`cause`、`pulse_name`、`name`、`from_pct`、`to_pct`、
  `delta_pct`），未传时不序列化，向后兼容（感谢 @Kobop1）
- **SDK**：新增 `Agent.wait_ready(timeout)`（阻塞等待握手，失败抛出异常
  由调用方决策）与 `Agent.is_ready()`（非阻塞单次就绪检查）
- **SDK**：测试套件（codec / agent 生命周期 / 消息字段，CI 自动运行）
- **Packer**：构建系统架构（`build_systems.py`），配置按系统独立记忆：
  - `Python - uv` — 清单驱动 vendor、`[tool.dghub].entry` 自动填充、
    可选 PyInstaller exe
  - `(无构建系统)` — 收集目录（产物根）+ pre-build 命令（可独立指定
    执行目录，默认插件目录）+ 附加文件精确/glob 规则收集
- **Packer**：设置页新增「PyPI 镜像源」选项（预置清华/阿里云/中科大），
  vendor 依赖打包时注入 `UV_DEFAULT_INDEX`，全局持久化
- **Packer**：逻辑层测试套件（43 项，CI 在 Windows 运行）

### 变更

- **SDK**：`with Agent(...)` 进入时不再等待握手（保持非阻塞语义），
  需在首次 `poll()` / 发送前显式调用 `wait_ready()`；快速开始示例与
  demo/tetris 已同步更新
- **Packer**：自身依赖管理由 pip + requirements.txt 迁移至 uv
  （pyproject.toml + uv.lock），源码运行命令改为
  `uv sync --project packer` + `uv run --project packer ...`
- **发布流程**：SDK 仅通过 PyPI 分发，GitHub Release 附件不再包含
  wheel；CI 检测 `sdk/python` 无变更时自动跳过 SDK 构建与 PyPI 发布
- demo/tetris 适配新 API 与 uv 项目结构（src 布局 + pyproject.toml）

### 修复

- 后台发送/关闭异常现在会进入 `get_exception()` 队列，不再静默丢失
- Packer 全局状态文件（state.json）改为读-改-写合并，修复设置项互相
  覆盖的问题

## [0.1.3] - 2026-07-27

历史版本，详见 [Releases](https://github.com/curtainsmall/dghub-sdk-toolkit/releases)。
