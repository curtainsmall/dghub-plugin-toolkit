"""消息数据类与编解码器（序列化 / 反序列化）。"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .enums import Action, Channel, DeviceType, LogLevel, OpCode, StrengthMode


# ---------------------------------------------------------------------------
# CodecMessage
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CodecMessage:
    """``Codec.parse()`` 的类型化结果。通过 ``.op`` 判断哪些字段有值。"""
    op: OpCode
    # hello_ack
    status: str | None = None
    # config
    data: dict[str, Any] | None = None
    # config_changed
    key: str | None = None
    value: bool | int | str | None = None
    # device_info
    connected: bool | None = None
    device_type: DeviceType | None = None
    max_strength_a: int | None = None
    max_strength_b: int | None = None
    # stop
    reason: str | None = None
    # ping
    t: float | None = None


# ---------------------------------------------------------------------------
# Codec (namespace class)
# ---------------------------------------------------------------------------


class Codec:
    """所有消息编解码的命名空间类，无需实例化。"""

    @staticmethod
    def hello(token: str, manifest: dict[str, Any]) -> str:
        """构建 hello 握手消息。"""
        if not token:
            raise ValueError("token is required")
        if not isinstance(manifest, dict):
            raise TypeError("manifest must be a dict")
        return json.dumps({
            "op": OpCode.HELLO.value,
            "token": token,
            "manifest": manifest,
        })

    @staticmethod
    def trigger(
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
    ) -> str:
        """构建统一触发消息。

        当 ``action`` 包含波形（Action.BOTH 或 Action.WAVEFORM）且
        ``preset`` 为空时抛出 ``ValueError``。
        """
        if action in (Action.BOTH, Action.WAVEFORM) and not preset:
            raise ValueError("preset is required when action includes waveform")
        msg: dict[str, Any] = {
            "op": OpCode.TRIGGER.value,
            "action": action.value,
            "delta_pct": delta_pct,
            "strength_mode": strength_mode.value,
            "duration_s": duration_s,
            "preset": preset,
            "channel": channel.value,
        }
        for key, value in (
            ("label", label),
            ("username", username),
            ("name", name),
            ("cause", cause),
            ("pulse_name", pulse_name),
            ("target_id", target_id),
        ):
            if value is not None:
                msg[key] = value
        return json.dumps(msg)

    @staticmethod
    def event(
        label: str,
        name: str,
        username: str | None = None,
        strength_pct: int | None = None,
        duration: float = 1.0,
        event_id: str | None = None,
        cause: str | None = None,
        pulse_name: str | None = None,
        from_pct: int | None = None,
        to_pct: int | None = None,
        delta_pct: int | None = None,
        target_id: str | None = None,
    ) -> str:
        """构建一次性事件消息。"""
        if not label:
            raise ValueError("label is required")
        if not name:
            raise ValueError("name is required")
        msg: dict[str, Any] = {
            "op": OpCode.EVENT.value,
            "label": label,
            "name": name,
            "duration": duration,
        }
        for key, value in (
            ("username", username),
            ("strength_pct", strength_pct),
            ("event_id", event_id),
            ("cause", cause),
            ("pulse_name", pulse_name),
            ("from_pct", from_pct),
            ("to_pct", to_pct),
            ("delta_pct", delta_pct),
            ("target_id", target_id),
        ):
            if value is not None:
                msg[key] = value
        return json.dumps(msg)

    @staticmethod
    def pulse(
        preset: str,
        channel: Channel = Channel.BOTH,
        target_id: str | None = None,
    ) -> str:
        """构建仅波形的脉冲消息。"""
        if not preset:
            raise ValueError("preset is required")
        msg = {
            "op": OpCode.PULSE.value,
            "preset": preset,
            "channel": channel.value,
        }
        if target_id is not None:
            msg["target_id"] = target_id
        return json.dumps(msg)

    @staticmethod
    def set_strength(
        channel: Channel,
        pct: int,
        target_id: str | None = None,
    ) -> str:
        """构建 set_strength 消息。"""
        if not 0 <= pct <= 100:
            raise ValueError("pct must be 0-100")
        msg = {
            "op": OpCode.SET_STRENGTH.value,
            "channel": channel.value,
            "pct": pct,
        }
        if target_id is not None:
            msg["target_id"] = target_id
        return json.dumps(msg)

    @staticmethod
    def adjust_strength(
        channel: Channel,
        delta_pct: int,
        target_id: str | None = None,
    ) -> str:
        """构建 adjust_strength 消息。"""
        if not -100 <= delta_pct <= 100:
            raise ValueError("delta_pct must be -100 to 100")
        msg = {
            "op": OpCode.ADJUST_STRENGTH.value,
            "channel": channel.value,
            "delta_pct": delta_pct,
        }
        if target_id is not None:
            msg["target_id"] = target_id
        return json.dumps(msg)

    @staticmethod
    def status(fields: dict[str, Any]) -> str:
        """构建状态上报消息。"""
        if not isinstance(fields, dict):
            raise TypeError("fields must be a dict")
        return json.dumps({
            "op": OpCode.STATUS.value,
            "fields": fields,
        })

    @staticmethod
    def log(level: LogLevel, message: str) -> str:
        """构建日志消息。"""
        return json.dumps({
            "op": OpCode.LOG.value,
            "level": level.value,
            "message": message,
        })

    @staticmethod
    def set_config(key: str, value: Any) -> str:
        """构建 set_config 消息，用于持久化运行时数据。"""
        return json.dumps({
            "op": OpCode.SET_CONFIG.value,
            "key": key,
            "value": value,
        })

    @staticmethod
    def parse(raw: str) -> CodecMessage:
        """将 JSON 字符串解析为类型化的 ``CodecMessage`` 数据类。"""
        data = json.loads(raw)
        match data:
            case {"op": OpCode.HELLO_ACK} as ack:
                ack_fields = {k: v for k, v in ack.items() if k != "op"}
                return CodecMessage(op=OpCode.HELLO_ACK, data=ack_fields)
            case {"op": OpCode.CONFIG, "data": d}:
                return CodecMessage(op=OpCode.CONFIG, data=d)
            case {"op": OpCode.CONFIG_CHANGED, "key": k, "value": v}:
                return CodecMessage(op=OpCode.CONFIG_CHANGED, key=k, value=v)
            case {"op": OpCode.DEVICE_INFO, "connected": c,
                  "device_type": dt, "max_strength_a": ma, "max_strength_b": mb}:
                return CodecMessage(
                    op=OpCode.DEVICE_INFO, connected=c,
                    device_type=DeviceType(dt),
                    max_strength_a=ma, max_strength_b=mb,
                )
            case {"op": OpCode.PING, "t": t}:
                return CodecMessage(op=OpCode.PING, t=t)
            case {"op": OpCode.STOP, "reason": r}:
                return CodecMessage(op=OpCode.STOP, reason=r)
            case _:
                raise ValueError(f"Unknown op: {data.get('op')}")

    @staticmethod
    def serialize(msg: CodecMessage) -> str:
        """将 ``CodecMessage`` 序列化回 JSON 字符串。"""
        data: dict[str, Any] = {"op": msg.op.value}
        for key in ("status", "data", "key", "value", "connected",
                     "device_type", "max_strength_a", "max_strength_b",
                     "reason", "t"):
            val = getattr(msg, key)
            if val is not None:
                data[key] = val.value if isinstance(val, StrEnum) else val
        return json.dumps(data)
