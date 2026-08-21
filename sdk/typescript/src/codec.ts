/**
 * 消息类型与编解码器（序列化 / 反序列化）。
 * 与 Python SDK 的 `dghub_sdk.codec` 一一对应（协议完全一致）。
 */

import { Action, Channel, DeviceType, LogLevel, OpCode, StrengthMode } from "./enums.js";

/** `Codec.parse()` 的类型化结果。通过 `.op` 判断哪些字段有值。 */
export interface CodecMessage {
  op: OpCode;
  // hello_ack
  status?: string;
  // config
  data?: Record<string, unknown>;
  // config_changed
  key?: string;
  value?: boolean | number | string;
  // device_info
  connected?: boolean;
  deviceType?: DeviceType;
  maxStrengthA?: number;
  maxStrengthB?: number;
  // stop
  reason?: string;
  // ping
  t?: number;
}

/** trigger 消息参数（对应 Python `Codec.trigger` 的命名参数）。 */
export interface TriggerOptions {
  action?: Action;
  deltaPct?: number;
  strengthMode?: StrengthMode;
  durationS?: number;
  preset?: string;
  channel?: Channel;
  label?: string | null;
  username?: string | null;
  name?: string | null;
  cause?: string | null;
  pulseName?: string | null;
  targetId?: string | null;
}

/** event 消息参数（对应 Python `Codec.event` 的命名参数）。 */
export interface EventOptions {
  username?: string | null;
  strengthPct?: number | null;
  duration?: number;
  eventId?: string | null;
  cause?: string | null;
  pulseName?: string | null;
  fromPct?: number | null;
  toPct?: number | null;
  deltaPct?: number | null;
  targetId?: string | null;
}

function putIfNotNull(msg: Record<string, unknown>, key: string, value: unknown): void {
  if (value !== null && value !== undefined) {
    msg[key] = value;
  }
}

/** 所有消息编解码的命名空间类，无需实例化。 */
export class Codec {
  /** 构建 hello 握手消息。 */
  static hello(token: string, manifest: Record<string, unknown>): string {
    if (!token) {
      throw new Error("token is required");
    }
    if (typeof manifest !== "object" || manifest === null) {
      throw new TypeError("manifest must be an object");
    }
    return JSON.stringify({ op: OpCode.HELLO, token, manifest });
  }

  /** 构建统一触发消息。action 包含波形（BOTH / WAVEFORM）且 preset 为空时抛错。 */
  static trigger(options: TriggerOptions = {}): string {
    const action = options.action ?? Action.BOTH;
    if ((action === Action.BOTH || action === Action.WAVEFORM) && !options.preset) {
      throw new Error("preset is required when action includes waveform");
    }
    const msg: Record<string, unknown> = {
      op: OpCode.TRIGGER,
      action: action,
      delta_pct: options.deltaPct ?? 0,
      strength_mode: options.strengthMode ?? StrengthMode.ROLLBACK,
      duration_s: options.durationS ?? 1.0,
      preset: options.preset ?? "",
      channel: options.channel ?? Channel.BOTH,
    };
    putIfNotNull(msg, "label", options.label);
    putIfNotNull(msg, "username", options.username);
    putIfNotNull(msg, "name", options.name);
    putIfNotNull(msg, "cause", options.cause);
    putIfNotNull(msg, "pulse_name", options.pulseName);
    putIfNotNull(msg, "target_id", options.targetId);
    return JSON.stringify(msg);
  }

  /** 构建一次性事件消息。 */
  static event(label: string, name: string, options: EventOptions = {}): string {
    if (!label) {
      throw new Error("label is required");
    }
    if (!name) {
      throw new Error("name is required");
    }
    const msg: Record<string, unknown> = {
      op: OpCode.EVENT,
      label,
      name,
      duration: options.duration ?? 1.0,
    };
    putIfNotNull(msg, "username", options.username);
    putIfNotNull(msg, "strength_pct", options.strengthPct);
    putIfNotNull(msg, "event_id", options.eventId);
    putIfNotNull(msg, "cause", options.cause);
    putIfNotNull(msg, "pulse_name", options.pulseName);
    putIfNotNull(msg, "from_pct", options.fromPct);
    putIfNotNull(msg, "to_pct", options.toPct);
    putIfNotNull(msg, "delta_pct", options.deltaPct);
    putIfNotNull(msg, "target_id", options.targetId);
    return JSON.stringify(msg);
  }

