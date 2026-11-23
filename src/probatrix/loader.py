"""模板加载：目录扫描 + importlib 导入 + 模板收集。

设计要点见 docs/架构全景.md，模板共享说明见 docs/manual/02-模板开发指南.md。
- 只扫模板目录「一层」，两种布局并存：
  1) 单文件模板 `<名>.py`（老做法，模板目录入 sys.path，故 `import Hsteel` 可用）；
  2) 文件夹模板 `<名>/template.py`——文件夹里可放 images/、data/、report.md 等资源，
     私有模块用 `from .materials import ...` 相对导入（文件夹当短期 package，
     不往 sys.path 加文件夹，避免不同文件夹的同名模块互相串）；
  文件夹下没有 template.py 就不是模板（资源文件夹），其内部 *.py 一律不扫；
- 模板 id = 「<名>.<函数名>」，<名> 取单文件名或文件夹名（如 gl/template.py → gl.calc）；
  老工程按 id 引用，改文件夹名等于换模板，所以文件夹名就是 id 前缀；
- 单文件与文件夹同名（gl.py 与 gl/template.py）时保留单文件、把文件夹记入 errors，
  避免文件夹悄悄接管已有计算；
- 模板可模块级声明 `__probatrix_requires__`（第三方库 import 名列表），
  加载时检查依赖，缺的记入 meta.missing_deps，供界面在运行前提示；
- 单文件导入对话框不做（依赖会丢），单目录扫描；
- 每个入口文件计算 sha256 作为模板 hash——只覆盖入口（文件夹模板即 template.py），
  不含资源与私有模块；
- 导入报错不打断整体：记入 errors，界面可展示（改坏一个文件不影响其他模板）。
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .template import TemplateMeta

__all__ = ["TemplateEntry", "LoadError", "TemplateLoader"]

#: 加载模板模块用的内部模块名前缀，reload 时按前缀清理
_MOD_PREFIX = "_cbtpl_"

#: 文件夹模板的入口文件名：<名>/template.py
_ENTRY_NAME = "template.py"

_CHUNK = 1 << 20

#: 本进程内扫描过的模板目录（跨 loader 实例共享）：清理 sys.modules 时覆盖
#: 全部目录，防止 A 目录扫描后其数据模块（如 Hsteel）被 B 目录的模板串用。
_SCANNED_DIRS: set[Path] = set()
#: 由加载器插入 sys.path 的模板目录（只移除自己插入的，不动用户原有路径）
_SYS_PATH_ADDED: list[str] = []


def check_deps(requires: list[str]) -> list[str]:
    """返回 requires 中当前环境缺失的依赖（import 名）。"""
    missing: list[str] = []
    for name in requires:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def _declared_requires(module: Any) -> list[str]:
    """读模板模块级声明的 __probatrix_requires__（容忍 str / list / tuple）。"""
    raw = getattr(module, "__probatrix_requires__", None)
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(x) for x in raw if isinstance(x, str)]


def file_hash(path: Path) -> str:
    """sha256（十六进制），模板内容校验用。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class _Entry:
    """发现阶段的一个模板入口。"""

    stem: str           # 模板 id 前缀：单文件名或文件夹名
    path: Path          # 入口 .py（文件夹模板即 <名>/template.py）
    package: bool       # True：文件夹模板，按 package 导入以支持 `from .` 相对导入


def _module_name(entry: _Entry) -> str:
    """模板模块在 sys.modules 里的内部名字（不是模板 id）。

    模板块名可能是「steel.v2」「图文 计算书」这类——点是 import 机制里的包层级
    分隔符，空格不能进模块名，所以非词字符一律换下划线；再拼上入口所在文件夹的
    短哈希，让两个不同位置的同名文件夹（两个模板目录各有一个 steel/）拿到不同
    模块名：各自那份 `from .materials import` 不会互相顶替，万一找不到也是响亮的
    ModuleNotFoundError，而不是悄悄用另一个文件夹的数据算错数。
    """
    safe = re.sub(r"\W", "_", entry.stem)
    digest = hashlib.sha1(str(entry.path.parent).encode("utf-8")).hexdigest()[:8]
    return f"{_MOD_PREFIX}{safe}_{digest}"


def _discover(directory: Path) -> tuple[list[_Entry], list[LoadError]]:
    """列出模板目录一层的模板入口，返回（按加载顺序的入口，同名冲突）。

    只认两种入口：`<名>.py` 与 `<名>/template.py`；其余子目录当资源文件夹。
    顺序 = 先单文件（按文件名，与只扫 `*.py` 的旧行为一致），再文件夹（按名字）。
    """
    files = {
        path.stem: path for path in sorted(directory.glob("*.py"))
        if path.is_file() and not path.name.startswith("_")
    }
    entries = [_Entry(stem=stem, path=path, package=False) for stem, path in files.items()]
    conflicts: list[LoadError] = []
    for folder in sorted(directory.iterdir()):
        if not folder.is_dir() or folder.name.startswith(("_", ".")):
            continue
        entry_file = folder / _ENTRY_NAME
        if not entry_file.is_file():
            continue                                  # 资源文件夹，不进模板列表
        kept = files.get(folder.name)
        if kept is not None:
            conflicts.append(LoadError(
                file=entry_file,
                error=(
                    f"模板同名冲突：{entry_file} 与 {kept} 都叫「{folder.name}」。"
                    f"已按单文件 {kept.name} 加载，文件夹版本被忽略；"
                    f"请重命名其中一个（文件夹模板要求 <名>/template.py）。"
                ),
            ))
            continue                                  # 单文件优先，避免悄悄换掉老模板
        entries.append(_Entry(stem=folder.name, path=entry_file, package=True))
    return entries, conflicts


