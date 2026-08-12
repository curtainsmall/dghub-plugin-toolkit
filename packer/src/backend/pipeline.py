"""构建编排：两阶段管线（validate → 编译 run → collect → package）。

阶段 1 = compile 编译（按 ``compile_system`` 字段显式单选："" 无 /
"python" / "command"），产出文件；阶段 2 = 统一 build 步骤——收集
Builder 条目（+ 编译产物树）→ 生成 manifest → 打包 → 清理。

BuildContext 由 GUI 组装（app.py），本模块不接触前端。经 ctx.log 汇报。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.builder import BuildError, Builder
from backend.build_control import Canceller
from backend.logbus import Logger
from backend.packaging import package_plugin
from backend.compilers import (
    CompilerContext,
    get_compiler,
    run_logged,
)
from backend.project_manager import ProjectManager


@dataclass
class BuildContext:
    """校验与构建共用的上下文（app.py 组装）。"""

    plugin_dir: Path
    source_dir: Path
    output_dir: Path
    plugin_name: str
    compile_system: str        # ""（无）/ "python" / "command"
    builder: Builder
    log: Logger
    pm: ProjectManager | None = None
    pypi_index: str = ""
    canceller: Canceller | None = None
    # 编译设置字段（compile_system 相关，由 app.py 从 project.json 读取）
    compile_cfg: dict[str, Any] = field(default_factory=dict)
    # 调试构建：保留 .deps / cache（PyInstaller 增量缓存前提）
    keep_cache: bool = False


def validate(ctx: BuildContext) -> list[str]:
    """静态校验：编译必要字段、Builder 必要条目（entry 由编译系统自持）。"""
    errors: list[str] = []
    comp = get_compiler(ctx.compile_system)  # 恒非 None（含「无」）
    errors += comp.validate(ctx.compile_cfg, ctx.source_dir)
    errors += ctx.builder.entry_errors(ctx.source_dir)
    return errors


def fill_builder(ctx: BuildContext) -> list[str] | None:
    """「从编译填充」：probe + deduce 串联，只填空。

    将建议落盘（编译设置字段 / Builder 条目），
    返回已应用的描述列表；无编译返回空列表（调用方提示）。
    """
    applied: list[str] = []
    comp = get_compiler(ctx.compile_system)  # 恒非 None（含「无」）

    # 0) 先清空既有 derived——无论是否有编译（切到「无」时也清，旧产物已失效）
    removed = ctx.builder.remove_derived()
    if removed:
        applied.append(f"已刷新 {removed} 个编译产物条目")

    if ctx.pm is None:
        return applied  # 无项目：可能清除了旧 derived，列表非空时调用方展示

    # 1) probe：编译设置为空时探测项目，建议编译设置（落盘）
    if not ctx.compile_cfg.get("manifest") \
            and not ctx.compile_cfg.get("compile"):
        suggest = comp.probe(ctx.plugin_dir)
        if suggest:
            section = dict(ctx.pm.get_field("compiler") or {})
            for key, value in suggest.items():
                section[key] = value
                applied.append(f"{key} = {value}")
            ctx.pm.set_field("compiler", section)

    # 2) deduce：建议编译产物条目（只填空——已存在 entry 条目不重复添加）
    items = ctx.builder.items()
    has_entry = any("entry" in it.tags for it in items)
    deduced = comp.deduce(ctx.compile_cfg, ctx.plugin_name, ctx.source_dir)
    if deduced and not has_entry:
        for item in deduced:
            if item.path is not None:
                ctx.builder.add_file(item.path, item.tags,
                                     derived=item.derived)
                applied.append(f"添加打包内容: {item.path}（入口）")
            elif item.dir is not None:
                ctx.builder.add_dir(item.dir, item.tags,
                                    derived=item.derived)
                applied.append(f"添加打包内容: {item.dir}（编译产物）")

    return applied


def run_build(ctx: BuildContext, manifest_data: dict[str, Any]) -> Path | None:
    """执行两阶段构建并打包，返回产物路径；失败返回 None。

    校验失败（BuildError 语义）时返回 None，错误经 ctx.log 记录；
    收集阶段的缺失/冲突抛 ``BuildError``，由调用方（GUI）处理。
    """
    errors = validate(ctx)
    if errors:
        for msg in errors:
            ctx.log.error(msg)
        return None

    # ---- 阶段 1：compile 编译（「无」编译 = 空操作）----
    comp = get_compiler(ctx.compile_system)
    pctx = CompilerContext(
        plugin_dir=ctx.plugin_dir,
        source_dir=ctx.source_dir,
        output_dir=ctx.output_dir,
        plugin_name=ctx.plugin_name,
        cfg=ctx.compile_cfg,
        log=ctx.log,
        pypi_index=ctx.pypi_index,
        canceller=ctx.canceller,
        keep_cache=ctx.keep_cache,
    )
    if not comp.run(pctx):
        return None

    # ---- 阶段 2：收集 + manifest + 打包 ----
    out_files: list[tuple[Path, str]] = []

    # 编译产物树（derived 条目从各编译的 prod_dir 解析，如 .pyi/<name>/）
    prod_dir = comp.prod_dir(ctx.output_dir, ctx.plugin_name)
    if prod_dir is not None and not prod_dir.is_dir():
        ctx.log.error(f"未找到打包产物: {prod_dir}")
        return None

    # Builder 条目（arc 保留相对路径）；无实际编译输入时入口缺失不豁免
    out_files += ctx.builder.resolve(
        ctx.source_dir,
        entry_exempt=bool(ctx.compile_cfg.get("compile")
                          or ctx.compile_cfg.get("manifest")),
        prod_dir=prod_dir)

    # manifest 的 entry = entry 标签条目的 arc（validate 已保证恰好一个）
    entry_item = ctx.builder.entry_item()
    assert entry_item is not None and entry_item.path is not None
    entry_arc = entry_item.path

    # 入口产物兜底校验：entry 文件可能由编译阶段产出（不在 source_dir），
    # 收集完成后必须实际存在（产物树或打包内容之一提供）
    if entry_arc not in {arc for _, arc in out_files}:
        ctx.log.error(f"入口产物缺失: {entry_arc}"
                      "（无编译时请检查打包内容中的入口文件）")
        return None

    data = dict(manifest_data)
    data["entry"] = entry_arc
    data.pop("homepage", None)

    return package_plugin(ctx, data, out_files,
                          ctx.builder.get_no_zip(),
                          keep_cache=ctx.keep_cache)
