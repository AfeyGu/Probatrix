"""模板加载：目录扫描 + importlib 导入 + 模板收集。

设计要点（契约见 计算书工具文档.md 第 8 节）：
- 扫描模板目录下所有 .py，收集带 __calcbook_template__ 标记的函数；
- 模板 id = 「文件名.函数名」（如 gl.calc），工程文件按 id 引用；
- 同目录数据模块（如 Hsteel.py）用普通 import 即可——加载时把模板目录
  插入 sys.path，Python 自行解析依赖；
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

from .template import TemplateMeta

__all__ = ["TemplateEntry", "LoadError", "TemplateLoader"]

#: 加载模板模块用的内部模块名前缀，reload 时按前缀清理
_MOD_PREFIX = "_cbtpl_"

_CHUNK = 1 << 20


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
        """全量重扫：清掉本目录已加载模块 → 逐个导入 → 收集模板。"""
        self.directory = Path(self.directory).resolve()
        self._forget_dir_modules()
        self.entries.clear()
        self.errors.clear()
        if not self.directory.is_dir():
            raise FileNotFoundError(f"模板目录不存在：{self.directory}")

        # 模板目录入 sys.path，让 gl.py 里的 import Hsteel 正常解析
        dir_str = str(self.directory)
        if dir_str not in sys.path:
            sys.path.insert(0, dir_str)

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
            meta: TemplateMeta | None = getattr(obj, "__calcbook_template__", None)
            if meta is None or not callable(obj):
                continue
            meta.template_id = f"{stem}.{attr}"
            self.entries[meta.template_id] = TemplateEntry(
                meta=meta, file=path, hash=file_hash(path),
            )

    def _forget_dir_modules(self) -> None:
        """把从模板目录加载过的模块从 sys.modules 移除，保证刷新拿到新代码。"""
        stale = [
            name for name, mod in sys.modules.items()
            if getattr(mod, "__file__", None)
            and Path(mod.__file__).resolve().parent == self.directory
        ]
        for name in stale:
            sys.modules.pop(name, None)
