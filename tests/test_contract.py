"""契约验证：Field 元信息、@template 注册、CalcBook 渲染与 check 闭环、示例模板端到端。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from calcbook import CalcBook, Field, param_meta, template

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------
# Field / param_meta：声明即界面
# ----------------------------------------------------------------------
class DemoParams(BaseModel):
    steel: str = Field("Q235B", label="钢材牌号",
                       choices=["Q235B", "Q355B"], group="材料")
    fy: float = Field(215, label="抗弯强度设计值", unit="N/mm²", group="材料", gt=0)
    note: str = "无元信息的普通字段"


def test_param_meta_extracts_field_metadata() -> None:
    metas = param_meta(DemoParams)
    assert [m["name"] for m in metas] == ["steel", "fy", "note"]  # 按声明顺序
    steel, fy, note = metas
    assert steel["label"] == "钢材牌号"
    assert steel["choices"] == ["Q235B", "Q355B"]
    assert steel["group"] == "材料"
    assert steel["default"] == "Q235B"
    assert fy["unit"] == "N/mm²"
    # 无 Field 包装的字段也应出现在列表里（label 缺省）
    assert "label" not in note


# ----------------------------------------------------------------------
# @template：参数注解契约
# ----------------------------------------------------------------------
def test_template_attaches_meta() -> None:
    @template("演示模板", description="d", manual=True)
    def calc(p: DemoParams) -> CalcBook:
        return CalcBook()

    meta = calc.__calcbook_template__  # type: ignore[attr-defined]
    assert meta.name == "演示模板"
    assert meta.description == "d"
    assert meta.manual is True
    assert meta.params_model is DemoParams


def test_template_requires_pydantic_annotation() -> None:
    with pytest.raises(TypeError):
        @template("坏模板")
        def bad(p):  # 缺类型注解
            return CalcBook()


def test_template_run_and_validate() -> None:
    @template("运行模板")
    def calc(p: DemoParams) -> CalcBook:
        return CalcBook().p(p.steel)

    meta = calc.__calcbook_template__
    params = meta.make_params({"steel": "Q355B"})
    assert params.steel == "Q355B"
    with pytest.raises(ValidationError):
        meta.make_params({"fy": -1})


# ----------------------------------------------------------------------
# CalcBook：渲染与 check 闭环
# ----------------------------------------------------------------------
def test_calcbook_markdown_structure() -> None:
    b = CalcBook(title="T")
    b.h2("1. 验算")
    b.formula(r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"))
    b.subs(r"\sigma = 150.2")
    md = b.to_markdown()
    assert "# T" in md
    assert "## 1. 验算" in md
    assert "$$\\sigma \\le f$$" in md
    assert "> 依据：GB 50017-2017 第 4.1.1 条" in md
    assert "$$\\sigma = 150.2$$" in md


def test_check_pass_and_fail() -> None:
    b = CalcBook()
    b.check("抗弯强度", value=150.2, limit=215, unit="N/mm²")
    b.check("稳定", value=230, limit=215, unit="N/mm²")
    md = b.to_markdown()
    assert "**满足**" in md
    assert "**不满足**" in md
    # 应力比：150.2/215=0.6986→0.6986，230/215=1.0698
    assert "应力比 0.6986" in md
    assert "应力比 1.07" in md or "应力比 1.0698" in md
    # 末尾自动汇总表
    assert "验算项" in md and "应力比" in md and "结论" in md
    assert b.max_ratio == pytest.approx(230 / 215)
    assert b.all_ok is False


def test_check_ge_op() -> None:
    b = CalcBook()
    b.check("最小配筋", value=1.2, limit=1.0, op="ge")
    assert b.all_ok is True
    assert b.max_ratio == pytest.approx(1.0 / 1.2)  # ge 时 ratio=limit/value


def test_image_and_table() -> None:
    b = CalcBook()
    b.image("img/section.png", caption="截面简图")
    b.table(["A", "B"], [[1, 2]])
    md = b.to_markdown()
    assert "![截面简图](img/section.png)" in md
    assert "| A | B |" in md and "| 1 | 2 |" in md


def test_image_bytes_datauri() -> None:
    b = CalcBook()
    b.image_bytes(b"\x89PNG-fake", caption="简图")
    md = b.to_markdown()
    assert md.startswith("![简图](data:image/png;base64,")
    assert "iVBORy1mYWtl" in md           # b"\x89PNG-fake" 的 base64


# ----------------------------------------------------------------------
# 示例模板 gl.py 端到端
# ----------------------------------------------------------------------
def _load_example(name: str):
    path = ROOT / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_example_gl_end_to_end() -> None:
    mod = _load_example("gl")
    metas = [m.__calcbook_template__ for m in vars(mod).values()
             if hasattr(m, "__calcbook_template__")]
    assert len(metas) == 1
    meta = metas[0]
    assert meta.template_id == ""  # 加载器负责填，契约层不填

    # 参数走默认值 → 应满足
    book = meta.run(meta.make_params({}))
    md = book.to_markdown()
    assert "# 钢梁强度验算" in md
    assert "应力比 0.443" in md           # 100e6/(1.05*1e6)/215 ≈ 0.443
    assert "**满足**" in md
    assert book.all_ok is True
    assert "| 验算项" in md               # 自动结论汇总表

    # 超载 → 不满足
    book2 = meta.run(meta.make_params({"Mx": 500}))
    assert book2.all_ok is False
    assert "**不满足**" in book2.to_markdown()

    with pytest.raises(ValidationError):
        meta.make_params({"fy": 0})       # gt=0 生效
