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

---

## 安装

```bash
npm install dghub-sdk
```

依赖：Node.js 20+（SEA 打包要求）、`ws`（自动安装）。

## 快速开始

```ts
import { Agent } from "dghub-sdk";

let running = true;

const agent = new Agent({
  onStop: (reason) => { running = false; },
});
agent.start();
await agent.waitReady(10);   // 等待握手完成
while (running) {
  agent.poll();
  // 你的游戏 / 业务逻辑
}
```

`Agent` 关键 API：

| API | 用途 |
|-----|------|
| `new Agent({ onStop, onConfig, onConfigChanged, manifestDir })` | 构造 |
| `start()` | 启动连接（不等待握手） |
| `waitReady(timeout)` | 等待握手完成；失败 Promise 拒绝 |
| `isReady()` | 非阻塞检查是否就绪 |
| `poll(timeout?)` | 取出收到的消息并触发回调（默认非阻塞） |
| `getException()` | 读取后台异常（见[错误处理](#错误处理)） |

## 插件根目录与资源文件

`pluginRoot()` 返回插件根目录（exe 形态 = exe 所在目录；源码形态 =
调用文件所在目录；`DGHUB_PLUGIN_ROOT` 环境变量优先，约定绝对路径）：

```ts
import { pluginRoot } from "dghub-sdk";
import { join } from "node:path";

const icon = join(pluginRoot(), "assets", "icon.png");   // 资源统一相对插件根
```

`manifestDir` 构造参数解析：显式传入（相对以调用方文件目录为基准）>
环境变量 `DGHUB_MANIFEST_DIR`（Packer 调试注入）> 缺省 `pluginRoot()`。
手动运行源码且插件根无 manifest.json 时握手失败（manifest 是构建产物）。

## 配置监听

| 回调 | 触发时机 | 签名 |
|------|----------|------|
| `onConfig` | 握手完成后，推送全量配置 | `(config: Record<string, unknown>) => void` |
| `onConfigChanged` | 用户在前端修改单个字段 | `(key: string, value: boolean \| number \| string) => void` |

```ts
const config: Record<string, unknown> = {};

const agent = new Agent({
  onConfig: (cfg) => { Object.assign(config, cfg); },
  onConfigChanged: (key, value) => { config[key] = value; },
});
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
`onDeviceInfo` 收到 `DeviceType.V4`；省略 `targetId` 时使用插件默认目标，
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

后台连接异常被收集，主循环中检查：

```ts
while (running) {
  agent.poll();
  let exc = agent.getException();
  while (exc !== null) {
    console.error(`[错误] ${exc}`);
    exc = agent.getException();
  }
}
```

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

---

## 更多

- 完整协议字段定义：[PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)
- API 签名与参数说明：源码中的 docstrings
