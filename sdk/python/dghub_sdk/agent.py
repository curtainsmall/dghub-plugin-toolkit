"""异步 WebSocket 连接管理器 —— 对外提供完全同步的 API。

将整个异步生命周期封装在后台线程中。收到的服务端消息会先进入队列，
在用户线程调用 ``poll()`` 时再分发到各回调。

插件根与 manifest 目录定位：``plugin_root()``（模块级，@cache）返回插件根
（显式参数原样 / ``DGHUB_PLUGIN_ROOT`` env / frozen exe 目录 / caller 目录）；
``Agent.manifest_dir`` 默认 = 插件根，支持 ``DGHUB_MANIFEST_DIR`` 注入（Packer 调试）。
"""

import asyncio
import json
import os
import queue
import sys
import threading
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Callable

from .codec import Codec, CodecMessage
from .enums import Action, Channel, CheckState, DeviceType, LogLevel, OpCode, StrengthMode


@cache
def plugin_root(plugin_dir: Path | None = None) -> Path:
    """插件根：显式传入**原样返回**（用户负责，不解析不校验——谁先调用结果都相同）；
    否则默认：DGHUB_PLUGIN_ROOT env（约定绝对路径，resolve 兜底）→ frozen exe 目录
    → caller 目录。进程内缓存。"""
    if plugin_dir is not None:
        return Path(plugin_dir)
    env_dir = os.environ.get("DGHUB_PLUGIN_ROOT")
    if env_dir:
        return Path(env_dir).resolve()   # 注入值约定为绝对路径，resolve 兜底（相对 cwd 归一化）
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(sys._getframe(1).f_code.co_filename).resolve().parent


