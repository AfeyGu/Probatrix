"""模板：雨篷板计算（悬臂受弯，按 GB 50010-2010 (2015年版)）。

由《雨篷板计算.rtf》移植：
- 一、基本参数 → 「几何」参数组；
- 二、材性参数 → 「材料」参数组（按等级查表，混凝土/钢筋分离）；
- 三、弯矩计算 → 恒载（梯形板重 + 翻边重 + 面层）+ 活载 + 检修集中
  → 取活载/检修大值 → 1.3·恒 + 1.5·活 设计弯矩；
- 四、配筋计算（GB 50010-2010 第 6.2 节）→ αs→ξ→γs→As，再与
  ρmin·b·h 取大；按选筋表取严格大于 As需求 的最小档；
- 五、裂缝验算（GB 50010-2010 第 7.1 节）→ σs→ψ→ωmax ≤ 0.20 mm。

与 RTF 的一处偏差说明：
RTF 中活载/检修两者取大（Mk2），弯矩设计值用 1.3·Mk1 + 1.5·Mk2，
**没有**显式引入活载准永久值系数 ψq（GB 50010-2010 第 7.1.4 条的
裂缝计算本应用准永久组合 Mk1 + ψq·Mk2）。RTF 简化地用 Mk = Mk1 + Mk2
算钢筋应力 σs，本文按 RTF 的写法完整复刻；如设计人需按规范严格校核
裂缝，应自行乘 ψq（模板参数里已预留 `psi_q`，默认 0.5 用于手动套用）。
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from calcbook import CalcBook, Field, template

#: 运行本模板所需的导入名，用于界面检查依赖。Windows 便携包预装 matplotlib。
__calcbook_requires__ = ["matplotlib"]

# ----------------------------------------------------------------------
# 材料常数（等级 → 常数映射）
# ----------------------------------------------------------------------
#: 混凝土等级 → (fc 抗压强度设计值, ft 抗拉强度设计值, ftk 抗拉强度标准值,
#:                 Ec 弹性模量)，N/mm²
#: 《混凝土结构设计规范》GB 50010-2010 (2015年版) 表 4.1.3-1 / 4.1.4-1 / 4.1.5
CONCRETE: dict[str, tuple[float, float, float, float]] = {
    "C25": (11.9, 1.27, 1.78, 2.80e4),
    "C30": (14.3, 1.43, 2.01, 3.00e4),
    "C35": (16.7, 1.57, 2.20, 3.15e4),
    "C40": (19.1, 1.71, 2.39, 3.25e4),
    "C45": (21.1, 1.80, 2.51, 3.35e4),
    "C50": (23.1, 1.89, 2.64, 3.45e4),
}

#: 钢筋级别 → (fy 抗拉强度设计值, Es 弹性模量)
#: 注：ξb 由 α1/β1 与 εcu 在 calc 内按所选混凝土等级动态计算（GB 50010-2010 6.2.7-1）
REBAR: dict[str, tuple[float, float]] = {
    "HPB300": (270.0, 2.1e5),
    "HRB400": (360.0, 2.0e5),
    "HRB500": (435.0, 2.0e5),
}

#: 混凝土等级 → (α1, β1)，GB 50010-2010 第 6.2.6 条表
ALPHA_BETA: dict[str, tuple[float, float]] = {
    "C25": (1.00, 0.80),
    "C30": (1.00, 0.80),
    "C35": (1.00, 0.80),
    "C40": (1.00, 0.80),
    "C45": (1.00, 0.80),
    "C50": (1.00, 0.80),
}

# ----------------------------------------------------------------------
# 选筋表（直径 mm @ 间距 mm，按 b=1000mm 计算面积）
# 配筋原则：取面积严格大于 As需求 的最小档（同面积取表中靠前者，
# 与原 RTF "HRB400 8@150" = 335.1 mm² 风格一致）
# ----------------------------------------------------------------------
BAR_TABLE: list[tuple[int, int]] = [
    (8, 200), (8, 150), (8, 100),
    (10, 200), (10, 150), (10, 125), (10, 100),
    (12, 200), (12, 175), (12, 150), (12, 125), (12, 100),
    (8, 125),
]


# ----------------------------------------------------------------------
# 参数契约
# ----------------------------------------------------------------------
class CanopyParams(BaseModel):
    """雨篷板参数。「几何」每块板各自输入；材料、荷载与系数可整组统一设置。"""

    # —— 几何（每块雨篷板各自输入）——
    h1: float = Field(100, label="根部板厚 h1", unit="mm", gt=0, group="几何",
                     row="thick")
    h2: float = Field(80, label="端部板厚 h2", unit="mm", gt=0, group="几何",
                     row="thick")
    b: float = Field(60, label="翻边宽度 b", unit="mm", gt=0, group="几何",
                    row="flap")
    h3: float = Field(150, label="翻边高度 h3", unit="mm", gt=0, group="几何",
                     row="flap")
    L: float = Field(1000, label="挑出长度 L", unit="mm", gt=0, group="几何")

    # —— 材料 ——
    concrete: str = Field(
        "C30", label="混凝土等级",
        choices=list(CONCRETE), group="材料", batch_hidden=True, row="mat",
    )
    rebar: str = Field(
        "HRB400", label="钢筋等级",
        choices=list(REBAR), group="材料", batch_hidden=True, row="mat",
    )

    # —— 荷载与系数（批量时整组统一设置）——
    qq1: float = Field(
        0.50, label="板面粉刷(面层)荷载标准值", unit="kN/m²", gt=0,
        group="荷载与系数",
    )
    qq2: float = Field(
        1.50, label="活载/积水/雪载 标准值大值", unit="kN/m²", gt=0,
        group="荷载与系数",
    )
    F: float = Field(
        1.00, label="检修集中荷载标准值", unit="kN/m",
        group="荷载与系数",
        description="按 GB 50009 雨篷检修集中荷载 1.0 kN，距板端 1m 处",
    )
    gamma_g: float = Field(
        1.3, label="恒载分项系数 γG", gt=0,
        group="荷载与系数", batch_hidden=True, row="gamma",
    )
    gamma_q: float = Field(
        1.5, label="活载分项系数 γQ", gt=0,
        group="荷载与系数", batch_hidden=True, row="gamma",
    )
    psi_q: float = Field(
        0.5, label="活载准永久值系数 ψq", ge=0, le=1,
        group="荷载与系数", batch_hidden=True,
        description="按 RTF 复刻，裂缝 σs 用 Mk = Mk1 + Mk2 简化算；"
                    "如严格按 GB 50010 7.1.4 条应用 ψq 折减 Mk2 后再算 σs，"
                    "可手动用本参数（默认 0.5）",
    )
    rho_min_pct: float = Field(
        0.20, label="受弯构件最小配筋率 ρmin", unit="%", gt=0,
        group="荷载与系数", batch_hidden=True,
        description="GB 50010-2010 表 8.5.1；按板构件取 0.20% 与 45ft/fy 的较大值",
    )
    r_c: float = Field(
        25, label="混凝土容重 r", unit="kN/m³", gt=0,
        group="荷载与系数", batch_hidden=True, row="mix",
    )
    cover: float = Field(
        15, label="保护层厚度 c", unit="mm", gt=0,
        group="荷载与系数", batch_hidden=True, row="mix",
    )

    # —— 实配钢筋（裂缝校核用）——
    dia: float = Field(
        8, label="实配钢筋直径 d", unit="mm", gt=0, le=32,
        group="实配钢筋", row="bar",
        description="裂缝校核用；deq = d",
    )
    s: float = Field(
        150, label="实配钢筋间距 s", unit="mm", gt=0,
        group="实配钢筋", row="bar",
        description="按 b=1000mm 计算 As_实 = 1000·π·d²/(4s)",
    )


# ----------------------------------------------------------------------
# 计算入口
# ----------------------------------------------------------------------
@template(
    "雨篷板计算",
    description="悬臂雨篷板：荷载弯矩 + 配筋设计 + 裂缝验算（GB 50010-2010 2015年版）",
)
def calc(p: CanopyParams, *, name: str = "") -> CalcBook:
    """name：批量行的「名称」列，用作计算书的项目编号；未填时显示「未命名」。"""
    canopy_no = name or "未命名"
    fc, ft, ftk, Ec = CONCRETE[p.concrete]
    fy, Es = REBAR[p.rebar]
    alpha1, beta1 = ALPHA_BETA[p.concrete]
    epsilon_cu = 0.0033                          # GB 50010-2010 6.2.6-1
    xi_b = beta1 / (1.0 + fy / (epsilon_cu * Es)) # GB 50010-2010 公式 6.2.7-1

    # ---- 几何 ----
    L_m = p.L / 1000                              # 挑出长度 (m)

    # ---- 自重（kN/m²，板自重按厚度变化；翻边按线荷载 kN/m 沿板长分布）----
    q1 = p.r_c * p.h1 / 1000                     # 根部板重（kN/m²）
    q2 = p.r_c * p.h2 / 1000                     # 端部板重（kN/m²）
    Q3 = p.r_c * p.b * p.h3 / 1e6                # 翻边自重（kN/m，沿板长分布）

    # ---- 弯矩（kN·m/m 板宽）----
    # 恒载下弯矩标准值 Mk1：
    #   梯形板自重（端部 q2 均布 + 三角形部分 q1-q2）+ 面层均布 qq1
    #   + 翻边集中（端部线荷载 Q3 折算为集中）+ 翻边均布线荷载 0.5·Q3·L²
    #   注意：RTF 写法将翻边自重拆为「端部集中」+「均布线荷载」两项叠加（偏保守）
    Mk1 = (
        0.5 * q2 * L_m ** 2
        + (q1 - q2) * L_m ** 2 / 6.0
        + 0.5 * p.qq1 * L_m ** 2
        + Q3 * L_m
        + 0.5 * Q3 * L_m ** 2
    )
    # 活载下弯矩标准值
    Mkt1 = 0.5 * p.qq2 * L_m ** 2
    # 检修集中荷载下弯矩标准值（GB 50009：1.0 kN 作用于板端最不利位置）
    Mkt2 = p.F * L_m
    # 活载/检修取大
    Mk2 = max(Mkt1, Mkt2)
    # 弯矩标准值组合（用于裂缝 σs 计算；RTF 简化用 Mk = Mk1 + Mk2）
    Mk = Mk1 + Mk2
    # 弯矩设计值（基本组合）
    M = p.gamma_g * Mk1 + p.gamma_q * Mk2

    # ---- 截面有效高度 ----
    h0 = p.h1 - p.cover - 5                       # 配筋用（RTF 简化取 5mm）
    h0c = p.h1 - p.cover - p.dia / 2              # 裂缝用（按实配钢筋 d/2）

    # ---- 配筋（GB 50010-2010 第 6.2 节）----
    # 最小配筋面积 ρmin·b·h，按 GB 50010-2010 §8.5.1：max(0.20%, 45·ft/fy)
    # p.rho_min_pct 是百分数（0.20）；45·ft/fy 也是百分数（已×100）：直接比较
    rho_min = max(p.rho_min_pct, 45.0 * ft / fy)
    as_min = rho_min / 100.0 * 1000.0 * p.h1      # ρmin·b·h (mm²，b=1000mm)
    rho_max = xi_b * alpha1 * fc / fy * 100.0     # 最大配筋率（%）

    alpha_s = M * 1e6 / (alpha1 * fc * 1000 * h0 ** 2)
    if alpha_s >= 0.5:
        raise ValueError(
            f"αs={alpha_s:.3f} ≥ 0.5，截面超筋，请增大根部板厚 h1")
    xi = 1 - math.sqrt(max(1.0 - 2.0 * alpha_s, 0.0))
    gamma_s = 1 - 0.5 * xi
    as_calc = M * 1e6 / (fy * gamma_s * h0)
    as_des = max(as_calc, as_min)

    # 选筋
    best: tuple[int, int, float] | None = None
    for dia_, sp_ in BAR_TABLE:
        area_ = math.pi * dia_ ** 2 / 4.0 / sp_ * 1000.0
        if area_ > as_des and (best is None or area_ < best[2]):
            best = (dia_, sp_, area_)
    if best is None:
        raise ValueError(f"所需 As={as_des:.0f} mm² 超出选筋表最大档，请扩充选筋表")
    dia_pick, sp_pick, as_pick = best
    # 用户实配
    as_prov = math.pi * p.dia ** 2 / 4.0 / p.s * 1000.0
    deq = p.dia                                    # 等效直径（单一直径 → 等于 d）

    # ---- 裂缝（GB 50010-2010 第 7.1 节）----
    Ate = 0.5 * 1000.0 * p.h1                      # 有效受拉混凝土截面面积
    rte = max(as_prov / Ate, 0.01)                # ρte ≥ 0.01
    nu = 1.0                                       # HRB400 变形钢筋粘结特性系数
    sigma_s = Mk * 1e6 / (0.87 * h0c * as_prov)    # 钢筋等效应力（用 Mk 简化）
    psi = max(1.1 - 0.65 * ftk / (rte * sigma_s), 0.2)  # 受拉钢筋应变不均匀系数
    cs = min(max(p.cover, 20.0), 65.0)            # 保护层取值（GB 50010 表 7.1.2-1 注释）
    alpha_cr = 1.9                                  # 受弯构件受力特征系数
    w_max = (alpha_cr * psi * sigma_s / Es
             * (1.9 * cs + 0.08 * deq / rte))     # GB 50010-2010 公式 7.1.2-1
    w_lim = 0.20                                    # 裂缝宽度限值（mm）

    # ---- 计算书 ----
    b = CalcBook(title=f"雨篷板计算书 · {canopy_no}")
    b.metric("根部配筋", f"Φ{dia_pick}@{sp_pick}")
    b.metric("实配钢筋", f"Φ{int(p.dia)}@{int(p.s)}")
    b.metric("裂缝宽度", f"{w_max:.3f} mm")

    # 一、编号
    b.h2("一、编号")
    b.table(["项目", "内容"], [
        ["项目编号", canopy_no],
        ["计算依据", "《混凝土结构设计规范》GB 50010-2010（2015年版）"],
        ["构件类型", "悬臂雨篷板（根部嵌固于梁/墙）"],
    ])

    # 二、基本资料
    b.h2("二、基本资料")
    b.p("**几何参数**：雨篷板为变厚度悬臂板，根部厚度 h1，端部厚度 h2，"
        "挑出长度 L。翻边（侧封板）宽 b、高 h3，按线荷载计入恒载。")
    b.image_bytes(_section_fig(p.h1, p.h2, p.b, p.h3, p.L),
                  caption="雨篷板计算简图（侧剖面）")
    b.table(["参数", "取值", "参数", "取值"], [
        ["根部板厚 h1", f"{p.h1:g} mm", "混凝土等级", p.concrete],
        ["端部板厚 h2", f"{p.h2:g} mm", "钢筋等级", p.rebar],
        ["翻边宽度 b", f"{p.b:g} mm", "混凝土容重 r", f"{p.r_c:g} kN/m³"],
        ["翻边高度 h3", f"{p.h3:g} mm", "保护层厚度 c", f"{p.cover:g} mm"],
        ["挑出长度 L", f"{p.L:g} mm", "最小配筋率 ρmin", f"{p.rho_min_pct:g}%"],
        ["面层荷载 qq1", f"{p.qq1:g} kN/m²", "恒载分项系数 γG", f"{p.gamma_g:g}"],
        ["活载 qq2", f"{p.qq2:g} kN/m²", "活载分项系数 γQ", f"{p.gamma_q:g}"],
        ["检修集中 F", f"{p.F:g} kN/m", "活载准永久值系数 ψq", f"{p.psi_q:g}"],
    ])
    b.p("混凝土与钢筋力学指标（按所选等级查 GB 50010-2010 表 4.1.4-1 / 表 4.2.3-1）：")
    b.table(["指标", "数值", "依据"], [
        ["fc（混凝土抗压强度设计值）", f"{fc:g} N/mm²", "GB 50010-2010 表 4.1.4-1"],
        ["ftk（混凝土抗拉强度标准值）", f"{ftk:g} N/mm²", "GB 50010-2010 表 4.1.3-1"],
        ["Ec（混凝土弹性模量）", f"{Ec:.0f} N/mm²", "GB 50010-2010 表 4.1.5"],
        ["fy（钢筋抗拉强度设计值）", f"{fy:g} N/mm²", "GB 50010-2010 表 4.2.3-1"],
        ["Es（钢筋弹性模量）", f"{Es:.0f} N/mm²", "GB 50010-2010 表 4.2.4"],
        ["α1（受压区等效矩形应力图系数）", f"{alpha1:g}", "GB 50010-2010 §6.2.6"],
        ["β1（等效矩形受压区高度与中和轴高度比）", f"{beta1:g}", "GB 50010-2010 §6.2.6"],
        ["εcu（正截面混凝土极限压应变）", f"{epsilon_cu:g}", "GB 50010-2010 §6.2.6"],
    ])

    # 三、弯矩计算
    b.h2("三、弯矩计算")
    b.h3("1. 恒载")
    b.p("根部板重与端部板重（板自重按面积分布）：")
    b.derive(
        r"q_1",
        r"\dfrac{r \cdot h_1}{1000}",
        rf"\dfrac{{{p.r_c:g} \times {p.h1:g}}}{{1000}} = {q1:.2f}\ \mathrm{{kN/m^2}}",
    )
    b.derive(
        r"q_2",
        r"\dfrac{r \cdot h_2}{1000}",
        rf"\dfrac{{{p.r_c:g} \times {p.h2:g}}}{{1000}} = {q2:.2f}\ \mathrm{{kN/m^2}}",
    )
    b.p("翻边自重（按线荷载沿板长分布，作用在板端）：")
    b.derive(
        r"Q_3",
        r"\dfrac{r \cdot b \cdot h_3}{10^{6}}",
        rf"\dfrac{{{p.r_c:g} \times {p.b:g} \times {p.h3:g}}}{{10^{{6}}}} = {Q3:.2f}\ \mathrm{{kN/m}}",
    )

    b.h3("2. 恒载下弯矩标准值 Mk1")
    b.p("悬臂受弯，根部弯矩最大。恒载包括三部分：")
    b.p("**(a) 变厚度板自重**——梯形分布（端部 q2 均布 + 三角形 q1-q2）：")
    b.derive(
        r"M_{k1}^{(a)}",
        r"\dfrac{1}{2} q_2 L^2 + \dfrac{1}{6} (q_1 - q_2) L^2",
        rf"\dfrac{{1}}{{2}} \times {q2:.2f} \times {L_m:g}^2"
        rf" + \dfrac{{1}}{{6}} \times ({q1:.2f} - {q2:.2f}) \times {L_m:g}^2"
        rf" = {0.5 * q2 * L_m**2 + (q1 - q2) * L_m**2 / 6.0:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.p("**(b) 板面粉刷（面层）**——均布荷载：")
    b.derive(
        r"M_{k1}^{(b)}",
        r"\dfrac{1}{2} q_{q1} L^2",
        rf"\dfrac{{1}}{{2}} \times {p.qq1:g} \times {L_m:g}^2"
           rf" = {0.5 * p.qq1 * L_m**2:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.p("**(c) 翻边自重**——按 RTF 简化算法拆为端部集中力 + 均布线荷载（保守叠加）：")
    b.derive(
        r"M_{k1}^{(c)}",
        r"Q_3 L + \dfrac{1}{2} Q_3 L^2",
        rf"{Q3:.2f} \times {L_m:g} + \dfrac{{1}}{{2}} \times {Q3:.2f} \times {L_m:g}^2"
           rf" = {Q3 * L_m + 0.5 * Q3 * L_m**2:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.derive(
        r"M_{k1}",
        r"M_{k1}^{(a)} + M_{k1}^{(b)} + M_{k1}^{(c)} = "
        rf"{Mk1:.3f}\ \mathrm{{kN \cdot m/m}}",
    )

    b.h3("3. 活载下弯矩标准值")
    b.derive(
        r"M_{kt1}",
        r"\dfrac{1}{2} q_{q2} L^2",
        rf"\dfrac{{1}}{{2}} \times {p.qq2:g} \times {L_m:g}^2"
           rf" = {Mkt1:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.p("检修集中荷载（F 作用于板端最不利位置，弯矩 = F·L）：")
    b.derive(
        r"M_{kt2}",
        r"F L = "
        rf"{p.F:g} \times {L_m:g} = {Mkt2:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.p("取活载 / 检修弯矩大值作为 Mk2：")
    b.derive(
        r"M_{k2}",
        r"\max\{M_{kt1},\ M_{kt2}\}",
        rf"\max\{{{Mkt1:.3f},\ {Mkt2:.3f}\}} = {Mk2:.3f}\ \mathrm{{kN \cdot m/m}}",
    )

    b.h3("4. 弯矩组合")
    b.derive(
        r"M_k",
        r"M_{k1} + M_{k2} \qquad (\text{标准值组合，用于裂缝验算})",
        rf"{Mk1:.3f} + {Mk2:.3f} = {Mk:.3f}\ \mathrm{{kN \cdot m/m}}",
    )
    b.derive(
        r"M",
        r"\gamma_G M_{k1} + \gamma_Q M_{k2} \qquad (\text{基本组合，用于配筋})",
        rf"{p.gamma_g:g} \times {Mk1:.3f} + {p.gamma_q:g} \times {Mk2:.3f}"
           rf" = {M:.3f}\ \mathrm{{kN \cdot m/m}}",
    )

    # 四、配筋计算
    b.h2("四、配筋计算")
    b.p("按单筋矩形截面计算，截面有效高度（按钢筋单层布置假定）：")
    b.derive(
        r"h_0",
        r"h_1 - c - 5 = "
        rf"{p.h1:g} - {p.cover:g} - 5 = {h0:g}\ \mathrm{{mm}}",
    )

    b.h3("1. 界限相对受压区高度 ξb")
    b.derive(
        r"\xi_b",
        r"\dfrac{\beta_1}{1 + \dfrac{f_y}{\varepsilon_{cu} E_s}}",
        rf"\dfrac{{{beta1:g}}}{{1 + \dfrac{{{fy:g}}}{{{epsilon_cu:g} \times {Es:.0f}}}}} = {xi_b:.3f}",
        cite=("GB 50010-2010", "6.2.7-1"),
    )

    b.h3("2. 最小 / 最大配筋率")
    b.p("受弯构件最小配筋率取 0.20% 与 45·ft/fy 的较大值（GB 50010-2010 §8.5.1）；"
        f"此处 $f_t = {ft:g}\\ \\mathrm{{N/mm^2}}$（GB 50010-2010 表 4.1.4-1）。")
    b.formula(
        r"\rho_{\min} = \max\left\{0.20\%,\ \dfrac{45 f_t}{f_y}\right\}",
        cite=("GB 50010-2010", "8.5.1"),
    )
    _rmin_left = r"\max\left\{"
    _rmin_right = r"\right\}"
    b.subs(rf"\rho_{{\min}} = {_rmin_left}0.20\%,\ \dfrac{{45 \times {ft:g}}}{{{fy:g}}}{_rmin_right}"
           rf" = {rho_min:.3f}\%")
    b.derive(
        r"\rho_{\max}",
        r"\dfrac{\xi_b \alpha_1 f_c}{f_y}",
        rf"\dfrac{{{xi_b:.3f} \times {alpha1:g} \times {fc:g}}}{{{fy:g}}}"
           rf" = {rho_max:.3f}\%",
        cite=("GB 50010-2010", "6.2.7-1"),
    )
    b.check("配筋率上界", value=rho_min, limit=rho_max, unit="%",
            op="le", expr=r"\rho_{\min} \le \rho_{\max}",
            cite=("GB 50010-2010", "6.2.7-1"))
    b.p(f"最小配筋面积：$A_{{s,\\min}} = \\rho_{{\\min}} b h = "
        f"{rho_min:.3f}\\% \\times 1000 \\times {p.h1:g} = {as_min:.1f}\\ \\mathrm{{mm^2}}$。")

    b.h3("3. 受弯承载力计算")
    b.derive(
        r"\alpha_s",
        r"\dfrac{M}{\alpha_1 f_c b h_0^2}",
        rf"\dfrac{{{M * 1e6:.0f}}}{{{alpha1:g} \times {fc:g} \times 1000 \times {h0:g}^2}}"
           rf" = {alpha_s:.4f}",
        cite=("GB 50010-2010", "6.2.10-1"),
    )
    b.derive(
        r"\xi",
        r"1 - \sqrt{1 - 2 \alpha_s} = "
        rf"1 - \sqrt{{1 - 2 \times {alpha_s:.4f}}} = {xi:.4f}",
    )
    b.check("相对受压区高度", value=xi, limit=xi_b,
            expr=r"\xi \le \xi_b",
            cite=("GB 50010-2010", "6.2.10-4"))
    b.derive(
        r"\gamma_s",
        r"1 - 0.5 \xi = "
        rf"1 - 0.5 \times {xi:.4f} = {gamma_s:.4f}",
    )
    b.derive(
        r"A_s",
        r"\dfrac{M}{f_y \gamma_s h_0}",
        rf"\dfrac{{{M * 1e6:.0f}}}{{{fy:g} \times {gamma_s:.4f} \times {h0:g}}}"
           rf" = {as_calc:.1f}\ \mathrm{{mm^2}}",
        cite=("GB 50010-2010", "6.2.10-2"),
    )
    b.p("按最小配筋率控制取大：")
    b.derive(
        r"A_{s,\mathrm{des}}",
        r"\max\{A_s,\ A_{s,\min}\}",
        rf"\max\{{{as_calc:.1f},\ {as_min:.1f}\}} = {as_des:.1f}\ \mathrm{{mm^2}}",
    )
    b.p(f"查选筋表取严格大于 $A_{{s,\\mathrm{{des}}}}$ 的最小档："
        f"$\\Phi{dia_pick}@{sp_pick}$，实配面积 $A_{{s,\\text{{实}}}} = {as_pick:.1f}\\ \\mathrm{{mm^2}}$。")
    b.check("最小配筋控制", value=as_pick, limit=as_min,
            op="ge", expr=r"A_{s,\text{实}} \ge A_{s,\min}", unit="mm²",
            cite=("GB 50010-2010", "8.5.1"))

    # 五、裂缝验算
    b.h2("五、裂缝验算")
    b.p("按标准值组合（RTF 简化用 $M_k = M_{k1} + M_{k2}$，严格按规范应取准永久组合）"
        "校核最大裂缝宽度，限值 $[\\omega] = 0.20\\ \\mathrm{mm}$（GB 50010-2010 表 3.4.5，"
        "二 a 类环境，钢筋混凝土受弯构件）。")
    b.p("**实配钢筋**（用于裂缝校核）："
        f"$\\Phi{int(p.dia)}@{int(p.s)}$，"
        f"$A_{{s,\\text{{实}}}} = 1000 \\times \\pi d^2 / (4s) = "
        f"{as_prov:.1f}\\ \\mathrm{{mm^2}}$，等效直径 $d_{{eq}} = d = {deq:g}\\ \\mathrm{{mm}}$。")
    b.p("截面有效高度（按实配钢筋直径）：")
    b.derive(
        r"h_{0,c}",
        r"h_1 - c - d/2 = "
        rf"{p.h1:g} - {p.cover:g} - {p.dia:g}/2 = {h0c:g}\ \mathrm{{mm}}",
    )

    b.h3("1. 钢筋等效应力 σs")
    b.derive(
        r"\sigma_s",
        r"\dfrac{M_k}{0.87\, h_{0,c}\, A_{s,\text{实}}}",
        rf"\dfrac{{{Mk * 1e6:.0f}}}{{0.87 \times {h0c:g} \times {as_prov:.1f}}}"
           rf" = {sigma_s:.2f}\ \mathrm{{N/mm^2}}",
        cite=("GB 50010-2010", "7.1.4-2"),
    )

    b.h3("2. 受拉钢筋应变不均匀系数 ψ")
    b.p("有效受拉混凝土截面面积 $A_{{te}} = 0.5 b h = 0.5 \\times 1000 \\times "
        f"{p.h1:g}\\ \\mathrm{{mm^2}}$；配筋率 $\\rho_{{te}} = A_{{s,\\text{{实}}}} / A_{{te}}$，"
        f"小于 0.01 时取 0.01。")
    b.formula(r"\rho_{te} = \max\left\{\dfrac{A_{s,\text{实}}}{A_{te}},\ 0.01\right\}")
    _rte_left = r"\max\left\{"
    _rte_right = r"\right\}"
    b.subs(rf"\rho_{{te}} = {_rte_left}\dfrac{{{as_prov:.1f}}}{{{Ate:.0f}}},\ 0.01{_rte_right} = {rte:.4f}")
    b.derive(
        r"\psi",
        r"1.1 - \dfrac{0.65\, f_{tk}}{\rho_{te}\, \sigma_s}",
        rf"1.1 - \dfrac{{0.65 \times {ftk:g}}}{{{rte:.4f} \times {sigma_s:.2f}}}"
           rf" = {1.1 - 0.65 * ftk / (rte * sigma_s):.4f}",
        cite=("GB 50010-2010", "7.1.2-4"),
    )
    b.p("$\\psi$ 应在 $[0.2, 1.0]$ 区间内（GB 50010-2010 §7.1.2 第 4 款），"
        f"此处取 $\\psi = {psi:.3f}$。")

    b.h3("3. 最大裂缝宽度 ωmax")
    b.p("保护层厚度取值：$c_s = \\min(\\max(c, 20), 65)$ mm（GB 50010-2010 表 7.1.2-1 注释）；"
        f"钢筋粘结特性系数 $\\nu = 1.0$（HRB400 变形钢筋）；"
        f"构件受力特征系数 $\\alpha_{{cr}} = 1.9$（受弯构件）。")
    _cs_left = r"\min\{\max("
    _cs_right = r"),\ 65\}"
    b.derive(
        r"c_s",
        r"\min\{\max(c, 20), 65\} = "
        rf"{_cs_left}{p.cover:g}, 20{_cs_right} = {cs:g}\ \mathrm{{mm}}",
    )
    b.derive(
        r"\omega_{\max}",
        r"\alpha_{cr}\, \psi\, \dfrac{\sigma_s}{E_s}\left( 1.9\, c_s + 0.08\, \dfrac{d_{eq}}{\rho_{te}} \right)",
        rf"{alpha_cr:g} \times {psi:.3f} \times \dfrac{{{sigma_s:.2f}}}{{{Es:.0f}}}"
           rf" \times \left(1.9 \times {cs:g} + 0.08 \times \dfrac{{{deq:g}}}{{{rte:.4f}}}\right)"
           rf" = {w_max:.3f}\ \mathrm{{mm}}",
        cite=("GB 50010-2010", "7.1.2-1"),
    )
    b.check("最大裂缝宽度", value=w_max, limit=w_lim, unit="mm",
            expr=r"\omega_{\max} \le [\omega]=0.20",
            cite=("GB 50010-2010", "7.1.2-1"))

    b.p("注：本模板按 RTF 复刻，裂缝 σs 采用标准值组合 $M_k = M_{k1} + M_{k2}$；"
        "如严格按 GB 50010-2010 §7.1.4 条，应改用准永久组合 $M_q = M_{k1} + \\psi_q M_{k2}$，"
        "相关参数 $\\psi_q$ 已在「荷载与系数」组预留，可手工调整后重新计算。")

    return b


# ----------------------------------------------------------------------
# 计算简图（matplotlib 侧剖面：悬臂变厚度板 + 翻边 + 荷载 + 尺寸标注）
# ----------------------------------------------------------------------
def _section_fig(h1: float, h2: float, b_: float, h3: float,
                 L: float) -> bytes:
    """生成雨篷板侧剖面计算简图 PNG（全部尺寸单位为 mm）。"""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon, Rectangle

    old_font = matplotlib.rcParams["font.sans-serif"]
    old_uminus = matplotlib.rcParams["axes.unicode_minus"]
    try:
        matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        matplotlib.rcParams["axes.unicode_minus"] = False

        fig, ax = plt.subplots(figsize=(10, 5.2))
        x_wall = -180.0                       # 嵌固墙左边界
        top = h1
        bot_end = h1 - h2
        # 板轮廓：顶面水平 y=h1，底面从墙边 (0,0) 斜到端部 (L, h1-h2)
        slab = Polygon(
            [(x_wall, top), (L, top), (L, bot_end), (0, 0.0), (x_wall, 0.0)],
            closed=True, facecolor="#dce8f5", edgecolor="black", lw=1.4,
        )
        ax.add_patch(slab)
        # 墙（嵌固支座，阴影区）
        wall = Rectangle((x_wall, -30), 150, h1 + 130,
                         facecolor="#e8e8e8", edgecolor="black", lw=1.2,
                         hatch="//", zorder=1)
        ax.add_patch(wall)
        # 固端约束符号（墙与板交界面三条斜线，加粗置顶层）
        for k in (-30, 40, 110):
            ax.plot([-30, 0], [k, k + 30], color="black", lw=1.6, zorder=5)
        ax.text(-95, h1 + 140, "固端（嵌固）", ha="center",
                fontsize=8.5, color="#555555")
        # 翻边（端部顶部，宽 b、高 h3）
        rim = Rectangle((L, top), b_, h3, facecolor="#dce8f5",
                        edgecolor="black", lw=1.4)
        ax.add_patch(rim)
        # 板底坡度线（标注 i）
        ax.plot([0, L], [0, bot_end], color="black", lw=0)

        # ---- 尺寸标注 ----
        ax.annotate("", xy=(0, top), xytext=(x_wall + 60, top),
                    arrowprops=dict(arrowstyle="<->", color="black"))
        ax.text((0 + x_wall + 60) / 2, top + 16, "挑出长度 L", ha="center")
        ax.annotate("", xy=(0, 0), xytext=(0, top),
                    arrowprops=dict(arrowstyle="<->", color="black"))
        ax.text(-70, top / 2, "h1", ha="right", va="center")
        ax.annotate("", xy=(L, bot_end), xytext=(L, top),
                    arrowprops=dict(arrowstyle="<->", color="black"))
        ax.text(L + 15, (top + bot_end) / 2, "h2", va="center")
        ax.annotate("", xy=(L + b_, top), xytext=(L, top),
                    arrowprops=dict(arrowstyle="<->", color="black"))
        ax.text(L + b_ / 2 + 22, top + 22, "b", ha="center", fontsize=9)
        ax.annotate("", xy=(L + b_, top + h3), xytext=(L + b_, top),
                    arrowprops=dict(arrowstyle="<->", color="black"))
        ax.text(L + b_ + 32, top + h3 / 2, "h3", va="center", fontsize=9)
        # 坡度
        if h2 < h1:
            i = (h1 - h2) / L * 100
            ax.text(L / 2, -46, rf"坡度 $i = {i:.2f}\%$（上平下斜，排水）",
                    ha="center", fontsize=9)

        # ---- 荷载（箭头一律贴板顶面、指向板内）----
        # 面层荷载 qq1（板面均布，向下，标签靠左）
        n_q1 = 4
        xs1 = [60 + i * (L - 120) / n_q1 for i in range(n_q1 + 1)]
        for x in xs1:
            ax.annotate("", xy=(x, top - 6), xytext=(x, top + 10),
                        arrowprops=dict(arrowstyle="->", color="#1f77b4",
                                        lw=1.5))
        ax.text(L * 0.25, top + 16, "面层荷载", ha="center", color="#1f77b4",
                fontsize=9, bbox=dict(boxstyle="round,pad=0.15", fc="white",
                                      ec="none", alpha=0.85))
        ax.text(L * 0.25, top + 26, r"$q_{q1}$", ha="center", color="#1f77b4",
                fontsize=9)
        # 活荷载 qq2（板面均布，向下，标签靠右）
        n_q2 = 4
        xs2 = [60 + i * (L - 120) / n_q2 for i in range(n_q2 + 1)]
        for x in xs2:
            ax.annotate("", xy=(x, top - 6), xytext=(x, top + 40),
                        arrowprops=dict(arrowstyle="->", color="#d62728",
                                        lw=1.5))
        ax.text(L * 0.75, top + 46, "活荷载", ha="center", color="#d62728",
                fontsize=9, bbox=dict(boxstyle="round,pad=0.15", fc="white",
                                      ec="none", alpha=0.85))
        ax.text(L * 0.75, top + 56, r"$q_{q2}$", ha="center", color="#d62728",
                fontsize=9)
        # 检修集中荷载 F（端部，标数值与作用位置；标签放翻边正上方避开 h3）
        fx = L + b_ / 2
        ax.annotate("", xy=(fx, top - 4), xytext=(fx, top + h3 + 30),
                    arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.6))
        ax.text(fx, top + h3 + 40, r"检修 $F$（kN/m）", ha="center",
                color="#2ca02c", fontsize=9)
        ax.text(fx, top + h3 + 32, r"作用于端部", ha="center",
                color="#2ca02c", fontsize=8)

        # ---- 控制截面标注 ----
        ax.plot([x_wall + 60, x_wall + 60], [0, top], color="#7f7f7f",
                lw=0.8, ls="--")
        ax.text(x_wall + 60, -18, "控制截面（根部）", ha="center",
                fontsize=9, color="#7f7f7f")

        # ---- 图例 ----
        legend = (
            f"图例：板自重 $q_1,q_2$；翻边 $Q_3$；面层 $q_{{q1}}$"
            f"；活/雪/积水 $q_{{q2}}$；检修集中 $F$\n"
            f"荷载组合：$M_k = M_{{k1}}+M_{{k2}}$（标准值），"
            f"$M = \\gamma_G M_{{k1}} + \\gamma_Q M_{{k2}}$（基本组合）"
        )
        ax.text(0.5, -0.06, legend, transform=ax.transAxes, ha="center",
                va="top", fontsize=8.5, color="#333333")

        ax.set_xlim(x_wall - 60, L + b_ + 100)
        ax.set_ylim(-105, max(top, h1) + h3 + 180)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title("雨篷板计算简图（尺寸单位：mm）")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    finally:
        matplotlib.rcParams["font.sans-serif"] = old_font
        matplotlib.rcParams["axes.unicode_minus"] = old_uminus
