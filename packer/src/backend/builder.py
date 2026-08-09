"""Builder：阶段 2 输入视图（打包内容 + 发布选项）+ 收集逻辑。

打包内容 = 统一文件选择列表（``builder.files``），用户 / 编译 deduce /
任何来源均可通过同一接口添加条目；特殊条目用 ``tags`` 标记——本计划定义
``entry`` 标签（主入口，manifest.entry 引用；必要条目，validate 保证恰好
一个）。发布选项 = ``no_zip`` / ``output_dir``。

Builder 完全独立：只消费 builder.files 与发布选项，不引用编译配置、
不引用顶层 entry（阶段 1 输入）。收集（resolve）时 arc 保留相对项目根的
路径（镜像插件根布局），编译产物树由管线另行并入。
"""

from pathlib import Path
from typing import Any

from backend.project_manager import ProjectManager


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
    """阶段 2 输入视图：统一文件选择列表（任何来源可添加）+ 发布选项。"""

    def __init__(self, pm: ProjectManager) -> None:
        self._pm = pm

    # ------------------------------------------------------------------
    # 打包内容（用户 / 编译 / 任何来源均通过同一接口添加条目）
    # ------------------------------------------------------------------

    def _files(self) -> list[dict[str, Any]]:
        return self._pm.read_builder_files()

    def _save(self, files: list[dict[str, Any]]) -> None:
        self._pm.write_builder_files(files)

    def add_file(self, rel: str,
                 tags: list[str] | None = None,
                 derived: bool = False) -> None:
        files = self._files()
        files.append(self._entry(rel, "path", tags, derived))
        self._save(files)

    def add_dir(self, rel: str,
                tags: list[str] | None = None,
                derived: bool = False) -> None:
        files = self._files()
        files.append(self._entry(rel, "dir", tags, derived))
        self._save(files)

    def add_rule(self, pattern: str,
                 tags: list[str] | None = None) -> None:
        files = self._files()
        files.append(self._entry(pattern, "pattern", tags))
        self._save(files)

    @staticmethod
    def _entry(rel: str, kind: str,
               tags: list[str] | None,
               derived: bool = False) -> dict[str, Any]:
        item: dict[str, Any] = {kind: rel}
        if tags:
            item["tags"] = list(tags)
        if derived:
            item["derived"] = True  # 编译产物条目（显式声明，非用户选择）
        return item

    def remove_derived(self) -> int:
        """移除所有 derived（编译产物）条目，返回移除数量。"""
        files = self._files()
        kept = [it for it in files if not it.get("derived")]
        n = len(files) - len(kept)
        if n:
            self._save(kept)
        return n

    def remove_item(self, idx: int) -> None:
        files = self._files()
        if 0 <= idx < len(files):
            files.pop(idx)
            self._save(files)

    def set_tags(self, idx: int, tags: list[str]) -> None:
        """贴/改标签（如标为 entry）。"""
        files = self._files()
        if 0 <= idx < len(files):
            if tags:
                files[idx]["tags"] = list(tags)
            else:
                files[idx].pop("tags", None)
            self._save(files)

    def set_path(self, idx: int, rel: str) -> None:
        """替换条目路径（保持类型与标签不变）。"""
        files = self._files()
        if 0 <= idx < len(files):
            item = files[idx]
            for key in ("path", "dir", "pattern"):
                if key in item:
                    item[key] = rel
                    break
            self._save(files)

    def items(self) -> list[dict[str, Any]]:
        """条目列表 [{"path"|"dir"|"pattern": ..., "tags": [...]}]。"""
        return list(self._files())

    # ------------------------------------------------------------------
    # 发布选项
    # ------------------------------------------------------------------

    def get_no_zip(self) -> bool:
        return bool(self._pm.get_builder().get("no_zip", False))

    def set_no_zip(self, value: bool) -> None:
        self._pm.set_builder_field("no_zip", bool(value))

    def get_output_dir(self) -> str:
        return str(self._pm.get_builder().get("output_dir", ""))

    def set_output_dir(self, value: str) -> None:
        self._pm.set_builder_field("output_dir", value)

    # ------------------------------------------------------------------
    # 必要条目校验（validate 阶段）
    # ------------------------------------------------------------------

    def entry_errors(self, source_dir: Path) -> list[str]:
        """entry 必要条目校验：恰好一个、必须为单个文件。

        文件存在性不在校验期检查——编译产物（如 <name>.exe）由阶段 1
        构建时生成，存在性由 resolve（收集阶段）兜底报 BuildError。
        """
        entries = [i for i in self.items()
                   if "entry" in i.get("tags", [])]
        if len(entries) > 1:
            return ["入口条目重复：请仅将一个文件设为入口"]
        if not entries:
            return ["缺少入口条目，请在打包内容中设置入口"]
        item = entries[0]
        if "path" not in item:
            return ["入口必须是单个文件（目录/规则不能作为入口）"]
        return []

    def entry_item(self) -> dict[str, Any] | None:
        """返回带 entry 标签的条目（validate 已保证恰好一个）。"""
        for item in self.items():
            if "entry" in item.get("tags", []):
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
            if "path" in item:
                rel = item["path"]
                if item.get("derived"):
                    # 编译产物入口：从产物树解析，缺失跳过（管线兜底）
                    if prod_dir is not None:
                        src = prod_dir / rel
                        if src.is_file():
                            _append(src, rel)
                    continue
                src = source_dir / rel
                if not src.is_file():
                    if entry_exempt and "entry" in item.get("tags", []):
                        # 入口文件可能由编译阶段产出（如 <插件名>.exe 在
                        # 处理器产物树中）；缺失与否由管线收集后兜底校验
                        continue
                    errors.append(f"打包内容文件不存在: {rel}")
                    continue
                _append(src, rel)
            elif "dir" in item:
                rel = item["dir"]
                if item.get("derived"):
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
                rel = item["pattern"]
                for matched in evaluate_pattern(source_dir, rel):
                    src = source_dir / matched
                    if src.is_file():
                        _append(src, matched)

        if errors:
            raise BuildError(errors)
        return out
