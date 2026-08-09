/**
 * 路径与环境变量测试 —— 对齐 Python SDK `agent.plugin_root` / `manifest_dir` 语义。
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { isAbsolute, join, resolve } from "node:path";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";

import { pluginRoot, manifestDir, envConfig } from "../dist/paths.js";

/** 创建平台原生唯一临时目录（对齐 Python `tmp_path` 语义）。 */
async function makeTmp(): Promise<string> {
  return mkdtemp(join(tmpdir(), "dghub-sdk-test-"));
}

test("envConfig 默认值", () => {
  const saved = { ...process.env };
  delete process.env.DGHUB_HOST;
  delete process.env.DGHUB_PORT;
  delete process.env.DGHUB_TOKEN;
  try {
    const cfg = envConfig();
    assert.equal(cfg.host, "localhost");
    assert.equal(cfg.port, 8000);
    assert.equal(cfg.token, "");
  } finally {
    Object.assign(process.env, saved);
  }
});

test("envConfig 环境变量注入", () => {
  const saved = { ...process.env };
  process.env.DGHUB_HOST = "192.168.1.5";
  process.env.DGHUB_PORT = "9000";
  process.env.DGHUB_TOKEN = "tok123";
  try {
    const cfg = envConfig();
    assert.equal(cfg.host, "192.168.1.5");
    assert.equal(cfg.port, 9000);
    assert.equal(cfg.token, "tok123");
  } finally {
    Object.assign(process.env, saved);
  }
});

test("pluginRoot 显式参数原样返回", () => {
  assert.equal(pluginRoot("D:/x/y"), "D:/x/y");
});

test("pluginRoot 优先环境变量（resolve 兜底）", async () => {
  const saved = { ...process.env };
  const dir = await makeTmp();
  process.env.DGHUB_PLUGIN_ROOT = dir;
  try {
    const root = pluginRoot();
    assert.ok(isAbsolute(root));
    assert.equal(root, resolve(dir));
  } finally {
    delete process.env.DGHUB_PLUGIN_ROOT;
    Object.assign(process.env, saved);
  }
});

test("pluginRoot 进程内缓存（显式参数不受缓存影响）", () => {
  const saved = { ...process.env };
  delete process.env.DGHUB_PLUGIN_ROOT;
  try {
    const a = pluginRoot();
    const b = pluginRoot();
    assert.equal(a, b); // 缓存：两次调用结果一致
  } finally {
    Object.assign(process.env, saved);
  }
});

test("manifestDir 环境变量注入", async () => {
  const saved = { ...process.env };
  const dir = await makeTmp();
  process.env.DGHUB_MANIFEST_DIR = dir;
  try {
    assert.equal(manifestDir(), resolve(dir));
  } finally {
    delete process.env.DGHUB_MANIFEST_DIR;
    Object.assign(process.env, saved);
  }
});

test("manifestDir 显式相对路径以调用者目录为基准", () => {
  const saved = { ...process.env };
  delete process.env.DGHUB_MANIFEST_DIR;
  try {
    const rel = manifestDir("relative/dir");
    assert.ok(isAbsolute(rel));
    assert.ok(rel.replace(/\\/g, "/").endsWith("/relative/dir"));
  } finally {
    Object.assign(process.env, saved);
  }
});

test("manifestDir 显式绝对路径原样返回", async () => {
  const saved = { ...process.env };
  delete process.env.DGHUB_MANIFEST_DIR;
  try {
    const dir = await makeTmp();
    // 显式参数原样返回（对齐 Python：不解析不校验）
    assert.equal(manifestDir(dir), dir);
  } finally {
    Object.assign(process.env, saved);
  }
});
