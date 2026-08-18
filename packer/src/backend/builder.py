"""Builder：阶段 2 输入视图（打包内容 + 发布选项）+ 收集逻辑。

打包内容 = 统一文件选择列表（``builder.files``），用户 / 编译 deduce /
任何来源均可通过同一接口添加条目；特殊条目用 ``tags`` 标记——本计划定义
``entry`` 标签（主入口，manifest.entry 引用；必要条目，validate 保证恰好
一个）。发布选项 = ``output_dir``（发布形态固定 zip）。

Builder 完全独立：只消费 builder.files 与发布选项，不引用编译配置、
不引用顶层 entry（阶段 1 输入）。收集（resolve）时 arc 保留相对项目根的
路径（镜像插件根布局），编译产物树由管线另行并入。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.project_manager import ProjectManager


@dataclass
class BuilderItem:
    """打包内容条目：path / dir / pattern 三选一，可选 tags 与 derived。

    ``derived=True`` 表示编译产物条目（显式声明，非用户选择）；
    持久化到 project.json 时经 ``to_dict()`` 保持原 JSON 形状。
    """

    path: str | None = None
    dir: str | None = None
    pattern: str | None = None
    tags: list[str] = field(default_factory=list)
    derived: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "BuilderItem":
        return cls(
            path=d.get("path"),
            dir=d.get("dir"),
            pattern=d.get("pattern"),
            tags=list(d.get("tags", [])),
            derived=bool(d.get("derived")),
        )

    def to_dict(self) -> dict:
        item: dict[str, Any] = {}
        for key in ("path", "dir", "pattern"):
            value = getattr(self, key)
            if value is not None:
                item[key] = value
        if self.tags:
            item["tags"] = list(self.tags)
        if self.derived:
            item["derived"] = True
        return item


class BuildError(Exception):
    """产物收集阶段的失败（缺失文件 / 同名冲突），携带错误列表。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def evaluate_pattern(workdir: Path, pattern: str) -> list[str]:
    """对收集根求值 glob 规则，返回相对路径列表（仅文件，排序）。"""
    try:
        return sorted(
            p.relative_to(workdir).as_posix()
            for p in workdir.glob(pattern) if p.is_file())
    except (ValueError, OSError):
        return []


