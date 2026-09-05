"""示例模板：钢梁强度验算（最小可运行的契约样例）。

展示三件事：
1. Pydantic 模型 + Field 声明参数（label/unit/choices/group 驱动界面）；
2. @template 注册计算入口；
3. CalcBook 写计算书：符号公式 → 代入数值 → check 验算（自动结论表）。
"""

from pydantic import BaseModel

from calcbook import CalcBook, Field, template


class GLParams(BaseModel):
    """钢梁强度验算参数。"""

    # —— 材料（通用参数，批量时可整组统一设置）——
    steel: str = Field(
        "Q235B", label="钢材牌号", choices=["Q235B", "Q355B"], group="材料",
    )
    fy: float = Field(
        215, label="抗弯强度设计值", unit="N/mm²", group="材料", gt=0,
    )
    gamma_x: float = Field(
        1.05, label="截面塑性发展系数", group="截面", ge=1.0, le=1.25,
    )
    Wx: float = Field(
        1.0e6, label="截面模量", unit="mm³", group="截面", gt=0,
    )
    # —— 荷载（每根梁各自输入）——
    Mx: float = Field(
        100, label="弯矩设计值", unit="kN·m", group="荷载",
    )


@template("钢梁强度验算", description="GB 50017-2017 弯曲正应力验算（最小示例）")
def calc(p: GLParams) -> CalcBook:
    b = CalcBook(title="钢梁强度验算")
    sigma = p.Mx * 1e6 / (p.gamma_x * p.Wx)   # kN·m→N·mm：×1e6

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
