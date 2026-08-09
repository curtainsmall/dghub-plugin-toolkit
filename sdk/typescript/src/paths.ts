/**
 * 插件根与 manifest 目录定位（与 Python SDK `dghub_sdk.agent` 语义一致）。
 *
 * 优先级（pluginRoot）：
 * 显式参数原样返回 → `DGHUB_PLUGIN_ROOT` env（绝对路径，resolve 兜底）
 * → 打包形态（可执行文件目录）→ 调用者文件目录。进程内缓存。
 */

import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** 打包形态检测：Node 单文件打包器（pkg / bytenode 等）或原生 exe 内嵌。 */
function isPackaged(): boolean {
  // pkg / nexe / bytenode 等打包器会注入这些标志
  return Boolean((process as unknown as Record<string, unknown>).pkg)
    || process.execPath.toLowerCase().endsWith(".exe")
    && !process.execPath.toLowerCase().includes("node.exe");
}

/** 尽力获取调用者文件目录（栈解析；失败回退 cwd）。 */
function callerDir(depth = 2): string {
  try {
    const stack = new Error().stack?.split("\n") ?? [];
    // stack[0]=Error, stack[1]=callerDir 自身, stack[depth]=目标调用者
    const line = stack[depth] ?? "";
    const m = line.match(/\((.*?):\d+:\d+\)$/) ?? line.match(/at\s+(.*?):\d+:\d+$/);
    if (m) {
      return dirname(m[1].startsWith("file://") ? fileURLToPath(m[1]) : m[1]);
    }
  } catch {
    // 栈解析失败 → 回退 cwd
  }
  return process.cwd();
}

/** 跨平台绝对路径：POSIX 绝对路径或 Windows 盘符（`C:/` / `C:\`）。 */
function isAbsPath(p: string): boolean {
  return isAbsolute(p) || /^[a-zA-Z]:[\\/]/.test(p);
}

let _cachedRoot: string | null = null;

/**
 * 插件根：显式传入**原样返回**（不解析不校验）；
 * 否则默认：`DGHUB_PLUGIN_ROOT` env（resolve 兜底）→ 打包 exe 目录
 * → 调用者目录。进程内缓存。
 */
export function pluginRoot(pluginDir?: string): string {
  if (pluginDir !== undefined && pluginDir !== null && pluginDir !== "") {
    return pluginDir;
  }
  if (_cachedRoot !== null) {
    return _cachedRoot;
  }
  const envDir = process.env.DGHUB_PLUGIN_ROOT;
  if (envDir) {
    _cachedRoot = resolve(envDir);
    return _cachedRoot!;
  }
  if (isPackaged()) {
    _cachedRoot = dirname(process.execPath);
    return _cachedRoot!;
  }
  _cachedRoot = callerDir();
  return _cachedRoot!;
}

/**
 * 解析 manifest 目录：显式参数（相对路径以调用者文件目录为基准）
 * → `DGHUB_MANIFEST_DIR` env（注入约定绝对路径，resolve 兜底）
 * → 插件根。
 */
export function manifestDir(explicit?: string): string {
  if (explicit !== undefined && explicit !== null && explicit !== "") {
    if (isAbsolute(explicit)) {
      return explicit;
    }
    // manifestDir 内部多一层调用：caller 位于栈深 3
    return resolve(callerDir(3), explicit);
  }
  const envDir = process.env.DGHUB_MANIFEST_DIR;
  if (envDir) {
    return resolve(envDir);
  }
  return pluginRoot();
}
/** 读取 DGHub 连接环境变量（默认值同 Python SDK）。 */
export function envConfig(): { host: string; port: number; token: string } {
  const host = process.env.DGHUB_HOST || "localhost";
  const port = Number(process.env.DGHUB_PORT || "8000");
  const token = process.env.DGHUB_TOKEN || "";
  return { host, port, token };
}
