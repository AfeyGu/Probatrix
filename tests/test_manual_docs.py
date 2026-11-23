"""示例模板 manual.py：把软件目录 docs/ 下的 Markdown 当计算书读。

验证三件事：下拉选项来自 docs/ 实际文件、选中文档渲染成计算书正文、
文档目录缺失或选区无效时给可读提示而不是 traceback。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from probatrix.engine import run_template
from probatrix.loader import TemplateLoader

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
MANUAL_NAMES = (
    "01-使用说明", "02-模板开发指南", "03-模板快速开始",
    "04-参数输入界面", "05-计算与验算", "06-计算书排版",
)
TOPICS = MANUAL_NAMES[2:]


def _load() -> tuple[object, object]:
    """重新导入模板模块，返回 (module, meta)。"""
    path = EXAMPLES / "manual.py"
    spec = importlib.util.spec_from_file_location("manual_doc_tpl", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["manual_doc_tpl"] = module
    spec.loader.exec_module(module)
    metas = [getattr(obj, "__probatrix_template__", None)
             for obj in vars(module).values()]
    metas = [m for m in metas if m is not None]
    assert len(metas) == 1
    return module, metas[0]


def test_choices_come_from_docs_dir() -> None:
    module, meta = _load()
    field = meta.params_model.model_fields["doc"]
    choices = field.json_schema_extra["choices"]
    assert choices[:len(MANUAL_NAMES)] == list(MANUAL_NAMES)
    assert field.default == "01-使用说明"
    assert all(isinstance(p, Path) for p in module._DOCS.values())


def test_default_doc_renders_its_own_body() -> None:
    """默认项（下拉第一项）就能跑出正文——打开模板即有内容，不需先选。"""
    _, meta = _load()
    result = run_template(meta, {})
    assert result.ok
    assert "<h1>使用说明</h1>" in result.html
    assert "定义自己的计算工具" in result.html
    assert result.md.startswith("# 使用说明")


def test_legacy_manual_choice_still_renders() -> None:
    _, meta = _load()
    legacy = run_template(meta, {"doc": "使用说明"})
    numbered = run_template(meta, {"doc": "01-使用说明"})
    assert legacy.ok and numbered.ok
    assert legacy.html == numbered.html
    assert "<pre><code class='language-powershell'>" in legacy.html
    assert "<ol><li>" in legacy.html


def test_dev_guide_indexes_all_topics() -> None:
    _, meta = _load()
    result = run_template(meta, {"doc": "02-模板开发指南"})
    assert result.ok
    assert "<h1>模板开发指南</h1>" in result.html
    for doc in TOPICS:
        assert f"<code>{doc}</code>" in result.html
        assert f"[{doc}]({doc}.md)" in result.md


@pytest.mark.parametrize("doc", TOPICS)
def test_topic_renders_its_own_body(doc: str) -> None:
    _, meta = _load()
    result = run_template(meta, {"doc": doc})
    assert result.ok
    title = doc.split("-", 1)[1]
    assert f"<h1>{title}</h1>" in result.html
    assert "<h2>" in result.html
    assert "language-python" in result.html
    source = (ROOT / "docs" / "manual" / f"{doc}.md").read_text(encoding="utf-8")
    assert result.md.rstrip() == source.rstrip()


@pytest.mark.parametrize(("doc", "n_images"), [("03-模板快速开始", 2), ("06-计算书排版", 1)])
def test_manual_embeds_its_screenshots(doc: str, n_images: int) -> None:
    _, meta = _load()
    result = run_template(meta, {"doc": doc})
    assert result.ok
    assert result.html.count("data:image/png;base64,") == n_images


def test_unknown_doc_gives_readable_hint() -> None:
    _, meta = _load()
    result = run_template(meta, {"doc": "不存在的文档"})
    assert result.ok
    assert "没有找到文档「不存在的文档」" in result.html


def test_scan_tolerates_missing_docs_dir() -> None:
    module, _ = _load()
    assert module._scan(None) == {}


def test_loader_registers_template_with_hash() -> None:
    loader = TemplateLoader(EXAMPLES)
    loader.scan()
    assert loader.errors == []
    entry = loader.entries["manual.calc"]
    assert entry.meta.name == "使用文档"
    assert len(entry.hash) == 64
