# DGHub SDK TypeScript 使用指南

社区 TypeScript SDK（npm `dghub-sdk`），为 DGHub 插件提供 WebSocket 通信封装。
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
- [构建与测试](#构建与测试)
- [附录：插件入口声明](#附录插件入口声明)

---

## 安装

```bash
npm install dghub-sdk
```

依赖：Node.js 24+（TypeScript 原生执行与 SEA 打包要求）、`ws`（自动安装）。

## 快速开始

```ts
import { Agent, AgentEvent } from "dghub-sdk";

const agent = new Agent();
agent.on(AgentEvent.Stop, (reason) => {
  console.log(`服务端要求停止：${reason}`);
});
agent.start();
await agent.waitReady(10);   // 等待握手完成
// 之后无需手动 poll：消息到达即触发事件
```

`Agent` 关键 API：

| API | 用途 |
|-----|------|
| `new Agent({ onStop, onConfig, onConfigChanged, manifestDir })` | 构造；`on*` 回调等价于对应事件注册 |
| `agent.on(AgentEvent.X, listener)` / `once` / `off` | 订阅 / 退订事件（事件名集合封闭，参数随事件名类型检查） |
| `start()` | 启动连接（不等待握手） |
| `waitReady(timeout)` | 等待握手完成；失败 Promise 拒绝 |
| `waitForClose()` | 等待连接循环结束（ws 关闭后 resolve） |
| `isReady()` | 非阻塞检查是否就绪 |

### 事件一览

| 事件 | 触发时机 | 监听器签名 |
|------|----------|-----------|
| `AgentEvent.Ready` | 握手成功（hello_ack） | `(data: Record<string, unknown>) => void` |
| `AgentEvent.Config` | 握手后推送全量配置 | `(config: Record<string, unknown>) => void` |
| `AgentEvent.ConfigChanged` | 用户修改单个配置字段 | `(key: string, value: boolean \| number \| string) => void` |
| `AgentEvent.DeviceInfo` | 设备状态变化 | `(connected: boolean, deviceType: DeviceType, maxA: number, maxB: number) => void` |
| `AgentEvent.Stop` | 服务端要求插件停止 | `(reason: string) => void` |
| `AgentEvent.Ping` | 服务端 ping（SDK 自动回 pong） | `(t: number) => void` |
| `AgentEvent.Error` | 连接 / 解析 / 发送错误 | `(err: Error) => void` |

事件名是具名常量（`AgentEvent` 枚举），拼错成员名在编译期报错。

## 插件根目录与资源文件

`pluginRoot()` 返回插件根目录（`DGHUB_PLUGIN_ROOT` 环境变量优先）：

```ts
import { pluginRoot } from "dghub-sdk";
import { join } from "node:path";

const icon = join(pluginRoot(), "assets", "icon.png");   // 资源统一相对插件根
```

`manifestDir` 构造参数解析：显式传入（相对以调用方文件目录为基准）>
环境变量 `DGHUB_MANIFEST_DIR`（Packer 调试注入）> 缺省 `pluginRoot()`。
手动运行源码且插件根无 manifest.json 时握手失败（manifest 是构建产物）。

## 配置监听

| 事件 | 触发时机 | 签名 |
|------|----------|------|
| `AgentEvent.Config` | 握手完成后，推送全量配置 | `(config: Record<string, unknown>) => void` |
| `AgentEvent.ConfigChanged` | 用户在前端修改单个字段 | `(key: string, value: boolean \| number \| string) => void` |

```ts
const config: Record<string, unknown> = {};

const agent = new Agent();
agent.on(AgentEvent.Config, (cfg) => { Object.assign(config, cfg); });
agent.on(AgentEvent.ConfigChanged, (key, value) => { config[key] = value; });
agent.start();
await agent.waitReady(10);
```

`config` 语义边界：

- 是当前插件 ID 下的配置值快照（含 `sendSetConfig` 写入的自定义字段与
  `target_id`、`idle_strength` 等公开字段），不是 `config_schema`
- `config_schema.default` 不保证出现在 `config` 中——插件应以 schema 默认值兜底
- `enabled` 与 `_` 开头内部字段不下发；`target_id` 由 DGHub 管理，插件不能修改
- 握手后全量一次，之后用户修改推送单字段；`sendSetConfig` 发送后不回推
  `configChanged`——插件需自行同步本地缓存

## 强度触发

`sendTrigger` 一条调用同时控制强度、波形、通道：

```ts
agent.sendTrigger({
  action: Action.BOTH,                 // 默认 "both"
  deltaPct: 0,                         // 默认 0
  strengthMode: StrengthMode.ROLLBACK, // 默认 "rollback"
  durationS: 1.0,                      // 默认 1.0
  preset: "",                          // 含波形时必填
  channel: Channel.BOTH,               // 默认 "both"
  label: "受击",
  username: "player",
  name: "BOSS 守卫",
  cause: "强度值下降",
  pulseName: "脉冲",
  targetId: "target-1",
});
```

三种典型用法：

```ts
// Rollback：强度临时偏移 baseline，duration 后自动回正
agent.sendTrigger({ action: Action.BOTH, deltaPct: 50,
  strengthMode: StrengthMode.ROLLBACK, durationS: 1.5,
  preset: "CS2-受伤", label: "受击" });

// Permanent：永久修改 baseline
agent.sendTrigger({ action: Action.STRENGTH, deltaPct: 10,
  strengthMode: StrengthMode.PERMANENT });

// 仅波形：不改强度，只播放触感反馈
agent.sendTrigger({ action: Action.WAVEFORM, preset: "振动-短", durationS: 0.5 });
```

其他发送方法：`sendEvent()`（支持 `fromPct`/`toPct`/`deltaPct` 事件信息）、
`sendPulse()`、`sendSetStrength()`、`sendAdjustStrength()`。

`name`/`cause`/`pulseName` 补充事件内容、原因与波形名。V4 多设备：
`AgentEvent.DeviceInfo` 收到 `DeviceType.V4`；省略 `targetId` 时使用插件默认目标，
仅需发给另一台 V4 设备时传消息级 `targetId`（V2/V3 与旧调用不受影响；
`targetId` 由 DGHub 管理，勿用 `sendSetConfig()` 修改）。

## 状态上报

| API | 用途 |
|-----|------|
| `sendStartupCheck(key, label, state, { detail?, displayStatus?, dontSend? })` | 启动检查步骤；`state` 取值 `CheckState`：idle/pending/ok/warn/fail；`dontSend: true` 只登记不发送，最后一次不带该参数触发发送；面板标题由 `setStartupCheckTitle()` 设置 |
| `sendDisplayStatus(text)` | 显示状态 |
| `sendStatusField(key, value)` | 单字段上报 |
| `sendStatus(fields)` | 底层 API（以上方法均基于它） |

```ts
agent.sendStartupCheck("game", "游戏连接", CheckState.OK, { detail: "已连接" });
agent.sendDisplayStatus("运行中");
agent.sendStatusField("tick", 42);
```

## 错误处理

连接 / 解析 / 发送错误统一通过 `AgentEvent.Error` 事件上报：

```ts
const agent = new Agent();
agent.on(AgentEvent.Error, (err) => {
  console.error(`[SDK 错误] ${err}`);
});
```

> 按 Node 惯例（EventEmitter），**Error 事件无人订阅时会直接抛出**（进程崩溃）。
> 插件应始终订阅 `AgentEvent.Error`。

启动阶段的错误（manifest 缺失、token 未设置、握手失败）同时会让
`waitReady()` 的 Promise 拒绝——二选一处理即可，避免重复上报。

## 手动接入（调试）

DGHub 正常会自动启动插件进程并注入环境变量；手动调试时自行设置：

```bash
set DGHUB_HOST=127.0.0.1
set DGHUB_PORT=27020
set DGHUB_TOKEN=<从 GET /api/plugins/_session_token 获取>
node dist/main.js
```

## 构建与测试

```bash
cd sdk/typescript
npm install
npm run build     # tsc 编译到 dist/
npm test          # node:test 单元测试
```

## 附录：插件入口声明

TypeScript 插件入口由 `package.json` 的 `main` 字段声明。该声明仅供 Packer 使用（构建与调试源码时读取），SDK 运行时不需要：

```json
{ "main": "dist/main.js" }
```

---

## 更多

- 完整协议字段定义：[PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)
- API 签名与参数说明：源码中的 docstrings