  /** 构建仅波形的脉冲消息。 */
  static pulse(preset: string, channel: Channel = Channel.BOTH, targetId?: string | null): string {
    if (!preset) {
      throw new Error("preset is required");
    }
    const msg: Record<string, unknown> = { op: OpCode.PULSE, preset, channel };
    putIfNotNull(msg, "target_id", targetId);
    return JSON.stringify(msg);
  }

  /** 构建 set_strength 消息。 */
  static setStrength(channel: Channel, pct: number, targetId?: string | null): string {
    if (!Number.isInteger(pct) || pct < 0 || pct > 100) {
      throw new Error("pct must be 0-100");
    }
    const msg: Record<string, unknown> = { op: OpCode.SET_STRENGTH, channel, pct };
    putIfNotNull(msg, "target_id", targetId);
    return JSON.stringify(msg);
  }

  /** 构建 adjust_strength 消息。 */
  static adjustStrength(channel: Channel, deltaPct: number, targetId?: string | null): string {
    if (!Number.isInteger(deltaPct) || deltaPct < -100 || deltaPct > 100) {
      throw new Error("delta_pct must be -100 to 100");
    }
    const msg: Record<string, unknown> = { op: OpCode.ADJUST_STRENGTH, channel, delta_pct: deltaPct };
    putIfNotNull(msg, "target_id", targetId);
    return JSON.stringify(msg);
  }

  /** 构建状态上报消息。 */
  static status(fields: Record<string, unknown>): string {
    if (typeof fields !== "object" || fields === null) {
      throw new TypeError("fields must be an object");
    }
    return JSON.stringify({ op: OpCode.STATUS, fields });
  }

  /** 构建日志消息。 */
  static log(level: LogLevel, message: string): string {
    return JSON.stringify({ op: OpCode.LOG, level, message });
  }

  /** 构建 set_config 消息，用于持久化运行时数据。 */
  static setConfig(key: string, value: unknown): string {
    return JSON.stringify({ op: OpCode.SET_CONFIG, key, value });
  }

  /** 将 JSON 字符串解析为类型化的 CodecMessage。 */
  static parse(raw: string): CodecMessage {
    const data = JSON.parse(raw) as Record<string, unknown>;
    const op = data.op as string;
    switch (op) {
      case OpCode.HELLO_ACK: {
        const fields: Record<string, unknown> = { ...data };
        delete fields.op;
        return { op: OpCode.HELLO_ACK, data: fields };
      }
      case OpCode.CONFIG:
        return { op: OpCode.CONFIG, data: (data.data ?? {}) as Record<string, unknown> };
      case OpCode.CONFIG_CHANGED:
        return { op: OpCode.CONFIG_CHANGED, key: data.key as string, value: data.value as boolean | number | string };
      case OpCode.DEVICE_INFO:
        return {
          op: OpCode.DEVICE_INFO,
          connected: data.connected as boolean,
          deviceType: DeviceType[(data.device_type as string)?.toUpperCase() as keyof typeof DeviceType] ?? DeviceType.UNKNOWN,
          maxStrengthA: data.max_strength_a as number,
          maxStrengthB: data.max_strength_b as number,
        };
      case OpCode.PING:
        return { op: OpCode.PING, t: data.t as number };
      case OpCode.STOP:
        return { op: OpCode.STOP, reason: data.reason as string };
      default:
        throw new Error(`Unknown op: ${op}`);
    }
  }

  /** 将 CodecMessage 序列化回 JSON 字符串。 */
  static serialize(msg: CodecMessage): string {
    const data: Record<string, unknown> = { op: msg.op };
    for (const key of [
      "status", "data", "key", "value", "connected",
      "deviceType", "maxStrengthA", "maxStrengthB", "reason", "t",
    ] as const) {
      const val = msg[key];
      if (val !== undefined && val !== null) {
        if (key === "deviceType") {
          data.device_type = (val as DeviceType) || DeviceType.UNKNOWN;
        } else if (key === "maxStrengthA") {
          data.max_strength_a = val;
        } else if (key === "maxStrengthB") {
          data.max_strength_b = val;
        } else {
          data[key] = val;
        }
      }
    }
    return JSON.stringify(data);
  }
}
