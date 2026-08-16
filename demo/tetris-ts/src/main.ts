/**
 * 俄罗斯方块（TypeScript/Node + SDL2 窗口版）主程序。
 * 与 Python 版 `demo/tetris-py/src/main.py` 功能对齐：
 * Agent 生命周期、activated / delta_pct 配置回调、Game Over 惩罚触发、
 * 暂停覆盖层、DAS 连发与软降加速。渲染走 @kmamal/sdl 像素上屏。
 */

import { Agent, Action, AgentEvent, LogLevel } from "dghub-sdk";
import { Tetris } from "./game.js";
import { SdlRenderer, WIDTH, HEIGHT } from "./render.js";

let activated = false;
let deltaPct = 20;

function onConfigChanged(key: string, value: boolean | number | string): void {
  if (key === "activated") {
    activated = Boolean(value);
  } else if (key === "delta_pct") {
    deltaPct = Number(value);
  }
}

function onConfig(configs: Record<string, unknown>): void {
  for (const [key, value] of Object.entries(configs)) {
    onConfigChanged(key, value as boolean | number | string);
  }
}

function main(): void {
  const agent = new Agent();
  // 事件驱动：消息到达即触发，无需 poll
  agent.on(AgentEvent.Config, onConfig);
  agent.on(AgentEvent.ConfigChanged, onConfigChanged);
  agent.on(AgentEvent.Error, (err) => console.error(`[SDK 错误] ${err}`));
  agent.start();

  const renderer = new SdlRenderer();
  const game = new Tetris();

  // DAS 连发状态（对齐 Python 版）
  const dasDelay = 0.15;
  const dasRepeat = 0.05;
  let dasDir = 0;
  let dasTimer = 0.0;
  let dasCharged = false;
  let softDrop = false;
  let punished = true;

  // 按键映射（虚拟键字符串 → 游戏动作，@kmamal/sdl 的 keyDown 事件 key 字段）
  const window = renderer.window;
  window.on("keyDown", (e: { key: string | null }) => {
    switch (e.key) {
      case "r":
        game.restart();
        break;
      case "left":
        game.move(-1, 0);
        dasDir = -1;
        dasTimer = 0.0;
        dasCharged = false;
        break;
      case "right":
        game.move(1, 0);
        dasDir = 1;
        dasTimer = 0.0;
        dasCharged = false;
        break;
      case "down":
        softDrop = true;
        break;
      case "up":
        game.rotate();
        break;
      case "space":
        game.hardDrop();
        break;
    }
  });
  window.on("keyUp", (e: { key: string | null }) => {
    if (e.key === "left" || e.key === "right") {
      dasDir = 0;
    } else if (e.key === "down") {
      softDrop = false;
    }
  });
  window.on("close", () => {
    agent.stop();
    // 不调 renderer.destroy()：@kmamal/sdl 的全局事件轮询在 destroy 后
    // 仍会访问窗口（events_poll 抛 "window is destroyed"），直接退出
    process.exit(0);
  });

  // 等待握手（不阻塞窗口，连接失败由 Error 事件上报）
  agent.waitReady(10)
    .then(() => agent.sendLog(LogLevel.INFO, "tetris-ts started"))
    .catch(() => { /* 错误已通过 AgentEvent.Error 上报 */ });

  const FPS = 30;
  const frameMs = 1000 / FPS;
  let lastFrame = Date.now();

  const loop = (): void => {
    const now = Date.now();
    const dt = Math.min((now - lastFrame) / 1000, 0.1);
    lastFrame = now;

    // 暂停：插件开关关闭时，丢弃瞬时输入避免恢复卡住
    if (!activated) {
      dasDir = 0;
      dasTimer = 0.0;
      dasCharged = false;
      softDrop = false;
      renderer.render(game, true);
      setTimeout(loop, frameMs);
      return;
    }

    // Game Over 惩罚触发（每次新游戏重新武装）
    if (game.gameOver) {
      if (!punished) {
        agent.sendTrigger({ action: Action.STRENGTH, deltaPct, durationS: 5 });
        punished = true;
      }
    } else {
      punished = false;
    }

    // DAS 自动连发
    if (dasDir !== 0) {
      dasTimer += dt;
      if (!dasCharged && dasTimer >= dasDelay) {
        dasCharged = true;
        dasTimer = 0.0;
      } else if (dasCharged && dasTimer >= dasRepeat) {
        game.move(dasDir, 0);
        dasTimer = 0.0;
      }
    }

    // 软降加速
    game.dropInterval = softDrop && !game.gameOver ? 0.05 : 0.5;

    game.update(dt);
    renderer.render(game, false);
    setTimeout(loop, frameMs);
  };

  loop();
}

main();
