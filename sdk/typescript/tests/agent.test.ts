/**
 * Agent 基础测试 —— 构造/选项/属性/事件（不连真实 DGHub）。
 * 生命周期与网络行为需真实服务端，见 Python `tests/test_agent_lifecycle.py`。
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { Agent } from "../dist/agent.js";
import { AgentEvent, LogLevel } from "../dist/enums.js";

test("Agent 构造回调注册为对应事件监听器", () => {
  const agent = new Agent({
    maxRetries: 3,
    onReady: () => {},
    onConfig: () => {},
    onConfigChanged: () => {},
    onDeviceInfo: () => {},
    onStop: () => {},
    onPing: () => {},
  });
  assert.equal(agent.listenerCount(AgentEvent.Ready), 1);
  assert.equal(agent.listenerCount(AgentEvent.Config), 1);
  assert.equal(agent.listenerCount(AgentEvent.ConfigChanged), 1);
  assert.equal(agent.listenerCount(AgentEvent.DeviceInfo), 1);
  assert.equal(agent.listenerCount(AgentEvent.Stop), 1);
  assert.equal(agent.listenerCount(AgentEvent.Ping), 1);
  assert.equal(agent.connected, false);
  assert.equal(agent.pluginId, "");
  // 未 start 时 waitReady 拒绝
  assert.rejects(() => agent.waitReady(), /has not been started/);
});

test("Agent 发送方法在未连接时不抛错（排队/静默）", () => {
  const agent = new Agent();
  // 未连接时发送：SDK 缓冲（不崩溃）
  agent.sendLog(LogLevel.INFO, "test");
  agent.sendTrigger({ preset: "wave" });
  assert.equal(agent.connected, false);
});

test("Agent 事件分发（emit → 监听器）", () => {
  const agent = new Agent();
  const seen: string[] = [];
  agent.on(AgentEvent.ConfigChanged, (key, value) => { seen.push(`${key}=${value}`); });
  agent.on(AgentEvent.Stop, (reason) => { seen.push(`stop:${reason}`); });
  agent.emit(AgentEvent.ConfigChanged, "activated", true);
  agent.emit(AgentEvent.Stop, "server quit");
  assert.deepEqual(seen, ["activated=true", "stop:server quit"]);
});

test("Agent once 只触发一次", () => {
  const agent = new Agent();
  let count = 0;
  agent.once(AgentEvent.Ping, () => { count += 1; });
  agent.emit(AgentEvent.Ping, 1);
  agent.emit(AgentEvent.Ping, 2);
  assert.equal(count, 1);
});

test("Agent waitForClose 返回 Promise", () => {
  const agent = new Agent();
  assert.ok(agent.waitForClose() instanceof Promise);
});
