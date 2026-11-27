"""示例模板：钢梁强度验算（入门样例，最小可运行的契约样例）。

展示四件事：
1. Pydantic 模型 + Field 声明参数（label/unit/choices/group 驱动界面）；
2. @template 注册计算入口；
3. Probatrix 写计算书：符号公式 → 代入数值 → check 验算（自动结论表）；
4. 按牌号查表取强度（不作为输入参数），并用 metric 在批量表显示。

荷载算弯矩与挠度的进阶版本见同目录的 gl_beam.py。
"""

from pydantic import BaseModel

from probatrix import Probatrix, Field, template

#: 钢材牌号 → 抗弯强度设计值 f（N/mm²，常用板厚 ≤16mm）
STEEL_F = {"Q235B": 215.0, "Q355B": 305.0}


class GLParams(BaseModel):
    """钢梁强度验算参数。"""

    # —— 材料（通用参数，批量时可整组统一设置）——
    steel: str = Field(
        "Q235B", label="钢材牌号", choices=list(STEEL_F), group="材料",
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


@template("钢梁强度验算", description="GB 50017-2017 弯曲正应力验算（入门示例）")
def calc(p: GLParams) -> Probatrix:
    b = Probatrix(title="钢梁强度验算")
    fy = STEEL_F[p.steel]                      # 按牌号自动取强度，用户不用输
    sigma = p.Mx * 1e6 / (p.gamma_x * p.Wx)   # kN·m→N·mm：×1e6

    b.h2("1. 计算条件")
    b.table(
        ["参数", "取值"],
        [
            ["钢材牌号", p.steel],
            ["抗弯强度设计值 f", f"{fy:g} N/mm²"],
            ["截面模量 Wx", f"{p.Wx:,.0f} mm³"],
            ["弯矩设计值 Mx", f"{p.Mx:g} kN·m"],
        ],
    )

    b.h2("2. 强度验算")
    b.derive(
        r"\sigma",
        r"\dfrac{M_x}{\gamma_x W_x} \le f",
        rf"\dfrac{{{p.Mx:g} \times 10^6}}{{{p.gamma_x:.2f} \times {p.Wx:,.0f}}} = {sigma:.1f}\ \mathrm{{N/mm^2}}",
        cite=("GB 50017-2017", "4.1.1"),
    )
    b.check(
        "抗弯强度", value=sigma, limit=fy, unit="N/mm²",
        expr=r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"),
    )
    b.metric("f (N/mm²)", f"{fy:g}")  # 批量表结果列：选牌号即见强度，便于核对
    return b
