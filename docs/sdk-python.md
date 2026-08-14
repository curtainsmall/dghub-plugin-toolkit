# DGHub SDK Python 使用指南

社区 Python SDK（`dghub_sdk`），为 DGHub 插件提供同步风格的 WebSocket 通信封装。
协议字段定义见 [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [插件根目录与资源文件](#插件根目录与资源文件)
- [配置监听](#配置监听)
- [强度触发](#强度触发)
- [状态上报](#状态上报)
- [错误处理](#错误处理)
- [手动接入（调试）](#手动接入调试)
- [附录：插件入口声明](#附录插件入口声明)

---

## 安装

```bash
pip install dghub-sdk
# uv 管理的项目可 uv add dghub-sdk
```

依赖：Python 3.11+、`websockets`（自动安装）。

## 快速开始

```python
import dghub_sdk

running = True

def on_stop(reason: str) -> None:
    global running
    running = False

with dghub_sdk.Agent(on_stop=on_stop) as agent:
    agent.wait_ready(timeout=10)   # 等待握手完成
    while running:
        agent.poll()
        # 你的游戏 / 业务逻辑
```

`Agent` 关键 API：

| API | 用途 |
|-----|------|
| `Agent(on_stop=..., on_config=..., on_config_changed=..., manifest_dir=...)` | 构造；`with` 自动连接/断开 |
| `start()` | 启动连接（不等待握手） |
| `wait_ready(timeout)` | 阻塞等待握手完成；失败直接抛出 |
| `is_ready()` | 非阻塞检查是否就绪 |
| `poll(timeout=None)` | 取出收到的消息并触发回调（默认非阻塞） |
| `get_exception()` | 读取后台异常（见[错误处理](#错误处理)） |
| `wait_threading_exit()` | 等待后台线程退出（`__exit__` 自动调用） |

## 插件根目录与资源文件

`dghub_sdk.plugin_root()` 返回插件根目录（`DGHUB_PLUGIN_ROOT` 环境变量优先）：

```python
icon = dghub_sdk.plugin_root() / "assets" / "icon.png"   # 资源统一相对插件根
```

`Agent.manifest_dir` 解析：显式传入（相对以调用方文件目录为基准）> 环境变量
`DGHUB_MANIFEST_DIR`（Packer 调试注入）> 缺省 `plugin_root()`。手动运行源码且
插件根无 manifest.json 时握手会报 `FileNotFoundError`（manifest 是构建产物）。

## 配置监听

| 回调 | 触发时机 | 签名 |
|------|----------|------|
| `on_config` | 握手完成后，推送全量配置 | `(config: dict[str, Any]) -> None` |
| `on_config_changed` | 用户在前端修改单个字段 | `(key: str, value: Any) -> None` |

```python
config: dict[str, Any] = {}

def on_config(cfg):
    config.update(cfg)

def on_config_changed(key, value):
    config[key] = value

with dghub_sdk.Agent(on_config=on_config,
                     on_config_changed=on_config_changed) as agent:
    ...
```

`config` 语义边界：

- 是当前插件 ID 下的配置值快照（含 `set_config` 写入的自定义字段与
  `target_id`、`idle_strength` 等公开字段），不是 `config_schema`
- `config_schema.default` 不保证出现在 `config` 中——插件应以 schema 默认值兜底
- `enabled` 与 `_` 开头内部字段不下发；`target_id` 由 DGHub 管理，插件不能修改
- 握手后全量一次，之后用户修改推送单字段；`set_config` 发送后不回推
  `config_changed`——插件需自行同步本地缓存

## 强度触发

`send_trigger` 一条调用同时控制强度、波形、通道：

```python
def send_trigger(
    self,
    action: Action = Action.BOTH,
    delta_pct: int = 0,
    strength_mode: StrengthMode = StrengthMode.ROLLBACK,
    duration_s: float = 1.0,
    preset: str = "",
    channel: Channel = Channel.BOTH,
    label: str | None = None,
    username: str | None = None,
    name: str | None = None,
    cause: str | None = None,
    pulse_name: str | None = None,
    target_id: str | None = None,
) -> None: ...
```

三种典型用法：

```python
# Rollback：强度临时偏移 baseline，duration 后自动回正
agent.send_trigger(action=dghub_sdk.Action.BOTH, delta_pct=50,
                   strength_mode=dghub_sdk.StrengthMode.ROLLBACK,
                   duration_s=1.5, preset="CS2-受伤", label="受击")

# Permanent：永久修改 baseline
agent.send_trigger(action=dghub_sdk.Action.STRENGTH, delta_pct=10,
                   strength_mode=dghub_sdk.StrengthMode.PERMANENT)

# 仅波形：不改强度，只播放触感反馈
agent.send_trigger(action=dghub_sdk.Action.WAVEFORM,
                   preset="振动-短", duration_s=0.5)
```

其他发送方法：`send_event()`（支持 `from_pct`/`to_pct`/`delta_pct` 事件信息）、
`send_pulse()`、`send_set_strength()`、`send_adjust_strength()`。

`name`/`cause`/`pulse_name` 补充事件内容、原因与波形名。V4 多设备：
`on_device_info` 收到 `DeviceType.V4`；省略 `target_id` 时使用插件默认目标，
仅需发给另一台 V4 设备时传消息级 `target_id`（V2/V3 与旧调用不受影响；
`target_id` 由 DGHub 管理，勿用 `send_set_config()` 修改）。

## 状态上报

| API | 用途 |
|-----|------|
| `send_startup_check(key, label, state, detail="", display_status="", dont_send=False)` | 启动检查步骤；`state` 取值 `CheckState`：idle/pending/ok/warn/fail；`dont_send=True` 只登记不发送，最后一次不带该参数触发发送；面板标题由 `set_startup_check_title()` 设置 |
| `send_display_status(text)` | 显示状态 |
| `send_status_field(key, value)` | 单字段上报 |
| `send_status(fields: dict)` | 底层 API（以上方法均基于它） |

```python
agent.send_startup_check("game", "游戏连接", CheckState.OK, detail="已连接")
agent.send_display_status("运行中")
agent.send_status_field("tick", 42)
```

## 错误处理

后台异常被收集，主循环中检查：

```python
while running:
    agent.poll()
    while exc := agent.get_exception():
        print(f"[错误] {exc}")
```

## 手动接入（调试）

DGHub 正常会自动启动插件进程并注入环境变量；手动调试时自行设置：

```bash
set DGHUB_HOST=127.0.0.1
set DGHUB_PORT=27020
set DGHUB_TOKEN=<从 GET /api/plugins/_session_token 获取>
python main.py
```

或代码中临时 patch：`os.environ["DGHUB_HOST"] / ["DGHUB_PORT"] / ["DGHUB_TOKEN"]`。

## 附录：插件入口声明

Python 插件入口由 `pyproject.toml` 的 `[tool.dghub].entry` 声明（相对清单文件所在目录）。该声明仅供 Packer 使用（构建与调试源码时读取），SDK 运行时不需要：

```toml
[tool.dghub]
entry = "src/main.py"
```

---

## 更多

- 完整协议字段定义：[PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)
- API 签名与参数说明：源码中的 Google-style docstrings
