"""插件打包：生成产物 manifest.json、写 zip / 文件夹、清理中间产物。

阶段 2 的交付步骤（纯逻辑，经 Logger 汇报）。产物清单（out_files）由
pipeline 收集（Builder 条目 + 编译产物树），本模块只负责组装与清理。
"""

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any


def cleanup_intermediates(output_dir: Path, plugin_name: str,
                          keep_cache: bool = False) -> None:
    """删除输出目录内的构建中间产物（.deps / .pyi / cache）。

    产物（<name>.zip 或 <name>/ 目录）保留。``keep_cache=True``
    （调试构建）时保留 .deps / cache——PyInstaller 增量缓存的前提，
    下次调试构建复用 Analysis 结果加速。
    """
    names = (".pyi",) if keep_cache else (".deps", ".pyi", "cache")
    for name in names:
        d = output_dir / name
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


_PACKER_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")

# 按产物模式自动追加的包名后缀（compiler.auto_suffix 开启时）；
# 默认值，可在设置页自定义
_DEFAULT_SUFFIXES = {
    "exe": "-self-contained",
    "deps": "-dependent",
}


def pack_suffix(compile_cfg: dict[str, Any] | None) -> str:
    """auto_suffix 开启时按产物模式返回后缀；否则空串。

    后缀文本来自全局设置（pack_suffixes），可自定义；非法字符
    （非 [A-Za-z0-9_-]）回退默认值。
    """
    if not (compile_cfg or {}).get("auto_suffix"):
        return ""
    bundle = compile_cfg.get("bundle", "exe")
    default = _DEFAULT_SUFFIXES.get(bundle, "")
    from backend import settings_store
    saved = settings_store.get_state("pack_suffixes", {})
    suffix = (saved or {}).get(bundle, "") or default
    return suffix if _PACKER_NAME_RE.match(suffix) else default


def resolve_packer_name(ctx: Any, manifest_data: dict[str, Any]) -> str:
    """包名解析：显式包名（构建页「包名」）> 插件目录名（默认）。

    显式包名非法（非安全字符）时视为未提供，回退插件目录名。
    compiler.auto_suffix 开启时按产物模式追加后缀（exe →
    -self-contained / deps → -dependent）——仅影响最终产物名
    （zip / 调试目录），编译产物名不变。
    """
    name = ""
    builder = getattr(ctx, "builder", None)
    if builder is not None:
        name = builder.get_packer_name()
    if not _PACKER_NAME_RE.match(name):
        name = ""
    if not name:
        name = ctx.plugin_name
    compile_cfg = getattr(ctx, "compile_cfg", None) or {}
    return name + pack_suffix(compile_cfg)


def package_plugin(ctx: Any, manifest_data: dict[str, Any],
                   out_files: list[tuple[Path, str]],
                   no_zip: bool,
                   keep_cache: bool = False) -> Path:
    """按 no_zip 组装产物并清理中间目录，返回产物路径。

    - ``no_zip=False``（默认）→ ``<name>.zip``（分发）
    - ``no_zip=True`` → ``<name>/`` 目录（仅调试构建使用）
    - ``keep_cache=True``（调试构建）→ 保留 .deps / cache 供下次增量
    - 包名：显式包名（构建页「包名」）> manifest.id > 插件目录名

    收集阶段的缺失/冲突已由 pipeline 的 Builder.resolve 抛出 BuildError。
    """
    packer_name = resolve_packer_name(ctx, manifest_data)
    manifest_json = json.dumps(manifest_data, ensure_ascii=False, indent=2)

    if no_zip:
        folder_dir = ctx.output_dir / packer_name
        folder_dir.mkdir(parents=True, exist_ok=True)
        (folder_dir / "manifest.json").write_text(
            manifest_json, encoding="utf-8")
        for src, arc in out_files:
            dst = folder_dir / arc
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except Exception as exc:
                ctx.log.warning(f"复制文件失败: {exc}")
        ctx.log.success(f"文件夹已发布: {folder_dir}")
        artifact = folder_dir
    else:  # zip（默认）
        zip_path = ctx.output_dir / f"{packer_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_json)
            for src, arc in out_files:
                zf.write(src, arc)
        size_kb = zip_path.stat().st_size / 1024
        ctx.log.success(f"打包完成: {zip_path} ({size_kb:.1f} KB)")
        artifact = zip_path

    cleanup_intermediates(ctx.output_dir, ctx.plugin_name,
                          keep_cache=keep_cache)
    return artifact