@dataclass
class TemplateEntry:
    """一个已加载的模板。"""

    meta: TemplateMeta          # meta.template_id 在收集时已填好
    file: Path
    hash: str                   # 模板入口文件 sha256


@dataclass
class LoadError:
    """一个导入失败的入口。"""

    file: Path
    error: str                  # traceback 原样，界面直接展示


@dataclass
class TemplateLoader:
    """模板目录的加载器；scan() 可重复调用（改代码后刷新）。"""

    directory: Path
    entries: dict[str, TemplateEntry] = field(default_factory=dict)
    errors: list[LoadError] = field(default_factory=list)

    def scan(self) -> None:
        """全量重扫：清掉已加载模块 → 逐个导入 → 收集模板。"""
        self.directory = Path(self.directory).resolve()
        _SCANNED_DIRS.add(self.directory)
        self._forget_dir_modules()
        self.entries.clear()
        self.errors.clear()
        if not self.directory.is_dir():
            raise FileNotFoundError(f"模板目录不存在：{self.directory}")

        # 模板目录入 sys.path，让 gl.py 里的 import Hsteel 正常解析；
        # 同时移除之前扫过的其他模板目录，避免旧目录的数据模块/同名模块串用
        dir_str = str(self.directory)
        for old in list(_SYS_PATH_ADDED):
            if old != dir_str and old in sys.path:
                sys.path.remove(old)
                _SYS_PATH_ADDED.remove(old)
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)
            _SYS_PATH_ADDED.append(dir_str)

        found, conflicts = _discover(self.directory)
        self.errors.extend(conflicts)          # 同名冲突先报，再按顺序导入入口
        for entry in found:
            self._import_entry(entry)

    # ------------------------------------------------------------------
    def _import_entry(self, entry: _Entry) -> None:
        stem = entry.stem
        mod_name = _module_name(entry)
        try:
            sys.modules.pop(mod_name, None)   # scan() 前已按前缀清理，这里兜底
            if entry.package:
                # 文件夹模板当短期 package 导入：__path__ = 文件夹本身，于是
                # `from .materials import X` 解析成 <mod_name>.materials。
                # 不往 sys.path 加文件夹，跨文件夹的同名模块不会互相串用。
                spec = importlib.util.spec_from_file_location(
                    mod_name, entry.path,
                    submodule_search_locations=[str(entry.path.parent)],
                )
            else:
                spec = importlib.util.spec_from_file_location(mod_name, entry.path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法构造导入规格：{entry.path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except Exception:
            import traceback
            self.errors.append(LoadError(file=entry.path, error=traceback.format_exc()))
            return

        for attr, obj in vars(module).items():
            meta: TemplateMeta | None = getattr(obj, "__probatrix_template__", None)
            if meta is None or not callable(obj):
                continue
            meta.template_id = f"{stem}.{attr}"
            meta.requires = _declared_requires(module)
            meta.missing_deps = check_deps(meta.requires)
            self.entries[meta.template_id] = TemplateEntry(
                meta=meta, file=entry.path, hash=file_hash(entry.path),
            )

    def _forget_dir_modules(self) -> None:
        """把该重来的模块移出 sys.modules，保证刷新拿到新代码。

        两类都要清掉：
        - 本目录的模板模块（`_cbtpl_*` 及文件夹内的私有模块，按文件路径判断）：
          刷新后必须重新导入，否则改 materials.py 还是用旧表；
        - 任何已扫描模板目录下的模块（如单文件模板 import 的 Hsteel）：
          覆盖全部已扫描目录，否则后扫目录 import 同名数据模块时会命中先扫
          目录的缓存，拿错目录的数据表。

        另一个目录的文件夹模板不清——它们的模块名带文件夹路径短哈希，
        各自那份 `from .materials import` 一直指向自己的文件夹，不会互相顶替；
        清掉反而会让已加载模板的懒导入失效。
        """
        stale = []
        for name, mod in sys.modules.items():
            file = getattr(mod, "__file__", None)
            if not file:
                continue
            path = Path(file).resolve()
            if path.parent in _SCANNED_DIRS or (
                name.startswith(_MOD_PREFIX) and self.directory in path.parents
            ):
                stale.append(name)
        for name in stale:
            sys.modules.pop(name, None)
