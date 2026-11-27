"""示例模板：简支钢梁强度与挠度验算。

展示四件事：
1. Pydantic 模型 + Field 声明参数（label/unit/choices/group 驱动界面）；
2. @template 注册计算入口；
3. Probatrix 写计算书：符号公式 → 代入数值 → check 验算（自动结论表）；
4. 按牌号查表取强度、按弹性模量选项取值，并用 metric 在批量表显示结果。

计算模型：简支梁、跨中集中力。弯矩用设计值（荷载乘分项系数），
挠度用标准值（荷载不乘分项系数）。两种荷载的贡献分别计算后叠加。
"""

from pydantic import BaseModel

from probatrix import Probatrix, Field, template

#: 钢材牌号 → 抗弯强度设计值 f（N/mm²，常用板厚 ≤16mm）
STEEL_F = {"Q235B": 215.0, "Q355B": 305.0}
#: 界面选项 → 弹性模量 E（N/mm²）
E_TABLE = {"2.06×10⁵ N/mm²": 2.06e5}
#: 挠度限值选项 → 分母 n，允许挠度 = 跨度 L / n
DELTA_LIMIT = {"L/150": 150.0, "L/180": 180.0, "L/200": 200.0,
               "L/250": 250.0, "L/300": 300.0, "L/400": 400.0}


class GLParams(BaseModel):
    """简支钢梁强度与挠度验算参数。

    单位：L 用 m，q 用 kN/m，P 用 kN，W 用 mm³，I 用 mm⁴；
    计算时统一换算成 N 与 mm。模板内部不做自动单位换算引擎。
    """

    # —— 材料（通用参数，批量时可整组统一设置）——
    steel: str = Field(
        "Q235B", label="钢材牌号", choices=list(STEEL_F), group="材料",
    )
    E: str = Field(
        "2.06×10⁵ N/mm²", label="弹性模量 E", choices=list(E_TABLE), group="材料",
    )
    # —— 截面 ——
    gamma_x: float = Field(
        1.05, label="截面塑性发展系数", group="截面", ge=1.0, le=1.25,
    )
    W: float = Field(
        1.0e6, label="截面模量 W", unit="mm³", group="截面", gt=0,
    )
    I: float = Field(
        1.2e8, label="截面惯性矩 I", unit="mm⁴", group="截面", gt=0,
    )
    # —— 荷载（标准值，每根梁各自输入；不用的填 0）——
    L: float = Field(
        6.0, label="计算跨度 L", unit="m", group="荷载", gt=0,
    )
    q: float = Field(
        10, label="均布荷载标准值 q", unit="kN/m", group="荷载", ge=0,
    )
    P: float = Field(
        0, label="跨中集中力标准值 P", unit="kN", group="荷载", ge=0,
    )
    gamma_Q: float = Field(
        1.5, label="荷载分项系数", group="荷载", gt=0,
    )
    # —— 验算限值 ——
    delta_limit: str = Field(
        "L/200", label="挠度限值", choices=list(DELTA_LIMIT), group="验算",
    )


