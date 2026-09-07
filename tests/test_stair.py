"""板式楼梯模板端到端：与原 xlsm 缓存值对账。

- 「模板」行与 2AT1 行（踏步 280×150）→ 与 xlsm 缓存值精确一致；
- 1ATa1 行（下铰上弹）→ 结构性校验（面层自重已按公式修正，不与原表
  硬编码值对齐）；
- 参数契约、超筋报错、选筋表无解报错。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from calcbook.engine import run_template

ROOT = Path(__file__).resolve().parent.parent


def _load_stair():
    path = ROOT / "examples" / "stair.py"
    spec = importlib.util.spec_from_file_location("stair", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stair"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def meta():
    return _load_stair().calc.__calcbook_template__


def _run(meta, name="", **params):
    r = run_template(meta, params, name=name)
    assert r.ok, r.error
    return r


# ----------------------------------------------------------------------
# 「模板」行：a=280 d=150 n=5 两端弹性 t=100 —— 与 xlsm 缓存值精确一致
# ----------------------------------------------------------------------
def test_default_row_matches_workbook(meta):
    r = _run(meta)
    checks = {c["name"]: c for c in r.checks}
    assert checks["A端支座裂缝宽度"]["value"] == pytest.approx(
        0.011831214259713832, rel=1e-6)
    assert checks["跨中裂缝宽度"]["value"] == pytest.approx(
        0.01892994281554213, rel=1e-6)
    assert checks["B端支座裂缝宽度"]["value"] == pytest.approx(
        0.011831214259713832, rel=1e-6)
    # 挠度 0.5578（原表 K206），限值 1.47/200×1000=7.35（原表 Q77）
    assert checks["跨中挠度"]["value"] == pytest.approx(
        0.5577694588072375, rel=1e-6)
    assert checks["跨中挠度"]["limit"] == pytest.approx(7.35)
    # 选筋：需求 200（ρmin 控制）→ 最小满足档 8@200 = 251.33
    # 名称作为项目编号传入；未传时显示「未命名」
    assert "未命名" in r.md
    assert r"\Phi8@200" in r.md
    # 批量表格指标列：三个截面配筋
    assert r.metrics == {"A端支座配筋": "Φ8@200", "跨中配筋": "Φ8@200",
                         "B端支座配筋": "Φ8@200"}
    assert r.all_ok is True


# ----------------------------------------------------------------------
# 2AT1 行：a=280 d=150 n=22 k=27 两端弹性 t=230 —— 手工独立复算锚定
# （l₀ 按意图公式修正为 6.36m，原表因 mm/m 量纲错取 6.468m，其余链路与原表一致）
# ----------------------------------------------------------------------
def test_2at1_row_matches_workbook(meta):
    r = _run(meta, name="2AT1", a=280, d=150, n=22, k_coef=27,
             support="两端弹性")
    checks = {c["name"]: c for c in r.checks}
    # l0 = min(6.16+0.2, 6.468) = 6.36（原表 6.468，量纲修正后的意图值）
    assert "= 6.36" in r.md
    # M_A = -18.631×6.36²/16 = -47.10 → As=658.5（>ρmin·b·h=460）
    # → 选 12@150=753.98；跨中 As=1045 → 12@100=1131
    assert r"\Phi12@150" in r.md
    assert r"\Phi12@100" in r.md
    # 裂缝（手算：ρte=0.01, cs=20，A端 σs=215.6, ψ=0.494）
    assert checks["A端支座裂缝宽度"]["value"] == pytest.approx(0.1356, rel=1e-3)
    assert checks["跨中裂缝宽度"]["value"] == pytest.approx(0.1558, rel=1e-3)
    # 挠度（手算 Bs≈1.219e13/2, f≈24.5），限值 6.36×5=31.8
    assert checks["跨中挠度"]["value"] == pytest.approx(24.5, rel=1e-2)
    assert checks["跨中挠度"]["limit"] == pytest.approx(31.8)
    assert r.all_ok is True


# ----------------------------------------------------------------------
# 1ATa1 行：下铰上弹 a=260 d=166.66 n=16 k=30 —— 结构性校验
# （面层自重按公式修正后荷载与原表略有差异，几何与选筋逻辑不变）
# ----------------------------------------------------------------------
def test_1ata1_row_hinged(meta):
    r = _run(meta, name="1ATa1", support="下铰上弹",
             a=260, d=166.66, n=16, k_coef=30)
    checks = {c["name"]: c for c in r.checks}
    assert r"= 140\ \mathrm{mm}" in r.md                      # ceil(4160/30/10)×10 = 140
    assert r"\Phi8@150" in r.md                       # A端 ρmin 控制 → 8@150
    assert "该截面弯矩为 0" in r.md                # A端铰支
    assert checks["A端支座裂缝宽度"]["value"] == pytest.approx(0.0, abs=1e-12)
    assert r.all_ok is True


# ----------------------------------------------------------------------
# 参数契约与异常路径
# ----------------------------------------------------------------------
def test_param_meta(meta):
    from calcbook import param_meta
    metas = {m["name"]: m for m in param_meta(meta.params_model)}
    assert metas["support"]["choices"] == ["两端弹性", "下铰上弹"]
    assert metas["support"]["group"] == "几何"
    assert metas["k_coef"]["default"] == 25
    assert metas["concrete"]["choices"][0] == "C25"
    assert metas["rebar"]["choices"] == ["HPB300", "HRB400", "HRB500"]


def test_over_reinforced_raises(meta):
    # t 最低 100mm + 特大活载 → αs≥0.5 超筋，报错进 RunResult.error
    r = run_template(meta, {"q_live": 300})
    assert not r.ok
    assert "超筋" in r.error


def test_bar_table_exhausted(meta):
    # 大跨 + 厚板 → 需求面积远超选筋表最大档
    r = run_template(meta, {"n": 60})
    assert not r.ok
    assert "选筋表" in r.error
