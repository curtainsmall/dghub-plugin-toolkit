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


def resolve_packer_name(ctx: Any, manifest_data: dict[str, Any]) -> str:
    """包名解析：显式包名（构建页「包名」）> 插件目录名（默认）。

    显式包名非法（非安全字符）时视为未提供，回退插件目录名。
    """
    name = ""
    builder = getattr(ctx, "builder", None)
    if builder is not None:
        name = builder.get_packer_name()
    if not _PACKER_NAME_RE.match(name):
        name = ""
    if not name:
        name = ctx.plugin_name
    return name


def package_plugin(ctx: Any, manifest_data: dict[str, Any],
                   out_files: list[tuple[Path, str]],
                   no_zip: bool,
                   keep_cache: bool = False) -> Path:
    """按 no_zip 组装产物并清理中间目录，返回产物路径。

    - ``no_zip=False``（默认）→ ``<name>.zip``（分发）
    - ``no_zip=True`` → ``<name>/`` 目录（调试，就地可用）
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
