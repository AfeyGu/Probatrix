"""模板第三方依赖机制：__probatrix_requires__ 声明收集、环境检查、
运行前拦截与 ModuleNotFoundError 兜底。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import BaseModel

from probatrix import Field              # 契约 Field（吸收 label 等扩展键）
from probatrix.engine import run_template
from probatrix.loader import TemplateLoader, check_deps
from probatrix.server import create_app
from probatrix.template import TemplateMeta

#: 保证环境中不存在的模块名
MISSING = "probatrix_definitely_missing_xyz_12345"

TPL = """\
from __future__ import annotations
from pydantic import BaseModel
from probatrix import Probatrix, Field, template

__probatrix_requires__ = {requires}

class P(BaseModel):
    a: float = Field(1.0, label="a")

@template("依赖测试", description="")
def calc(p: P) -> Probatrix:
    b = Probatrix()
    b.p("ok")
    return b
"""


class _P(BaseModel):
    a: float = Field(1.0, label="a")


def _write_tpl(tmp_path: Path, requires: str) -> None:
    (tmp_path / "t.py").write_text(
        TPL.format(requires=requires), encoding="utf-8")


def _first_entry(ld: TemplateLoader):
    assert len(ld.entries) == 1, [e.error for e in ld.errors]
    return next(iter(ld.entries.values()))


# ----------------------------------------------------------------------
# ① 契约层：声明收集 + 环境检查
# ----------------------------------------------------------------------
def test_check_deps() -> None:
    assert check_deps(["pydantic", MISSING]) == [MISSING]
    assert check_deps([]) == []


def test_loader_collects_requires_and_checks(tmp_path: Path) -> None:
    _write_tpl(tmp_path, f'["pydantic", "{MISSING}"]')
    ld = TemplateLoader(tmp_path)
    ld.scan()
    e = _first_entry(ld)
    assert e.meta.requires == ["pydantic", MISSING]
    assert e.meta.missing_deps == [MISSING]      # pydantic 已装


def test_loader_without_declaration(tmp_path: Path) -> None:
    _write_tpl(tmp_path, "[]")
    ld = TemplateLoader(tmp_path)
    ld.scan()
    e = _first_entry(ld)
    assert e.meta.requires == []
    assert e.meta.missing_deps == []


# ----------------------------------------------------------------------
# ② 运行层：缺依赖拦截 + ModuleNotFoundError 兜底
# ----------------------------------------------------------------------
def test_run_blocks_missing_deps(tmp_path: Path) -> None:
    _write_tpl(tmp_path, f'["{MISSING}"]')
    ld = TemplateLoader(tmp_path)
    ld.scan()
    res = run_template(_first_entry(ld).meta, {})
    assert not res.ok
    assert res.error_title == "缺少依赖"
    assert MISSING in res.error
    assert "pip install" in res.error
    assert res.md == ""                          # 模板未执行


def test_run_module_not_found_hint() -> None:
    def boom(p: _P):
        raise ModuleNotFoundError(
            "No module named 'matplotlib'", name="matplotlib")

    res = run_template(TemplateMeta(name="X", func=boom, params_model=_P), {})
    assert not res.ok
    assert res.error_title == "缺少依赖"
    assert "matplotlib" in res.error
    assert "pip install matplotlib" in res.error


def test_module_not_found_hint_from_traceback() -> None:
    """e.name 为 None 时从 traceback 的 No module named '...' 兜底解析。"""
    def boom(p: _P):
        raise ModuleNotFoundError("No module named 'numpy'")

    res = run_template(TemplateMeta(name="X", func=boom, params_model=_P), {})
    assert res.error_title == "缺少依赖"
    assert "numpy" in res.error


def test_other_exceptions_keep_traceback() -> None:
    def boom(p: _P):
        raise ValueError("参数不合理")

    res = run_template(TemplateMeta(name="X", func=boom, params_model=_P), {})
    assert res.error_title == "计算出错"
    assert "ValueError" in res.error             # 原始 traceback 保留


# ----------------------------------------------------------------------
# API 层：模板列表/运行报告依赖
# ----------------------------------------------------------------------
def test_server_reports_missing_deps(tmp_path: Path) -> None:
    _write_tpl(tmp_path, f'["{MISSING}"]')
    c = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    t = c.get("/api/templates").json()["templates"][0]
    assert t["requires"] == [MISSING]
    assert t["missing_deps"] == [MISSING]
    s = c.get("/api/templates/t.calc/schema").json()
    assert s["missing_deps"] == [MISSING]
    r = c.post("/api/run", json={"template_id": "t.calc", "params": {}})
    assert r.json()["error_title"] == "缺少依赖"
