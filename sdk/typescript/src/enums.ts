/**
 * DGHub SDK 全局使用的枚举类型。
 * 与 Python SDK 的 `dghub_sdk.enums` 一一对应（值完全相同）。
 */

/** WebSocket 协议操作码（客户端 <-> 服务端消息类型）。 */
export enum OpCode {
  // 客户端 -> 服务端
  HELLO = "hello",
  TRIGGER = "trigger",
  EVENT = "event",
  PULSE = "pulse",
  SET_STRENGTH = "set_strength",
  ADJUST_STRENGTH = "adjust_strength",
  STATUS = "status",
  LOG = "log",
  SET_CONFIG = "set_config",
  // 服务端 -> 客户端
  HELLO_ACK = "hello_ack",
  CONFIG = "config",
  CONFIG_CHANGED = "config_changed",
  DEVICE_INFO = "device_info",
  STOP = "stop",
  PING = "ping",
  PONG = "pong",
}

/** 强度/波形指令的目标设备通道。 */
export enum Channel {
  A = "a",
  B = "b",
  BOTH = "both",
}

/** 触发动作类型 —— 指定作用于设备的哪些方面。 */
export enum Action {
  /** 同时作用于强度和波形。 */
  BOTH = "both",
  /** 仅作用于强度。 */
  STRENGTH = "strength",
  /** 仅作用于波形。 */
  WAVEFORM = "waveform",
}

/**
 * 触发对 baseline 强度的作用方式。
 * ROLLBACK：临时偏移强度，持续时间结束后自动恢复。
 * PERMANENT：永久偏移 baseline（持久化到配置）。
 */
export enum StrengthMode {
  ROLLBACK = "rollback",
  PERMANENT = "permanent",
}

/** sendLog 消息的日志级别。 */
export enum LogLevel {
  DEBUG = "debug",
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
}

/** 通过 sendStatus 上报的启动检查状态值。 */
export enum CheckState {
  /** 尚未开始或无数据。 */
  IDLE = "idle",
  /** 检查进行中。 */
  PENDING = "pending",
  /** 检查通过。 */
  OK = "ok",
  /** 检查完成但有警告。 */
  WARN = "warn",
  /** 检查失败。 */
  FAIL = "fail",
}

/** 当前连接的 DGLab 设备硬件版本。 */
export enum DeviceType {
  V2 = "v2",
  V3 = "v3",
  V4 = "v4",
  UNKNOWN = "",
}

/**
 * Agent 可订阅的事件名（Node EventEmitter 事件，字符串值即事件名）。
 * 事件名集合封闭：`agent.on(AgentEvent.X, ...)` 拼错成员名会在编译期报错。
 */
export enum AgentEvent {
  /** 握手成功（hello_ack）。 */
  Ready = "ready",
  /** 握手后服务端推送一次全量配置。 */
  Config = "config",
  /** 单个配置项变更。 */
  ConfigChanged = "configChanged",
  /** 设备状态变化。 */
  DeviceInfo = "deviceInfo",
  /** 服务端要求插件停止。 */
  Stop = "stop",
  /** 服务端 ping（SDK 自动回 pong）。 */
  Ping = "ping",
  /** 连接/解析/发送错误。按 Node 惯例，无人订阅时抛出。 */
  Error = "error",
}
