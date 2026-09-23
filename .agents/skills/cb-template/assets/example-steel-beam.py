"""示例模板：钢梁强度验算（GB 50017-2017 4.1.1 弯曲正应力）。

由 cb-template skill 自带 —— 展示模板的完整形态：
- Pydantic + Field 声明（label / unit / choices / group）
- @template 注册（含 manual / description）
- CalcBook 写书（h2 / table / formula / subs / check）
- 至少一个 check（让 max_ratio 有效）
- 公式 → 代入 → 判定 三件套

直接运行：
    pip install calcbook pydantic
    python example-steel-beam.py
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from calcbook import CalcBook, Field, template


class GLParams(BaseModel):
    """钢梁强度验算参数。"""

    # —— 材料（整组统一设置）——
    steel: str = Field(
        "Q235B", label="钢材牌号",
        choices=["Q235B", "Q355B"], group="材料",
    )
    fy: float = Field(
        215, label="抗弯强度设计值 f", unit="N/mm²",
        group="材料", gt=0,
    )

    # —— 截面（每根梁不同或统一设置，按习惯）——
    gamma_x: float = Field(
        1.05, label="截面塑性发展系数 γx",
        group="截面", ge=1.0, le=1.25,
    )
    Wx: float = Field(
        1.0e6, label="截面模量 Wx", unit="mm³",
        group="截面", gt=0,
    )

    # —— 荷载（每根梁不同）——
    Mx: float = Field(
        100, label="弯矩设计值 Mx", unit="kN·m",
        group="荷载",
    )


@template(
    "钢梁强度验算",
    description="GB 50017-2017 第 4.1.1 条 弯曲正应力验算（最小示例）",
)
def calc(p: GLParams) -> CalcBook:
    b = CalcBook(title="钢梁强度验算")
    sigma = p.Mx * 1e6 / (p.gamma_x * p.Wx)        # kN·m → N·mm

    b.h2("1. 计算条件")
    b.table(
        ["参数", "取值"],
        [
            ["钢材牌号", p.steel],
            ["抗弯强度设计值 f", f"{p.fy:g} N/mm²"],
            ["截面模量 Wx", f"{p.Wx:,.0f} mm³"],
            ["弯矩设计值 Mx", f"{p.Mx:g} kN·m"],
        ],
    )

    b.h2("2. 强度验算")
    b.formula(
        r"\sigma = \dfrac{M_x}{\gamma_x W_x} \le f",
        cite=("GB 50017-2017", "4.1.1"),
    )
    b.subs(
        rf"\sigma = \dfrac{{{p.Mx:g} \times 10^6}}"
        rf"{{{p.gamma_x:.2f} \times {p.Wx:,.0f}}}"
        rf"= {sigma:.1f}\ \mathrm{{N/mm^2}}",
    )
    b.check(
        "抗弯强度", value=sigma, limit=p.fy, unit="N/mm²",
        expr=r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"),
    )
    return b


# ----------------------------------------------------------------------
# 自检（无 pytest 时也能跑）
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("gl", __file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    meta = next(
        m.__calcbook_template__
        for m in vars(mod).values()
        if hasattr(m, "__calcbook_template__")
    )

    # 默认参数 → 应满足
    book = meta.run(meta.make_params({}))
    print(f"max_ratio = {book.max_ratio:.4f}")
    print(f"all_ok    = {book.all_ok}")
    assert book.all_ok, "默认参数应满足"
    assert 0.4 < book.max_ratio < 0.5, f"比值应在 0.4~0.5，实测 {book.max_ratio}"

    # 越界 → 应不满足
    book2 = meta.run(meta.make_params({"Mx": 500}))
    print(f"Mx=500    : all_ok = {book2.all_ok}, max_ratio = {book2.max_ratio:.4f}")
    assert not book2.all_ok, "Mx=500 应不满足"
    assert book2.max_ratio > 1.0

    print("\n--- 计算书 Markdown 已生成，完整内容请在 CalcBook 界面查看 ---")
    # 写到文件避免 Windows console 编码问题
    Path(__file__).with_name("example-steel-beam_output.md").write_text(
        book.to_markdown(), encoding="utf-8"
    )
    print(f"已写入：{Path(__file__).with_name('example-steel-beam_output.md')}")