def manifest_dir(explicit: Path | str | None = None) -> Path:
    """manifest 目录三档解析（与 TS SDK ``manifestDir`` 对齐）。

    显式参数（相对以调用者文件目录为基准）→ ``DGHUB_MANIFEST_DIR`` env
    （注入约定绝对路径，resolve 兜底）→ 插件根 ``plugin_root()``。
    """
    if explicit is not None:
        p = Path(explicit)
        if not p.is_absolute():
            caller_file = sys._getframe(1).f_code.co_filename
            p = (Path(caller_file).resolve().parent / p).resolve()
        return p
    env_dir = os.environ.get("DGHUB_MANIFEST_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return plugin_root()


@dataclass(frozen=True)
class EnvConfig:
    """DGHub 连接环境变量（与 TS SDK ``envConfig`` 对齐）。"""

    host: str
    port: int
    token: str


def env_config() -> EnvConfig:
    """读取 DGHub 连接环境变量（默认值同 TS SDK：localhost:8000）。"""
    return EnvConfig(
        host=os.environ.get("DGHUB_HOST", "localhost"),
        port=int(os.environ.get("DGHUB_PORT", "8000")),
        token=os.environ.get("DGHUB_TOKEN", ""),
    )


# Agent.__init__ 参数名与模块级函数同名（公共 API 不可改名），
# 内部引用经此别名避免遮蔽
_resolve_manifest_dir = manifest_dir


class Agent:
    """异步 WebSocket 连接管理器 —— 对外提供完全同步的 API。

    将整个异步生命周期封装在后台线程中。收到的服务端消息会先进入队列，
    在用户线程调用 ``poll()`` 时再分发到各回调。
    """

    def __init__(
        self,
        *,
        manifest_dir: Path | None = None,
        max_retries: int = 5,
        send_timeout: float | None = None,
        on_ready: Callable[[dict[str, Any]], None] | None = None,
        on_config: Callable[[dict[str, Any]], None] | None = None,
        on_config_changed: Callable[[str, Any], None] | None = None,
        on_device_info: Callable[[bool, DeviceType, int, int], None] | None = None,
        on_stop: Callable[[str], None] | None = None,
        on_ping: Callable[[float], None] | None = None,
    ):
        """初始化 Agent。

        Args:
            manifest_dir: 包含 ``manifest.json`` 的目录，默认为插件根
                （frozen = exe 目录 / 源码 = 入口文件所在目录）；相对路径以
                调用方文件目录为基准；支持 ``DGHUB_MANIFEST_DIR`` 环境变量
                注入（Packer 调试，约定绝对路径）。
            max_retries: WebSocket 连接的最大重试次数。
            send_timeout: 每次发送操作的可选超时时间（秒）。
                ``None`` 表示发完即返回（不阻塞等待）。
            on_ready: 握手成功后调用，传入 hello_ack 数据。
            on_config: 握手后服务端推送一次全量配置时调用。
                签名：``(config: dict) -> None``。
            on_config_changed: 单个配置项变更时调用。
                签名：``(key: str, value: Any) -> None``。
            on_device_info: 设备状态变化时调用。
                签名：``(connected, device_type, max_a, max_b) -> None``。
            on_stop: 服务端要求插件停止时调用。
                签名：``(reason: str) -> None``。
            on_ping: 收到服务端 ping 时调用，传入时间戳。
        """
        # --- 解析 manifest 目录（显式 → DGHUB_MANIFEST_DIR → 插件根） ---
        self._manifest_dir = _resolve_manifest_dir(manifest_dir)

        self._max_retries = max_retries
        self._send_timeout = send_timeout

        # --- 回调 ---
        self.on_ready = on_ready
        self.on_config = on_config
        self.on_config_changed = on_config_changed
        self.on_device_info = on_device_info
        self.on_stop = on_stop
        self.on_ping = on_ping

        # --- 内部状态 ---
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ws: Any = None
        self._token: str = ""
        self._manifest: dict[str, Any] = {}
        self._plugin_id: str = ""
        self._connected = False
        self._stopped = False
        self._ready_event = threading.Event()
        self._startup_exception: Exception | None = None

        # 启动检查状态
        self._check_title: str = "Startup Check"
        self._check_steps: dict[str, dict] = {}

        # 队列（线程安全）
        self._queue: queue.Queue[CodecMessage] = queue.Queue()
        self._error_queue: queue.Queue[Exception] = queue.Queue()

    # -- 属性 ----------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    # -- 公开生命周期方法 ------------------------------------------------------

    def start(self) -> None:
        """在后台线程中启动 WebSocket 连接，不阻塞。"""
        self._stopped = False
        self._connected = False
        self._startup_exception = None
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float | None = None) -> None:
        """阻塞等待握手成功，或抛出连接阶段发生的异常。

        应在 ``start()``（或进入 ``with`` 块）之后、首次调用
        ``poll()`` / ``send_*`` 之前手动调用。
        """
        if self._thread is None:
            raise RuntimeError("Agent has not been started")
        if not self._ready_event.wait(timeout=timeout):
            raise TimeoutError("Agent did not become ready before timeout")
        if self._connected:
            return
        if self._startup_exception is not None:
            raise self._startup_exception
        raise ConnectionError("Agent stopped before handshake completed")

    def is_ready(self) -> bool:
        """一次性检查握手是否已完成（不阻塞）。"""
        return self._ready_event.is_set() and self._connected

    def poll(self, timeout: float | None = None) -> None:
        """处理已接收的消息，在当前线程上调用回调。

        ``timeout=None``（默认）：不阻塞，排空队列中所有消息。
        ``timeout>=0``：阻塞，最多等待 *timeout* 秒获取一条消息。
        """
        if timeout is None:
            while not self._queue.empty():
                msg = self._queue.get_nowait()
                self._invoke(msg)
        else:
            try:
                msg = self._queue.get(timeout=timeout)
                self._invoke(msg)
            except queue.Empty:
                pass

    def stop(self) -> None:
        """通知后台循环停止并断开连接。"""
        self._stopped = True
        if self._loop is not None and self._loop.is_running():
            async def _do_close():
                if self._ws is not None:
                    await self._ws.close()
                    self._ws = None
            future = asyncio.run_coroutine_threadsafe(_do_close(), self._loop)
            future.add_done_callback(self._record_background_exception)

    def wait_threading_exit(self, timeout: float | None = None) -> None:
        """阻塞等待后台线程退出（可选）。"""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def __enter__(self) -> "Agent":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
        self.wait_threading_exit(timeout=5.0)

    # -- 公开发送方法（均为同步） --------------------------------------------

    def send(self, raw: str) -> None:
        """通过 WebSocket 发送原始 JSON 字符串。"""
        self._schedule_send(raw)

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
    ) -> None:
        """向设备发送强度/波形触发。

        Args:
            action: 作用对象 —— 强度、波形或两者。
            delta_pct: 相对 baseline 的强度变化量（0–100）。
            strength_mode: ROLLBACK（临时）或 PERMANENT（持久）。
            duration_s: 触发持续时间（秒）。
            preset: 波形预设名（action 包含波形时必填）。
            channel: 目标通道（a / b / both）。
            label: 可选，触发事件的展示标签。
            username: 可选，与本次触发关联的用户名。
            name: 可选，事件的具体展示内容。
            cause: 可选，触发原因的人话描述。
            pulse_name: 可选，覆盖事件流显示的波形名。
            target_id: 可选，V4 本次行为的显式设备目标。

        Raises:
            ValueError: action 包含波形但 preset 为空时抛出。
        """
        raw = Codec.trigger(
            action, delta_pct, strength_mode, duration_s, preset, channel,
            label, username, name, cause, pulse_name, target_id,
        )
        self._schedule_send(raw)

    def send_event(
        self,
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
    ) -> None:
        """发送一次性命名事件。

        Args:
            label: 事件分类标签（必填）。
            name: 事件展示名称（必填）。
            username: 可选，触发事件的用户名。
            strength_pct: 可选，强度提示值（0–100）。
            duration: 事件持续时间（秒）。
            event_id: 可选，用于去重的事件 ID。
            cause: 可选，触发原因的人话描述。
            pulse_name: 可选，本次事件使用的波形名。
            from_pct: 可选，事件前的强度百分比。
            to_pct: 可选，事件后的目标强度百分比。
            delta_pct: 可选，目标相对原强度的差值。
            target_id: 可选，V4 事件所属的显式设备目标。
        """
        raw = Codec.event(
            label, name, username, strength_pct, duration, event_id,
            cause, pulse_name, from_pct, to_pct, delta_pct, target_id,
        )
        self._schedule_send(raw)

    def send_pulse(
        self,
        preset: str,
        channel: Channel = Channel.BOTH,
        target_id: str | None = None,
    ) -> None:
        """发送仅波形的脉冲（不改变强度）。

        Args:
            preset: 波形预设名。
            channel: 目标通道。
            target_id: 可选，V4 本次行为的显式设备目标。
        """
        raw = Codec.pulse(preset, channel, target_id)
        self._schedule_send(raw)

    def send_set_strength(
        self,
        channel: Channel,
        pct: int,
        target_id: str | None = None,
    ) -> None:
        """设置指定通道的绝对强度。

        Args:
            channel: 目标通道。
            pct: 绝对强度百分比（0–100）。
            target_id: 可选，V4 本次行为的显式设备目标。
        """
        raw = Codec.set_strength(channel, pct, target_id)
        self._schedule_send(raw)

    def send_adjust_strength(
        self,
        channel: Channel,
        delta_pct: int,
        target_id: str | None = None,
    ) -> None:
        """按相对增量调整强度。

        Args:
            channel: 目标通道。
            delta_pct: 相对变化量（-100 到 100）。
            target_id: 可选，V4 本次行为的显式设备目标。
        """
        raw = Codec.adjust_strength(channel, delta_pct, target_id)
        self._schedule_send(raw)

    def send_status(self, fields: dict[str, Any]) -> None:
        """向服务端上报插件状态（如 startup_check 结果）。

        Args:
            fields: 状态数据的键值对。通常包含带 ``CheckState``
                值的 ``startup_check``。
        """
        raw = Codec.status(fields)
        self._schedule_send(raw)

    def send_log(self, level: LogLevel, message: str) -> None:
        """向服务端发送日志，展示在 DGHub 控制台中。

        Args:
            level: 日志级别（debug/info/warning/error）。
            message: 日志文本。
        """
        raw = Codec.log(level, message)
        self._schedule_send(raw)

    def send_startup_check(
        self,
        key: str,
        title: str,
        state: CheckState,
        *,
        detail: str | None = None,
        hint: str | None = None,
        display_status: str | None = None,
        dont_send: bool = False,
    ) -> None:
        """更新一个启动检查步骤，并可选地发送全量状态。

        内部以 ``key`` 为键维护所有步骤，每次调用更新或新增对应步骤。
        除非 ``dont_send=True``，否则立即发送全部步骤。

        Args:
            key: 步骤的唯一标识。
            title: 步骤的可读名称。
            state: 当前检查状态。
            detail: 可选，状态详情文本。
            hint: 可选，面向用户的提示。
            display_status: 可选，在同一条消息中一并设置 display_status。
            dont_send: 为 True 时仅更新内部状态，不发送。
        """
        step: dict[str, Any] = {"key": key, "title": title, "state": state.value}
        if detail is not None:
            step["detail"] = detail
        if hint is not None:
            step["hint"] = hint
        self._check_steps[key] = step

        if dont_send:
            return

        fields: dict[str, Any] = {}
        if display_status is not None:
            fields["display_status"] = display_status
        fields["startup_check"] = {
            "title": self._check_title,
            "steps": list(self._check_steps.values()),
        }
        self.send_status(fields)

    def set_startup_check_title(self, title: str) -> None:
        """设置启动检查面板的标题（不发送）。"""
        self._check_title = title

    def send_display_status(self, text: str) -> None:
        """向服务端发送 display_status 更新。"""
        self.send_status({"display_status": text})

    def send_status_field(self, key: str, value: Any) -> None:
        """向服务端发送单个状态字段。

        Args:
            key: 状态字段名。
            value: 字段值（必须可 JSON 序列化）。
        """
        self.send_status({key: value})

    def send_set_config(self, key: str, value: Any) -> None:
        """将插件自有的配置键持久化到服务端。

        用于保存需要在重启后保留的运行时状态。
        不要写入服务端保留的键（如 ``target_id``）。

        Note:
            服务端不会为本次写入回推 ``config_changed``，
            发送后应自行更新本地配置缓存。

        Args:
            key: 配置键名。
            value: 要持久化的值（必须可 JSON 序列化）。
        """
        raw = Codec.set_config(key, value)
        self._schedule_send(raw)

    # -- 公开异常查询 ----------------------------------------------------------

    def get_exception(self) -> Exception | None:
        """返回后台线程捕获的一个异常，无则返回 ``None``。

        多个异常会保留在内部队列中，调用方应循环获取直到返回 ``None``。
        """
        try:
            return self._error_queue.get_nowait()
        except queue.Empty:
            return None

    # -- 内部：线程入口 ----------------------------------------------------------

    def _run_async(self) -> None:
        """后台线程入口，创建独立的事件循环。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_loop())
        except Exception as exc:
            if not self._ready_event.is_set():
                self._startup_exception = exc
            self._error_queue.put(exc)
        finally:
            self._connected = False
            self._ready_event.set()
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(
                    *pending,
                    return_exceptions=True,
                ))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            self._loop = None

    async def _connect_and_loop(self) -> None:
        """核心异步生命周期：加载 manifest、连接、握手、接收循环。"""
        import websockets

        # ---- 解析 manifest ----
        manifest_path = self._manifest_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest.json not found: {manifest_path}")
        with manifest_path.open("r", encoding="utf-8") as f:
            self._manifest = json.loads(f.read())

        self._plugin_id = self._manifest.get("id", "")

        # ---- 环境变量（经 env_config() 统一读取） ----
        cfg = env_config()
        self._token = cfg.token
        if not self._token:
            raise ValueError("DGHUB_TOKEN environment variable is not set")

        url = f"ws://{cfg.host}:{cfg.port}/ws/plugin?token={self._token}"

        # ---- 带重试的连接 ----
        for attempt in range(self._max_retries + 1):
            if self._stopped:
                raise ConnectionError(
                    "Agent stopped before connection established")
            try:
                self._ws = await websockets.connect(url)
                break
            except (ConnectionRefusedError, TimeoutError, OSError) as exc:
                if attempt < self._max_retries:
                    delay = min(2 ** attempt, 30)
                    # 分片等待：stop() 可在 0.5s 内中断退避重试
                    for _ in range(int(delay / 0.5)):
                        if self._stopped:
                            raise ConnectionError(
                                "Agent stopped before connection established")
                        await asyncio.sleep(0.5)
                else:
                    raise

        # ---- 握手 ----
        hello_raw = Codec.hello(self._token, self._manifest)
        await self._ws.send(hello_raw)
        ack_raw = await self._ws.recv()
        ack = json.loads(ack_raw)

        if not ack.get("accepted", False):
            raise ConnectionError(
                f"hello rejected: {ack.get('reason', 'unknown')}"
            )

        self._connected = True
        self._queue.put(CodecMessage(op=OpCode.HELLO_ACK, data={
            "accepted": ack.get("accepted"),
            "reason": ack.get("reason"),
            "sdk_version": ack.get("sdk_version"),
        }))
        self._ready_event.set()

        # ---- 接收循环 ----
        async for raw in self._ws:
            if self._stopped:
                break
            msg = Codec.parse(raw)
            if msg.op == OpCode.PING:
                pong = json.dumps({"op": "pong", "t": msg.t})
                await self._ws.send(pong)
                self._queue.put(msg)
            else:
                self._queue.put(msg)
                if msg.op == OpCode.STOP:
                    break

        self._connected = False

    # -- 内部：辅助方法 ----------------------------------------------------------

    def _invoke(self, msg: CodecMessage) -> None:
        """将单条消息分发到对应的回调。"""
        match msg.op:
            case OpCode.HELLO_ACK:
                if self.on_ready and msg.data:
                    self.on_ready(msg.data)
            case OpCode.CONFIG:
                if self.on_config:
                    self.on_config(msg.data or {})
            case OpCode.CONFIG_CHANGED:
                if self.on_config_changed:
                    self.on_config_changed(msg.key or "", msg.value)
            case OpCode.DEVICE_INFO:
                if self.on_device_info and all(
                    v is not None for v in (
                        msg.connected, msg.device_type,
                        msg.max_strength_a, msg.max_strength_b,
                    )
                ):
                    self.on_device_info(
                        msg.connected, msg.device_type,
                        msg.max_strength_a, msg.max_strength_b,
                    )
            case OpCode.STOP:
                if self.on_stop:
                    self.on_stop(msg.reason or "")
            case OpCode.PING:
                if self.on_ping:
                    self.on_ping(msg.t or 0.0)
            case _:
                pass

    def _schedule_send(self, raw: str) -> None:
        """将发送操作调度到后台事件循环上执行。"""
        if self._loop is None or not self._loop.is_running():
            raise RuntimeError("Agent is not connected")

        async def _do_send():
            if self._ws is None:
                raise RuntimeError("Agent is not connected")
            await self._ws.send(raw)

        future = asyncio.run_coroutine_threadsafe(_do_send(), self._loop)
        if self._send_timeout is not None:
            future.result(timeout=self._send_timeout)
        else:
            future.add_done_callback(self._record_background_exception)

    def _record_background_exception(self, future) -> None:
        """将后台发送/关闭异常转发到公开异常队列。"""
        try:
            future.result()
        except Exception as exc:
            if not (self._stopped and future.cancelled()):
                self._error_queue.put(exc)
