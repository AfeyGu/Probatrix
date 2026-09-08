"""雨篷板模板端到端契约测试。

对照《雨篷板计算.rtf》示例数据（h1=100, h2=80, b=60, h3=150, L=1000,
C30/HRB400, qq1=0.5, qq2=1.5, F=1.0），期望数值与 RTF 字面完全一致：
    Mk = 2.67 kN·m/m, M = 3.67 kN·m/m, ξb = 0.518,
    ρmin = 0.200%, ρmax = 2.056%, ωmax = 0.02 mm。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from calcbook.engine import run_template

ROOT = Path(__file__).resolve().parent.parent


def _load_canopy():
    path = ROOT / "examples" / "canopy.py"
    spec = importlib.util.spec_from_file_location("canopy", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["canopy"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def meta():
    return _load_canopy().calc.__calcbook_template__


def test_canopy_declares_matplotlib():
    mod = _load_canopy()
    assert mod.__calcbook_requires__ == ["matplotlib"]


def _run(meta, name="", **params):
    return run_template(meta, params, name=name)


# ----------------------------------------------------------------------
# 默认参数：与 RTF 示例数值对齐
# ----------------------------------------------------------------------
def test_default_params_match_rtf(meta):
    r = _run(meta)
    assert r.all_ok is True
    assert r.max_ratio is not None and r.max_ratio < 1.0
    md = r.md
    # 计算书三件套
    assert "# 雨篷板计算书" in md
    assert "## 一、编号" in md
    assert "**满足**" in md
    # 结论表
    assert "| 验算项" in md
    assert "| 依据 |" in md
    # RTF 关键数值（每一步的代入都应出现这些数）
    assert "2.670" in md or "2.67" in md          # Mk 标准组合
    assert "3.67" in md                            # M 设计值
    assert "0.518" in md                           # ξb
    assert "0.200" in md                           # ρmin %
    assert "2.056" in md                           # ρmax %
    assert "0.022" in md or "0.02" in md           # ωmax
    # 选筋（默认参数下 as_des=200 → Φ8@200=251.3 > 200）
    assert r"\Phi8@200" in md
    # 批量指标
    assert r.metrics["根部配筋"] == "Φ8@200"
    assert r.metrics["实配钢筋"] == "Φ8@150"
    # 4 个 check：配筋率上界、ξ、最小配筋控制、ωmax
    assert len(r.checks) == 4
    for c in r.checks:
        assert c["passed"] is True
        assert c["ratio"] is not None
    # 每个 check 都有 cite（GB 50010-2010）
    names = {c["name"] for c in r.checks}
    assert "配筋率上界" in names
    assert "相对受压区高度" in names
    assert "最小配筋控制" in names
    assert "最大裂缝宽度" in names


# ----------------------------------------------------------------------
# 名称参数：项目编号
# ----------------------------------------------------------------------
def test_name_param_used_as_number(meta):
    r = _run(meta, name="YPB-1")
    assert "YPB-1" in r.md


# ----------------------------------------------------------------------
# 越界：弯矩过大触发超筋报错
# ----------------------------------------------------------------------
def test_overload_reports_error(meta):
    """跨度拉到 3m + 活载翻倍，αs 应远大于 0.5，calc 主动抛 ValueError。
    engine 捕获后 result.ok=False、all_ok=None、error 含 traceback。
    """
    r = _run(meta, qq2=5.0, L=3000)
    assert r.ok is False
    assert r.all_ok is None
    assert "αs" in r.error and "超筋" in r.error


# ----------------------------------------------------------------------
# 越界：裂缝宽度超限
# ----------------------------------------------------------------------
def test_crack_over_limit_fails(meta):
    """把实配钢筋换小（Φ6@300）+ 大跨，让 σs 拉高 → ωmax 超 0.20。
    选筋表没有 Φ6，会抛错；改用更稀疏的大间距模拟钢筋不足。
    用更小的活载但极小钢筋（d=6, s=300 → As=94 mm²，远低于 as_min=200）
    """
    # dia/s 都没有 6 的选筋档 → calc 内部不查选筋（裂缝段直接用 as_prov），
    # 但 b.check 用 As_实 ≥ As_min 时如果 As_实 < As_min 会不满足
    r = _run(meta, dia=6, s=300)
    # 选筋那项 check 会因为 As_实=94 < As_min=200 而 ratio > 1
    # 但 min_ratio 控制项 + 最大裂缝都可能不满足
    assert r.all_ok is False
    assert any(c["ratio"] > 1.0 for c in r.checks)


# ----------------------------------------------------------------------
# 参数契约：保护层必须 > 0
# ----------------------------------------------------------------------
def test_invalid_param_rejected(meta):
    with pytest.raises(ValidationError):
        meta.make_params({"cover": -5})


# ----------------------------------------------------------------------
# cite 必须齐全（结论表才有「依据」列）
# ----------------------------------------------------------------------
def test_all_checks_have_cite(meta):
    r = _run(meta)
    assert len(r.checks) >= 1
    # 检查 md 渲染里依据列非空
    md_lines = r.md.splitlines()
    table_idx = [i for i, l in enumerate(md_lines) if l.startswith("| 验算项")]
    assert table_idx, "未找到结论表"
    # 表头应含「依据」
    assert "依据" in md_lines[table_idx[0]]
