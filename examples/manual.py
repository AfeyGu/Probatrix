"""示例模板：使用文档（把软件目录下的 Markdown 当计算书读）。

用途：把 docs/ 里的 Markdown 文档直接渲染进计算书预览区——左侧「文档」下拉选一篇，
右侧即该文档，可导出 HTML/PDF。它走的是普通模板的完整链路（下拉参数 → 防抖重算 →
预览与导出），没有一行专用界面代码。

从本文件所在目录往上找 docs/，找不到再查看当前工作目录。docs/manual/ 的
编号手册排在前面，每篇文档从自己的目录读取配图。
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from pydantic import BaseModel

from probatrix import Probatrix, Field, template


def _docs_dir() -> Path | None:
    """软件目录下的 docs/：从本文件向上逐级找，退到当前工作目录。"""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        candidate = base / "docs"
        if candidate.is_dir():
            return candidate
    fallback = Path.cwd() / "docs"
    return fallback if fallback.is_dir() else None


def _scan(docs: Path | None) -> dict[str, Path]:
    """按文件名列出文档，用户手册排在前面，重名时带相对目录。"""
    if docs is None:
        return {}
    manual = docs / "manual"
    files = sorted(docs.rglob("*.md"), key=lambda path: (not path.is_relative_to(manual), path))
    counts = Counter(path.stem for path in files)
    found: dict[str, Path] = {}
    for path in files:
        name = path.stem
        if counts[name] > 1:
            name = path.relative_to(docs).with_suffix("").as_posix().replace("/", " / ")
        found[name] = path
    return found


_DOCS = _scan(_docs_dir())
_CHOICES = list(_DOCS)


class ManualParams(BaseModel):
    """文档浏览参数：只有「选哪一篇」。"""

    doc: str = Field(_CHOICES[0] if _CHOICES else "", label="文档", choices=_CHOICES)


@template("使用文档", description="浏览软件目录 docs/ 里的使用文档")
def calc(p: ManualParams) -> Probatrix:
    b = Probatrix()
    path = _DOCS.get(p.doc)
    if path is None and p.doc:
        # 已保存工程可能仍引用没有编号的篇名。
        matches = [candidate for name, candidate in _DOCS.items()
                   if re.sub(r"^\d{2}-", "", name) == p.doc]
        if len(matches) == 1:
            path = matches[0]
    if path is None:
        b.h1("使用文档")
        if _DOCS:
            b.p(f"没有找到文档「{p.doc}」。请从「文档」下拉框重新选择。")
        else:
            b.p("没有在 docs/ 下找到 Markdown 文档。放入文件后点「刷新模板」。")
        return b
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        b.h1(path.stem)
        b.p(f"读取失败：{exc}")
        return b
    return b.markdown(text, base_dir=path.parent)