@template("简支梁验算", description="GB 50017-2017 弯曲正应力验算 + 简支梁挠度（强度用设计值，挠度用标准值）")
def calc(p: GLParams) -> Probatrix:
    b = Probatrix(title="简支梁验算")
    fy = STEEL_F[p.steel]                      # 按牌号查表，用户不用输
    E = E_TABLE[p.E]                           # 按下拉选项查表

    # 单位统一到 N、mm：q(kN/m) 数值等于 N/mm；P(kN) ×1000 → N；L(m) ×1000 → mm
    L = p.L * 1000.0
    q = p.q                                    # N/mm
    P = p.P * 1000.0                           # N

    # —— 弯矩（设计值：荷载乘分项系数）——
    Mq = p.gamma_Q * q * L * L / 8.0           # 均布荷载跨中弯矩，N·mm
    Mp = p.gamma_Q * P * L / 4.0               # 跨中集中力弯矩，N·mm
    M = Mq + Mp
    sigma = M / (p.gamma_x * p.W)              # N/mm²

    # —— 挠度（标准值：荷载不乘分项系数）——
    dq = 5.0 * q * L ** 4 / (384.0 * E * p.I)  # 均布荷载跨中挠度，mm
    dp = P * L ** 3 / (48.0 * E * p.I)         # 跨中集中力挠度，mm
    delta = dq + dp
    delta_allow = L / DELTA_LIMIT[p.delta_limit]  # 允许挠度 = L/n，mm

    b.h2("1. 计算条件")
    b.table(
        ["参数", "取值"],
        [
            ["钢材牌号", p.steel],
            ["抗弯强度设计值 f", f"{fy:g} N/mm²"],
            ["弹性模量 E", f"{E:,.0f} N/mm²"],
            ["截面模量 W", f"{p.W:,.0f} mm³"],
            ["截面惯性矩 I", f"{p.I:,.0f} mm⁴"],
            ["计算跨度 L", f"{p.L:g} m"],
            ["均布荷载标准值 q", f"{q:g} kN/m"],
            ["跨中集中力标准值 P", f"{p.P:g} kN"],
            ["荷载分项系数", f"{p.gamma_Q:g}"],
            ["挠度限值", f"{p.delta_limit}（L/{DELTA_LIMIT[p.delta_limit]:g}，即 {delta_allow:.2f} mm）"],
        ],
    )

    b.h2("2. 弯矩（设计值）")
    b.derive(
        r"M",
        r"\gamma_Q\left(\dfrac{qL^2}{8}+\dfrac{PL}{4}\right)",
        rf"{p.gamma_Q:g}\left(\dfrac{{{q:g}\times{L:g}^2}}{{8}}+\dfrac{{{P/1000:g}\times{L:g}}}{{4}}\right) = {M/1e6:.2f}\ \mathrm{{kN\cdot m}}",
    )
    b.p(f"其中均布荷载贡献 {Mq/1e6:.2f} kN·m，跨中集中力贡献 {Mp/1e6:.2f} kN·m。")

    b.h2("3. 强度验算")
    b.derive(
        r"\sigma",
        r"\dfrac{M}{\gamma_x W} \le f",
        rf"\dfrac{{{M/1e6:.2f}\times 10^6}}{{{p.gamma_x:.2f}\times{p.W:,.0f}}} = {sigma:.1f}\ \mathrm{{N/mm^2}}",
        cite=("GB 50017-2017", "4.1.1"),
    )
    b.check(
        "抗弯强度", value=sigma, limit=fy, unit="N/mm²",
        expr=r"\sigma \le f", cite=("GB 50017-2017", "4.1.1"),
    )

    b.h2("4. 挠度（标准值）")
    b.derive(
        r"\delta",
        r"\dfrac{5qL^4}{384EI}+\dfrac{PL^3}{48EI}",
        rf"\dfrac{{5\times{q:g}\times{L:g}^4}}{{384\times{E:,.0f}\times{p.I:,.0f}}}+\dfrac{{{P/1000:g}\times{L:g}^3}}{{48\times{E:,.0f}\times{p.I:,.0f}}} = {delta:.2f}\ \mathrm{{mm}}",
    )
    b.p(f"其中均布荷载贡献 {dq:.2f} mm，跨中集中力贡献 {dp:.2f} mm；挠度按标准值计算，不乘分项系数。")
    b.check(
        "跨中挠度", value=delta, limit=delta_allow, unit="mm",
        expr=r"\delta \le [\delta]",
    )

    b.metric("f (N/mm²)", f"{fy:g}")          # 批量表结果列：选牌号即见强度
    b.metric("M (kN·m)", f"{M/1e6:.2f}")      # 弯矩设计值
    b.metric("δ (mm)", f"{delta:.2f}")        # 挠度标准值
    return b
