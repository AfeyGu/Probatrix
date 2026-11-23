"""模板加载：目录扫描 + importlib 导入 + 模板收集。

设计要点见 docs/架构全景.md，模板共享说明见 docs/manual/模板开发指南.md。
- 扫描模板目录下所有 .py，收集带 __probatrix_template__ 标记的函数；
- 模板 id = 「文件名.函数名」（如 gl.calc），工程文件按 id 引用；
- 同目录数据模块（如 Hsteel.py）用普通 import 即可——加载时把模板目录
  插入 sys.path，Python 自行解析依赖；
- 模板可模块级声明 `__probatrix_requires__`（第三方库 import 名列表），
  加载时检查依赖，缺的记入 meta.missing_deps，供界面在运行前提示；
- 单文件导入对话框不做（依赖会丢），单目录扫描；
- 每个文件计算 sha256，作为模板 hash（MVP 覆盖目录内所有被扫文件）；
- 导入报错不打断整体：记入 errors，界面可展示（改坏一个文件不影响其他模板）。
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .template import TemplateMeta

__all__ = ["TemplateEntry", "LoadError", "TemplateLoader"]

#: 加载模板模块用的内部模块名前缀，reload 时按前缀清理
_MOD_PREFIX = "_cbtpl_"

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


@dataclass
class TemplateEntry:
    """一个已加载的模板。"""

    meta: TemplateMeta          # meta.template_id 在收集时已填好
    file: Path
    hash: str                   # 模板文件 sha256


@dataclass
class LoadError:
    """一个导入失败的文件。"""

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

        for path in sorted(self.directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            self._import_file(path)

    # ------------------------------------------------------------------
    def _import_file(self, path: Path) -> None:
        stem = path.stem
        mod_name = _MOD_PREFIX + stem
        try:
            if mod_name in sys.modules:       # scan() 前已 forget，这里兜底
                del sys.modules[mod_name]
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法构造导入规格：{path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
        except Exception:
            import traceback
            self.errors.append(LoadError(file=path, error=traceback.format_exc()))
            return

        for attr, obj in vars(module).items():
            meta: TemplateMeta | None = getattr(obj, "__probatrix_template__", None)
            if meta is None or not callable(obj):
                continue
            meta.template_id = f"{stem}.{attr}"
            meta.requires = _declared_requires(module)
            meta.missing_deps = check_deps(meta.requires)
            self.entries[meta.template_id] = TemplateEntry(
                meta=meta, file=path, hash=file_hash(path),
            )

    def _forget_dir_modules(self) -> None:
        """把从任何已扫描模板目录加载过的模块移出 sys.modules，保证刷新拿到新代码。

        覆盖全部已扫描目录（不只当前目录）——否则后扫目录 import 同名数据模块时
        会命中先扫目录的缓存，拿错目录的数据表。
        """
        stale = [
            name for name, mod in sys.modules.items()
            if getattr(mod, "__file__", None)
            and Path(mod.__file__).resolve().parent in _SCANNED_DIRS
        ]
        for name in stale:
            sys.modules.pop(name, None)
