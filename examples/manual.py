"""示例模板：使用文档（把软件目录下的 Markdown 当计算书读）。

用途：把 docs/ 里的 Markdown 文档直接渲染进计算书预览区——左侧「文档」下拉选一篇，
右侧即该文档，可导出 HTML/PDF。它走的是普通模板的完整链路（下拉参数 → 防抖重算 →
预览与导出），没有一行专用界面代码。

文档来源：从本文件所在目录向上逐级找 docs/（便携版 app/examples/ → app/docs/，
源码仓库 CalcBook/examples/ → CalcBook/docs/），再退到当前工作目录下的 docs/。
扫到什么列什么——放哪些文档进 docs/ 由打包决定，模板不甄别、不排序分组。
"""

from __future__ import annotations

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
    """显示名 → 文件路径：递归扫 *.md，显示名取文件名（重名时带相对目录）。"""
    if docs is None:
        return {}
    files = sorted(docs.rglob("*.md"))
    found: dict[str, Path] = {}
    for path in files:
        name = path.stem
        if sum(1 for other in files if other.stem == name) > 1:
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
    if path is None:
        b.h1("使用文档")
        b.p("没有找到 docs/ 目录。把要展示的 Markdown 放进软件目录下的 docs/（模板目录"
            "的上一级），再点界面上的「刷新模板」。")
        return b
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        b.h1(path.stem)
        b.p(f"读取失败：{exc}")
        return b
    return b.markdown(text)