class Builder:
    """阶段 2 输入视图：统一文件选择列表（任何来源可添加）+ 发布选项。

    打包内容 = 手动条目（持久化于 project.json）+ deduced 编译产物
    （运行时注入，不落盘——总能从编译设置重新推导）。
    """

    def __init__(self, pm: ProjectManager) -> None:
        self._pm = pm
        self._no_zip_override: bool | None = None  # 调试 folder 内存覆盖（不落盘）
        self._deduced: list[BuilderItem] = []  # deduce 结果（派生视图，不持久化）

    # ------------------------------------------------------------------
    # 打包内容（手动条目持久化；deduced 条目运行时注入）
    # ------------------------------------------------------------------

    def _files(self) -> list[BuilderItem]:
        """手动条目（project.json）；旧版 derived/auto 残留读时忽略。"""
        return [BuilderItem.from_dict(d)
                for d in self._pm.read_builder_files()
                if not d.get("derived") and "auto" not in d.get("tags", [])]

    def _save(self, files: list[BuilderItem]) -> None:
        """落盘：derived / 废弃 auto 条目不持久化（仅手动条目）。"""
        self._pm.write_builder_files([
            f.to_dict() for f in files
            if not f.derived and "auto" not in f.tags])

    def set_deduced(self, items: list[BuilderItem]) -> None:
        """注入 deduce 结果（派生视图，仅内存——可随时从编译设置重建）。"""
        self._deduced = list(items)

    def prune_persisted(self) -> None:
        """清理 project.json 中过期的 derived/auto 残留（一次性迁移）。

        旧版把 deduced 条目落盘；新模型读时已忽略，此处落盘清洗。
        """
        self._save(self._files())

    def deduced_items(self) -> list[BuilderItem]:
        return list(self._deduced)

    def add_file(self, rel: str,
                 tags: list[str] | None = None,
                 derived: bool = False) -> None:
        files = self._files()
        files.append(BuilderItem(path=rel, tags=list(tags or []),
                                 derived=derived))
        self._save(files)

    def add_dir(self, rel: str,
                tags: list[str] | None = None,
                derived: bool = False) -> None:
        files = self._files()
        files.append(BuilderItem(dir=rel, tags=list(tags or []),
                                 derived=derived))
        self._save(files)

    def add_rule(self, pattern: str,
                 tags: list[str] | None = None) -> None:
        files = self._files()
        files.append(BuilderItem(pattern=pattern, tags=list(tags or [])))
        self._save(files)

    def remove_derived(self) -> int:
        """清除 deduced 视图（编译产物条目），返回移除数量。"""
        n = len(self._deduced)
        self._deduced = []
        return n

    def remove_item(self, idx: int) -> None:
        """删除条目（视图索引）——deduced 只读，仅手动条目可删。"""
        files = self._files()
        mi = idx - len(self._deduced)
        if 0 <= mi < len(files):
            files.pop(mi)
            self._save(files)

    def set_tags(self, idx: int, tags: list[str]) -> None:
        """贴/改标签（如标为 entry）——视图索引，deduced 条目只读。"""
        files = self._files()
        mi = idx - len(self._deduced)
        if 0 <= mi < len(files):
            files[mi].tags = list(tags)
            self._save(files)

    def strip_tag(self, tag: str) -> int:
        """摘除所有条目上的指定标签（条目本身保留），返回受影响条数。

        编译系统自持入口时用于「降级」手动 entry：旧入口条目保留为普通
        打包内容，但不再充当 manifest.entry。
        """
        files = self._files()
        n = 0
        for it in files:
            if tag in it.tags:
                it.tags = [t for t in it.tags if t != tag]
                n += 1
        if n:
            self._save(files)
        return n

    def set_path(self, idx: int, rel: str) -> None:
        """替换条目路径（保持类型与标签不变）——视图索引，deduced 只读。"""
        files = self._files()
        mi = idx - len(self._deduced)
        if 0 <= mi < len(files):
            item = files[mi]
            if item.path is not None:
                item.path = rel
            elif item.dir is not None:
                item.dir = rel
            else:
                item.pattern = rel
            self._save(files)

    def items(self) -> list[BuilderItem]:
        """条目列表：deduced（编译产物，视图在前）+ 手动条目。

        deduced 顺序即 deduce 返回顺序（入口在前）；手动保持添加顺序。
        """
        return self._deduced + self._files()

    # ------------------------------------------------------------------
    # 发布选项（发布形态固定 zip；folder 仅调试用内存覆盖，不落盘）
    # ------------------------------------------------------------------

    def get_no_zip(self) -> bool:
        """是否输出 folder（调试）。默认 False = zip 分发。"""
        if self._no_zip_override is not None:
            return self._no_zip_override
        return False

    def set_no_zip(self, value: bool) -> None:
        """内存覆盖 folder 输出（调试构建用，不写入 project.json）。"""
        self._no_zip_override = bool(value)

    def get_output_dir(self) -> str:
        return str(self._pm.get_builder().get("output_dir", ""))

    def set_output_dir(self, value: str) -> None:
        self._pm.set_builder_field("output_dir", value)

    def get_packer_name(self) -> str:
        """自定义包名（zip/目录名）；空 = 使用插件目录名。"""
        return str(self._pm.get_builder().get("packer_name", "")).strip()

    def set_packer_name(self, value: str) -> None:
        self._pm.set_builder_field("packer_name", value.strip())

    # ------------------------------------------------------------------
    # 必要条目校验（validate 阶段）
    # ------------------------------------------------------------------

    def entry_errors(self, source_dir: Path) -> list[str]:
        """entry 必要条目校验：恰好一个、必须为单个文件。

        文件存在性不在校验期检查——编译产物（如 <name>.exe）由阶段 1
        构建时生成，存在性由 resolve（收集阶段）兜底报 BuildError。
        """
        entries = [i for i in self.items() if "entry" in i.tags]
        if len(entries) > 1:
            return ["入口条目重复：请仅将一个文件设为入口"]
        if not entries:
            return ["缺少入口条目，请在打包内容中设置入口"]
        item = entries[0]
        if item.path is None:
            return ["入口必须是单个文件（目录/规则不能作为入口）"]
        return []

    def entry_item(self) -> BuilderItem | None:
        """返回带 entry 标签的条目（validate 已保证恰好一个）。"""
        for item in self.items():
            if "entry" in item.tags:
                return item
        return None

    # ------------------------------------------------------------------
    # 收集（构建时调用）
    # ------------------------------------------------------------------

    def resolve(self, source_dir: Path,
                entry_exempt: bool = True,
                prod_dir: Path | None = None) -> list[tuple[Path, str]]:
        """条目 → [(源文件, 包内相对路径)]。

        ``entry_exempt=True``（有编译时）：入口文件可能由编译阶段产出，
        缺失豁免，由管线收集后兜底校验；``False``（无编译）时入口
        必须真实存在，缺失报「打包内容文件不存在」。

        ``derived`` 条目（编译产物声明）从 ``prod_dir``（产物树，如
        ``output/.pyi/<插件名>/``）解析；产物树不存在时静默跳过
        （缺失由管线兜底校验）。

        arc 保留相对项目根的路径（子目录结构不丢失）；同名 arc 去重
        （先到先得，entry 条目与规则求值结果因此自动去重）；
        缺失文件/目录报 BuildError。
        """
        errors: list[str] = []
        out: list[tuple[Path, str]] = []
        seen: set[str] = set()

        def _append(src: Path, arc: str) -> None:
            if arc in seen:
                return
            seen.add(arc)
            out.append((src, arc))

        for item in self.items():
            if item.path is not None:
                rel = item.path
                if item.derived:
                    # 编译产物入口：从产物树解析，缺失跳过（管线兜底）
                    if prod_dir is not None:
                        src = prod_dir / rel
                        if src.is_file():
                            _append(src, rel)
                    continue
                src = source_dir / rel
                if not src.is_file():
                    if entry_exempt and "entry" in item.tags:
                        # 入口文件可能由编译阶段产出（如 <插件名>.exe 在
                        # 处理器产物树中）；缺失与否由管线收集后兜底校验
                        continue
                    errors.append(f"打包内容文件不存在: {rel}")
                    continue
                _append(src, rel)
            elif item.dir is not None:
                rel = item.dir
                if item.derived:
                    # 编译产物目录（如 _internal/）：从产物树解析
                    if prod_dir is not None:
                        base = prod_dir / rel
                        if base.is_dir():
                            for f in sorted(base.rglob("*")):
                                if f.is_file():
                                    _append(f, f"{rel}/{f.relative_to(base).as_posix()}")
                    continue
                base = source_dir / rel
                if not base.is_dir():
                    errors.append(f"打包内容目录不存在: {rel}")
                    continue
                for f in sorted(base.rglob("*")):
                    if f.is_file():
                        _append(f, f"{rel}/{f.relative_to(base).as_posix()}")
            else:  # pattern
                rel = item.pattern or ""
                for matched in evaluate_pattern(source_dir, rel):
                    src = source_dir / matched
                    if src.is_file():
                        _append(src, matched)

        if errors:
            raise BuildError(errors)
        return out
