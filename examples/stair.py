"""模板：板式楼梯计算（现浇梯段板）。

由《楼梯计算 v1.xlsm》移植：
- 「设置」表（通用参数 + 选筋表）→ CalcBook 参数组 + 模块内置选筋表；
- 「列表」表（每跑楼梯一行）→ 批量行参数（支座形式做成下拉菜单）；
- 「模板」sheet（计算书）→ 下面的计算书章节，计算内容一一对应：
  1. 梯段板荷载（三角形踏步 / 板厚 / 面层 / 底面抹灰 / 栏杆，水平投影每 m²）；
  2. 基本组合与准永久组合；
  3. 弯矩（支座形式：两端弹性 / 下铰上弹，查弯矩系数）；
  4. 配筋（αs→ξ→γs→As，与 ρmin·b·h 取大，查选筋表取严格大于 As 的最小档）；
  5. 裂缝宽度（A 支座 / 跨中 / B 支座，准永久组合）；
  6. 挠度（考虑踏步刚度的长期刚度，准永久组合）。

与原表的三处修正（结果更正确）：
- 面层 / 底面抹灰自重原表是按 a=280、d=150 写死的数值，踏步尺寸不同的楼梯
  一直沿用错值；此处按公式现算；
- 原表「配筋率检验」行引用了空单元格（G943 笔误）恒显示满足；此处改为
  「实配 As ≥ ρmin·b·h」的真实验算项（结果不变，最小配筋由 max() 强制）；
- 计算跨度原表把 0.5bA 以 mm 数值直接加到 m 上（量纲错），导致所有楼梯恒取
  1.05lₙ；按示意图标注的意图公式 min{lₙ+(bA+bB)/2, 1.05lₙ} 修正后，短楼梯
  （lₙ<4m，如「模板」行）结果与原表一致，长楼梯计算跨度略小、弯矩略小
  （支座中心距本就短于 1.05lₙ，如 lₙ=6.16m 时取 6.36m 而非 6.468m）。

另外：原表荷载组合为 1.3·g+1.5·q（γ0 未乘入），此处保持一致，γ0 仅列出。
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from calcbook import CalcBook, Field, template

# ----------------------------------------------------------------------
# 材料常数（等级 → 常数映射）
# ----------------------------------------------------------------------
#: 混凝土等级 → (fc 抗压强度设计值, ftk 抗拉强度标准值, Ec 弹性模量)，N/mm²
#: 《混凝土结构设计标准》GB/T 50010-2010(2024年版)
CONCRETE: dict[str, tuple[float, float, float]] = {
    "C25": (11.9, 1.78, 2.80e4),
    "C30": (14.3, 2.01, 3.00e4),
    "C35": (16.7, 2.20, 3.15e4),
    "C40": (19.1, 2.39, 3.25e4),
    "C45": (21.1, 2.51, 3.35e4),
    "C50": (23.1, 2.64, 3.45e4),
}

#: 钢筋级别 → (fy 抗拉强度设计值, Es 弹性模量, ξb 界限相对受压区高度)
REBAR: dict[str, tuple[float, float, float]] = {
    "HPB300": (270.0, 2.1e5, 0.576),
    "HRB400": (360.0, 2.0e5, 0.518),
    "HRB500": (435.0, 2.0e5, 0.482),
}

# ----------------------------------------------------------------------
# 选筋表（原「设置」sheet 选筋区，直径 mm @ 间距 mm）
# 配筋原则：取面积严格大于 As需求 的最小档；同面积取表中靠前者
# （与原表 SMALL+MATCH 行为一致，如 8@100 与 8@125 同面积时取 8@100）
# ----------------------------------------------------------------------
BAR_TABLE: list[tuple[int, int]] = [
    (8, 200), (8, 150), (8, 100),
    (10, 200), (10, 150), (10, 100),
    (12, 200), (12, 175), (12, 150), (12, 125), (12, 100),
    (10, 125), (8, 125),
]

#: 计算 h0 用的最大钢筋直径：原表选筋区含 16mm 预留行（MAX(d)=16），保持一致
D_MAX_H0: float = 16.0

#: 支座形式 → 弯矩系数分母 (A支座, 跨中, B支座)；0 表示铰支（该处弯矩为 0）
MOMENT_COEF: dict[str, tuple[float, float, float]] = {
    "两端弹性": (16.0, 10.0, 16.0),
    "下铰上弹": (0.0, 320.0 / 39.0, 32.0 / 3.0),
}

#: 支座形式 → 挠度系数（f = 系数 · p准 · l0⁴ / Bl）
DEFLECT_COEF: dict[str, float] = {
    "两端弹性": 0.5 * (1 / 384 + 5 / 384),      # = 1/128
    "下铰上弹": 0.5 * (0.00542 + 5 / 384),
}


# ----------------------------------------------------------------------
# 参数契约：声明即界面（label/unit/choices/group 驱动表单与批量表格列）
# ----------------------------------------------------------------------
class StairParams(BaseModel):
    """板式楼梯参数。「几何」逐跑输入；材料、荷载与系数可整组统一设置。"""

    # —— 楼梯几何（每跑各自输入）——
    support: str = Field(
        "两端弹性", label="支座形式",
        choices=["两端弹性", "下铰上弹"], group="几何",
    )
    a: float = Field(280, label="踏步宽度 a", unit="mm", gt=0, group="几何")
    d: float = Field(150, label="踏步高度 d", unit="mm", gt=0, group="几何")
    n: int = Field(5, label="踏步数 n", ge=1, group="几何")
    L1: float = Field(0, label="A端折板长度 L1", unit="mm", ge=0, group="几何")
    L2: float = Field(0, label="B端折板长度 L2", unit="mm", ge=0, group="几何")
    B: float = Field(1200, label="梯段板宽度 B", unit="mm", gt=0, group="几何")
    g_rail: float = Field(
        0.5, label="两侧栏板(杆)线荷载标准值 g", unit="kN/m", ge=0, group="几何",
    )
    k_coef: float = Field(
        25, label="梯板系数 k", gt=0, group="几何",
        description="梯段板厚 t = 向上取整10mm[(a·n+L1+L2)/k]，且 ≥100mm",
    )

    # —— 材料 ——
    concrete: str = Field(
        "C30", label="混凝土等级",
        choices=list(CONCRETE), group="材料",
    )
    rebar: str = Field(
        "HRB400", label="楼梯纵筋级别",
        choices=list(REBAR), group="材料",
    )

    # —— 荷载与系数（批量时整组统一设置）——
    q_live: float = Field(3.5, label="楼梯活荷载标准值 q", unit="kN/m²", gt=0,
                          group="荷载与系数")
    gamma0: float = Field(1.0, label="结构重要性系数 γ0", gt=0,
                          group="荷载与系数")
    gamma_g: float = Field(1.3, label="恒载分项系数 γG", gt=0,
                           group="荷载与系数")
    gamma_q: float = Field(1.5, label="活载分项系数 γQ", gt=0,
                           group="荷载与系数")
    psi_q: float = Field(0.4, label="活载准永久值系数 ψq", ge=0, le=1,
                         group="荷载与系数")
    step_factor: float = Field(
        0.2, label="踏步刚度系数 λ", ge=0, group="荷载与系数",
        description="挠度计算的等效截面高度 h0'=h0+λ·d·cosα 中的系数",
    )
    rho_min: float = Field(0.2, label="楼梯最小配筋率 ρmin", unit="%", gt=0,
                           group="荷载与系数")
    t1: float = Field(30, label="楼梯面层厚度 t1", unit="mm", ge=0,
                      group="荷载与系数")
    r1: float = Field(22, label="楼梯面层容重 r1", unit="kN/m³", gt=0,
                      group="荷载与系数")
    t2: float = Field(20, label="底面抹灰厚度 t2", unit="mm", ge=0,
                      group="荷载与系数")
    r2: float = Field(18, label="底面抹灰容重 r2", unit="kN/m³", gt=0,
                      group="荷载与系数")
    r_c: float = Field(25, label="混凝土容重 r", unit="kN/m³", gt=0,
                       group="荷载与系数")
    cover: float = Field(15, label="保护层厚度 c", unit="mm", gt=0,
                         group="荷载与系数")
    b_a: float = Field(200, label="A端支座宽度 bA", unit="mm", gt=0,
                       group="荷载与系数")
    b_b: float = Field(200, label="B端支座宽度 bB", unit="mm", gt=0,
                       group="荷载与系数")


# ----------------------------------------------------------------------
# 计算入口
# ----------------------------------------------------------------------
@template(
    "板式楼梯计算",
    description="现浇板式楼梯梯段板：荷载、配筋、裂缝与挠度（GB/T 50010-2010 2024年版）",
)
def calc(p: StairParams, *, name: str = "") -> CalcBook:
    """name：批量行的「名称」列，用作计算书的项目编号；未填时显示「未命名」。"""
    stair_no = name or "未命名"
    fc, ftk, Ec = CONCRETE[p.concrete]
    fy, Es, xi_b = REBAR[p.rebar]

    # ---- 几何 ----
    alpha = math.atan(p.d / p.a)                     # 梯段板倾角 (rad)
    cos_a = math.cos(alpha)
    L_hor = p.a * p.n                                # 踏步段水平长度 L = a·n (mm)
    t = max(math.ceil((L_hor + p.L1 + p.L2) / p.k_coef / 10) * 10, 100)  # 板厚(mm)
    l_n = (L_hor + p.L1 + p.L2) / 1000               # 净跨 (m)
    l0 = min(l_n + (p.b_a + p.b_b) / 2000, 1.05 * l_n)  # 计算跨度 (m)

    # ---- 荷载（kN/m²，水平投影）----
    g1 = p.r_c * p.d / 2000                          # 三角形踏步 r·d/2
    g2 = t / 1000 * p.r_c / cos_a                    # 板厚自重
    g3 = (p.a + p.d) / p.a * p.t1 / 1000 * p.r1      # 面层（踏步平+立面）
    g4 = p.t2 / 1000 * p.r2 / cos_a                  # 底面抹灰
    g5 = p.g_rail / (p.B / 1000) / cos_a             # 栏杆（线荷载摊到板宽）
    g_k = g1 + g2 + g3 + g4 + g5
    p_u = p.gamma_g * g_k + p.gamma_q * p.q_live     # 基本组合（γ0 未乘入，同原表）
    p_qp = g_k + p.psi_q * p.q_live                  # 准永久组合

    # ---- 弯矩（kN·m / m 板宽）----
    c_a, c_m, c_b = MOMENT_COEF[p.support]
    def _mom(pv: float) -> tuple[float, float, float]:
        m_a = 0.0 if c_a == 0 else -pv * l0 ** 2 / c_a
        m_m = pv * l0 ** 2 / c_m
        m_b = 0.0 if c_b == 0 else -pv * l0 ** 2 / c_b
        return m_a, m_m, m_b
    m_a, m_m, m_b = _mom(p_u)
    m_a_qp, m_m_qp, m_b_qp = _mom(p_qp)

    # ---- 配筋 ----
    h0 = t - p.cover - D_MAX_H0 / 2                  # 截面有效高度 (mm)
    as_min = p.rho_min / 100 * 1000 * t              # ρmin·b·h (b=1000mm)

    def _design(m_des: float) -> tuple[float, float, float, float]:
        """|M| (kN·m/m) → (αs, ξ, γs, As计算值)；弯矩为 0 时按最小配筋控制。"""
        if m_des <= 0:
            return 0.0, 0.0, 1.0, 0.0
        alpha_s = m_des * 1e6 / (1.0 * fc * 1000 * h0 ** 2)
        if alpha_s >= 0.5:
            raise ValueError(
                f"αs={alpha_s:.3f} ≥ 0.5，截面超筋，请增大梯段板厚度 t")
        xi = 1 - math.sqrt(1 - 2 * alpha_s)
        gamma_s = 1 - 0.5 * xi
        as_c = m_des * 1e6 / (fy * gamma_s * h0)
        return alpha_s, xi, gamma_s, as_c

    def _pick(as_req: float) -> tuple[int, int, float]:
        """选筋表里取面积严格大于 as_req 的最小档（同面积取表中靠前者）。"""
        best: tuple[int, int, float] | None = None
        for dia, sp in BAR_TABLE:
            area = math.pi * dia ** 2 / 4 / sp * 1000
            if area > as_req and (best is None or area < best[2]):
                best = (dia, sp, area)
        if best is None:
            raise ValueError(f"所需 {as_req:.0f} mm² 超出选筋表最大档，请扩充选筋表")
        return best

    def _crack(m_qp: float, as_prov: float, deq: float) -> dict[str, float]:
        """裂缝宽度计算（准永久组合）。返回 ρte/σs/ψ/cs/w_max/h0c。"""
        h0c = t - p.cover - deq / 2
        rte = max(as_prov / (0.5 * p.B * t), 0.01)
        if m_qp == 0 or as_prov <= 0:
            return dict(rte=rte, sig=0.0, psi=0.0,
                        cs=min(max(p.cover, 20.0), 65.0), w=0.0, h0c=h0c)
        sig = abs(m_qp) * 1e6 / (0.87 * h0c * as_prov)
        psi = min(max(1.1 - 0.65 * ftk / (rte * sig), 0.2), 1.0)
        cs = min(max(p.cover, 20.0), 65.0)
        w = 1.9 * psi * sig / Es * (1.9 * cs + 0.08 * deq / rte)
        return dict(rte=rte, sig=sig, psi=psi, cs=cs, w=w, h0c=h0c)

    # 三个截面的配筋与裂缝
    secs = []
    for tag, m_u, m_q in (("A端支座", m_a, m_a_qp),
                          ("跨中", m_m, m_m_qp),
                          ("B端支座", m_b, m_b_qp)):
        alpha_s, xi, gamma_s, as_c = _design(abs(m_u))
        as_des = max(as_c, as_min)
        dia, sp, area_req = _pick(as_des)
        as_prov = math.pi * dia ** 2 / 4 / sp * 1000
        crack = _crack(m_q, as_prov, float(dia))
        secs.append(dict(tag=tag, m=m_u, m_q=m_q, alpha_s=alpha_s, xi=xi,
                         gamma_s=gamma_s, as_c=as_c, as_des=as_des,
                         dia=dia, sp=sp, as_prov=as_prov, **crack))
    mid = secs[1]

    # ---- 挠度（跨中）----
    h0_d = t - p.cover - mid["dia"] / 2              # 截面有效高度（实配筋）
    rte_d = max(mid["as_prov"] / (0.5 * 1000 * t), 0.01)
    sig_d = mid["m_q"] * 1e6 / (0.87 * h0_d * mid["as_prov"])
    psi_d = min(max(1.1 - 0.65 * ftk / (rte_d * sig_d), 0.2), 1.0)
    a_e = Es / Ec
    rho_d = mid["as_prov"] / (1000 * h0_d)
    h0_step = h0_d + p.step_factor * p.d * cos_a     # 考虑踏步刚度后的等效高度
    b_s = Es * mid["as_prov"] * h0_step ** 2 / (1.15 * psi_d + 0.2 + 6 * a_e * rho_d)
    b_l = b_s / 2                                    # 长期刚度（θ=2）
    f = DEFLECT_COEF[p.support] * p_qp * l0 ** 4 * 1e12 / b_l
    f_lim = l0 * 1000 / 200

    def n2(v: float) -> str:
        return f"{v:.2f}"

    def n3(v: float) -> str:
        return f"{v:.3f}"

    # ---- 计算书 ----
    b = CalcBook(title=f"楼梯计算书 · {stair_no}")
    for s in secs:
        b.metric(f"{s['tag']}配筋", f"Φ{s['dia']}@{s['sp']}")

    b.h2("一、编号")
    b.table(["项目", "内容"], [
        ["项目编号", stair_no],
        ["支座形式", p.support],
        ["计算依据", "《混凝土结构设计标准》GB/T 50010-2010（2024年版）"],
    ])

    b.h2("二、计算示意图")
    b.image(_IMG_SECTION, caption="梯段板计算示意图")
    b.p("尺寸符号：a—踏步宽度；d—踏步高度；n—踏步数；t—梯段板厚度；"
        "L=a·n—踏步段水平长度；L1/L2—A端/B端折板长度；bA/bB—支座宽度；"
        "H=(n+1)·d—梯段总高度。①梯段纵筋 ②分布筋 ③支座负筋。")

    b.h2("三、基本资料")
    b.h3("1. 设计依据")
    b.p("《混凝土结构设计标准》GB/T 50010-2010（2024年版）。")
    b.h3("2. 计算条件")
    b.table(["参数", "取值", "参数", "取值"], [
        ["支座形式", p.support, "结构重要性系数 γ0", f"{p.gamma0:g}"],
        ["踏步宽度 a", f"{p.a:g} mm", "恒载分项系数 γG", f"{p.gamma_g:g}"],
        ["踏步高度 d", f"{p.d:g} mm", "活载分项系数 γQ", f"{p.gamma_q:g}"],
        ["踏步数 n", f"{p.n:g}", "活载准永久值系数 ψq", f"{p.psi_q:g}"],
        ["A端折板长度 L1", f"{p.L1:g} mm", "最小配筋率 ρmin", f"{p.rho_min:g}%"],
        ["B端折板长度 L2", f"{p.L2:g} mm", "面层厚度 t1 / 容重 r1",
         f"{p.t1:g} mm / {p.r1:g} kN/m³"],
        ["梯段板宽度 B", f"{p.B:g} mm", "抹灰厚度 t2 / 容重 r2",
         f"{p.t2:g} mm / {p.r2:g} kN/m³"],
        ["栏板(杆)线荷载 g", f"{p.g_rail:g} kN/m", "混凝土容重 r",
         f"{p.r_c:g} kN/m³"],
        ["A/B端支座宽度 bA/bB", f"{p.b_a:g} / {p.b_b:g} mm",
         "保护层厚度 c", f"{p.cover:g} mm"],
        ["活荷载标准值 q", f"{p.q_live:g} kN/m²", "混凝土等级", p.concrete],
        ["梯板系数 k", f"{p.k_coef:g}", "纵筋级别", p.rebar],
        ["踏步刚度系数 λ", f"{p.step_factor:g}", "梯段板厚度 t（按 k 估算）",
         f"{t:g} mm"],
    ])
    b.p("梯段板厚度按经验公式估算：板厚 = 向上取整10mm[(a·n+L1+L2)/k]，且不小于 100mm。")
    b.formula(r"t = \max\left\{\left\lceil \dfrac{a n + L_1 + L_2}{10\,k} \right\rceil \times 10,\ 100\right\}")
    b.subs(rf"t = \max\left\{{\left\lceil \dfrac{{{p.a:g} \times {p.n:g} + {p.L1:g} + {p.L2:g}}}{{10 \times {p.k_coef:g}}} \right\rceil \times 10,\ 100\right\}} = {t:g}\ \mathrm{{mm}}")
    b.p(f"注：γ0={p.gamma0:g} 仅列出；荷载组合与原表一致，未乘入 γ0。")

    b.h2("四、梯段板荷载计算")
    b.p("荷载均按水平投影面每平方米计。梯段板倾斜角：")
    b.formula(r"\alpha = \arctan \dfrac{d}{a}")
    b.subs(rf"\alpha = \arctan \dfrac{{{p.d:g}}}{{{p.a:g}}} = {alpha:.4f}\ \mathrm{{rad}}"
           rf"\ (\cos\alpha = {cos_a:.4f})")
    b.p("恒载标准值分项：")
    b.formula(r"g_{k1} = \dfrac{r \cdot d}{2} \quad (三角形踏步)")
    b.subs(rf"g_{{k1}} = \dfrac{{{p.r_c:g} \times {p.d:g}}}{{2 \times 1000}} = {g1:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"g_{k2} = \dfrac{t \cdot r}{1000\cos\alpha} \quad (梯段板自重)")
    b.subs(rf"g_{{k2}} = \dfrac{{{t:g} \times {p.r_c:g}}}{{1000 \times {cos_a:.4f}}} = {g2:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"g_{k3} = \dfrac{(a+d)\, t_1 r_1}{1000\,a} \quad (面层，踏步平、立面)")
    b.subs(rf"g_{{k3}} = \dfrac{{({p.a:g}+{p.d:g}) \times {p.t1:g} \times {p.r1:g}}}{{1000 \times {p.a:g}}} = {g3:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"g_{k4} = \dfrac{t_2 r_2}{1000\cos\alpha} \quad (底面抹灰)")
    b.subs(rf"g_{{k4}} = \dfrac{{{p.t2:g} \times {p.r2:g}}}{{1000 \times {cos_a:.4f}}} = {g4:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"g_{k5} = \dfrac{g}{B \cos\alpha} \quad (栏杆，线荷载摊到板宽)")
    b.subs(rf"g_{{k5}} = \dfrac{{{p.g_rail:g}}}{{{p.B / 1000:g} \times {cos_a:.4f}}} = {g5:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"g_k = g_{k1} + g_{k2} + g_{k3} + g_{k4} + g_{k5}")
    b.subs(rf"g_k = {g1:.3f} + {g2:.3f} + {g3:.3f} + {g4:.3f} + {g5:.3f} = {g_k:.3f}\ \mathrm{{kN/m^2}}")
    b.p("楼梯净跨与计算跨度：")
    b.formula(r"L_n = L + L_1 + L_2, \qquad L = a \cdot n")
    b.subs(rf"L_n = {L_hor:g} + {p.L1:g} + {p.L2:g} = {l_n * 1000:g}\ \mathrm{{mm}} = {l_n:g}\ \mathrm{{m}}")
    b.formula(r"l_0 = \min\left\{ L_n + \dfrac{b_A + b_B}{2},\ 1.05 L_n \right\}")
    b.subs(rf"l_0 = \min\left\{{ {l_n:g} + {(p.b_a + p.b_b) / 2000:g},\ 1.05 \times {l_n:g} \right\}} = {l0:g}\ \mathrm{{m}}")

    b.h2("五、荷载简图与荷载组合")
    b.image(_IMG_LOAD, caption="荷载简图")
    b.formula(r"p_u = \gamma_G g_k + \gamma_Q q_k \qquad (\text{基本组合})")
    b.subs(rf"p_u = {p.gamma_g:g} \times {g_k:.3f} + {p.gamma_q:g} \times {p.q_live:g} = {p_u:.3f}\ \mathrm{{kN/m^2}}")
    b.formula(r"p_{qp} = g_k + \psi_q q_k \qquad (\text{准永久组合})")
    b.subs(rf"p_{{qp}} = {g_k:.3f} + {p.psi_q:g} \times {p.q_live:g} = {p_qp:.3f}\ \mathrm{{kN/m^2}}")

    b.h2("六、内力计算")
    b.p("按支座形式取弯矩系数（每 m 板宽）：两端弹性——支座 1/16、跨中 1/10；"
        "下铰上弹——下端铰支弯矩为 0、跨中 39/320、上端弹性嵌固 3/32。")
    b.formula(r"M = \dfrac{1}{\zeta}\, p\, l_0^2")
    b.table(["截面", "弯矩系数 1/ζ", "M（基本组合）", "M（准永久组合）"], [
        ["A端支座", "铰支（0）" if c_a == 0 else f"1/{c_a:g}",
         f"{m_a:.3f} kN·m/m", f"{m_a_qp:.3f} kN·m/m"],
        ["跨中", f"1/{c_m:.4g}", f"{m_m:.3f} kN·m/m", f"{m_m_qp:.3f} kN·m/m"],
        ["B端支座", "铰支（0）" if c_b == 0 else f"1/{c_b:.4g}",
         f"{m_b:.3f} kN·m/m", f"{m_b_qp:.3f} kN·m/m"],
    ])
    if c_a:
        b.subs(rf"M_A = -\dfrac{{{p_u:.3f} \times {l0:g}^2}}{{{c_a:g}}} = {m_a:.3f}\ \mathrm{{kN \cdot m/m}}")
        b.subs(rf"M_B = -\dfrac{{{p_u:.3f} \times {l0:g}^2}}{{{c_b:g}}} = {m_b:.3f}\ \mathrm{{kN \cdot m/m}}")
    b.subs(rf"M_m = \dfrac{{{p_u:.3f} \times {l0:g}^2}}{{{c_m:.4g}}} = {m_m:.3f}\ \mathrm{{kN \cdot m/m}}")

    b.h2("七、配筋计算")
    b.p("按单筋矩形截面（b=1000mm）计算，截面有效高度按选筋表最大直径取：")
    b.formula(r"h_0 = t - c - d_{\max}/2")
    b.subs(rf"h_0 = {t:g} - {p.cover:g} - {D_MAX_H0:g}/2 = {h0:g}\ \mathrm{{mm}}")
    b.p(f"最小配筋面积：$A_{{s,\\min}} = \\rho_{{\\min}} b h = "
        f"{p.rho_min:g}\\% \\times 1000 \\times {t:g} = {as_min:.0f}\\ \\mathrm{{mm^2}}$。")
    for s in secs:
        b.h3(s["tag"])
        if s["alpha_s"] == 0 and s["as_c"] == 0:
            b.p("该截面弯矩为 0，按最小配筋率控制。")
        else:
            b.formula(r"\alpha_s = \dfrac{M}{\alpha_1 f_c b h_0^2}")
            b.subs(rf"\alpha_s = \dfrac{{{abs(s['m']) * 1e6:.0f}}}{{1 \times {fc:g} \times 1000 \times {h0:g}^2}} = {s['alpha_s']:.4f}")
            b.formula(r"\xi = 1 - \sqrt{1 - 2\alpha_s}")
            b.subs(rf"\xi = 1 - \sqrt{{1 - 2 \times {s['alpha_s']:.4f}}} = {s['xi']:.4f}")
            b.check(f"{s['tag']}受压区高度", value=s["xi"], limit=xi_b,
                    expr=r"\xi \le \xi_b")
            b.formula(r"\gamma_s = 1 - 0.5\xi")
            b.subs(rf"\gamma_s = 1 - 0.5 \times {s['xi']:.4f} = {s['gamma_s']:.4f}")
            b.formula(r"A_s = \dfrac{M}{f_y \gamma_s h_0}")
            b.subs(rf"A_s = \dfrac{{{abs(s['m']) * 1e6:.0f}}}{{{fy:g} \times {s['gamma_s']:.4f} \times {h0:g}}} = {s['as_c']:.1f}\ \mathrm{{mm^2}}")
            b.subs(rf"A_s = \max( {s['as_c']:.1f},\ {as_min:.0f} ) = {s['as_des']:.1f}\ \mathrm{{mm^2}}")
        b.p(rf"选用 $\Phi{s['dia']}@{s['sp']}$（$A_s = {s['as_prov']:.1f}\ \mathrm{{mm^2}}$）。")
        b.check(f"{s['tag']}最小配筋", value=s["as_prov"], limit=as_min,
                op="ge", expr=r"A_s \ge \rho_{\min} b h", unit="mm²")

    b.h2("八、裂缝验算")
    b.p("按准永久组合并考虑长期作用影响，最大裂缝宽度限值 0.3mm。"
        "ρte=As/(0.5B·t)（≥0.01），cs=min(max(c,20),65)。")
    for s in secs:
        b.h3(s["tag"])
        if s["sig"] == 0:
            b.p("该截面弯矩为 0，钢筋应力为 0，裂缝宽度为 0。")
        else:
            b.formula(r"\sigma_s = \dfrac{M_{qp}}{0.87 h_0 A_s}")
            b.subs(rf"\sigma_s = \dfrac{{{abs(s['m_q']) * 1e6:.0f}}}{{0.87 \times {s['h0c']:g} \times {s['as_prov']:.1f}}} = {s['sig']:.1f}\ \mathrm{{N/mm^2}}")
            b.formula(r"\psi = 1.1 - \dfrac{0.65 f_{tk}}{\rho_{te} \sigma_s} \quad (\text{限 } [0.2, 1])")
            b.subs(rf"\psi = 1.1 - \dfrac{{0.65 \times {ftk:g}}}{{{s['rte']:.4f} \times {s['sig']:.1f}}} = {s['psi']:.3f}")
        b.formula(r"\omega_{\max} = \alpha_{cr} \psi \dfrac{\sigma_s}{E_s}\left( 1.9 c_s + 0.08 \dfrac{d_{eq}}{\rho_{te}} \right)")
        if s["sig"] == 0:
            b.subs(rf"\omega_{{\max}} = 0\ \mathrm{{mm}} \quad (\rho_{{te}} = {s['rte']:.4f})")
        else:
            b.subs(rf"\omega_{{\max}} = 1.9 \times {s['psi']:.3f} \times \dfrac{{{s['sig']:.1f}}}{{{Es:.0f}}} \times (1.9 \times {s['cs']:g} + 0.08 \times \dfrac{{{s['dia']:g}}}{{{s['rte']:.4f}}}) = {s['w']:.3f}\ \mathrm{{mm}}")
        b.check(f"{s['tag']}裂缝宽度", value=s["w"], limit=0.3,
                expr=r"\omega_{\max} \le [\omega]=0.3", unit="mm")

    b.h2("九、挠度验算")
    b.p("按准永久组合计算跨中长期挠度，考虑踏步参与受力后的等效截面高度，"
        "挠度限值 [f]=l0/200。")
    b.formula(r"\rho_{te} = \max\left\{ \dfrac{A_s}{0.5 \times 1000 \times t},\ 0.01 \right\}, \qquad \sigma_s = \dfrac{M_{qp}}{0.87 h_0 A_s}")
    b.subs(rf"\rho_{{te}} = {rte_d:.4f}, \qquad \sigma_s = \dfrac{{{mid['m_q'] * 1e6:.0f}}}{{0.87 \times {h0_d:g} \times {mid['as_prov']:.1f}}} = {sig_d:.1f}\ \mathrm{{N/mm^2}}")
    b.subs(rf"\psi = 1.1 - \dfrac{{0.65 \times {ftk:g}}}{{{rte_d:.4f} \times {sig_d:.1f}}} = {psi_d:.3f}")
    b.formula(r"\alpha_E = \dfrac{E_s}{E_c}, \qquad \rho = \dfrac{A_s}{1000 h_0}")
    b.subs(rf"\alpha_E = {a_e:.3f}, \qquad \rho = {rho_d:.5f}")
    b.formula(r"h_0' = h_0 + \lambda\, d\cos\alpha \quad (\text{考虑踏步刚度后})")
    b.subs(rf"h_0' = {h0_d:g} + {p.step_factor:g} \times {p.d:g} \times {cos_a:.4f} = {h0_step:.1f}\ \mathrm{{mm}}")
    b.formula(r"B_s = \dfrac{E_s A_s h_0'^2}{1.15\psi + 0.2 + 6\alpha_E \rho}")
    b.subs(rf"B_s = \dfrac{{{Es:.0f} \times {mid['as_prov']:.1f} \times {h0_step:.1f}^2}}{{1.15 \times {psi_d:.3f} + 0.2 + 6 \times {a_e:.3f} \times {rho_d:.5f}}} = {b_s:.3e}\ \mathrm{{N \cdot mm^2}}")
    b.formula(r"B_l = \dfrac{B_s}{2} \quad (\theta = 2)")
    b.subs(rf"B_l = {b_l:.3e}\ \mathrm{{N \cdot mm^2}}")
    b.formula(r"f = \eta \cdot p_{qp} \cdot l_0^4 \times 10^{12} / B_l")
    b.subs(rf"f = {DEFLECT_COEF[p.support]:.5f} \times {p_qp:.3f} \times {l0:g}^4 \times 10^{{12}} / {b_l:.3e} = {f:.2f}\ \mathrm{{mm}}")
    b.check("跨中挠度", value=f, limit=f_lim,
            expr=r"f \le [f]=l_0/200", unit="mm")

    return b


# ----------------------------------------------------------------------
# 内嵌示意图（data URI，预览/导出/离线均可用）
# ----------------------------------------------------------------------
_IMG_SECTION = "data:image/png;base64,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"
_IMG_LOAD = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABQQAAAHJCAIAAABcxaO1AABIhklEQVR42u3deZhdZZ0n8FN3rVtrUqmslaQqyOaALJEEQSCiPh21QX1opNFpRXAGgzNta6sP3UrrDCDq4CO0BoZBoFVwARukwWbCos0itI6ySKPNorIkgUBCAiF7UlXzxx3vXO6m3eb+Dqn6fP7oB5K0L/d969y83/P7nfd0jI+PJwAAADCZZEwBAAAAwjAAAAAIwwAAACAMAwAAgDAMAAAAwjAAAAAIwwAAACAMAwAAgDAMAAAAwjAAAAAIwwAAACAMAwAAgDAMAAAAwjAAAAAIwwAAAJAkOVMAAG114403joyMVP71gAMOyGTcjAYAYRgAJqiXXnpp+fLl55577pw5c8q/snr16rPOOuvDH/5wT0/P+eef/9hjj1166aUmCgCEYQCYIG6++ebPfOYz2Wz2xz/+8d57713+xX/913/90Ic+dMstt1x11VWmCABS1DE+Pm4WACDZ3TXht73tbVOnTv3Wt77V09NT/Vvr168/4YQTent7jzzyyMcff1xlGAASB2gBwAQwOjr62c9+NpvN1ifhJEkGBgauu+66VatW/fznP3dLGgCEYQCYIFasWHH11Vdfdtll9Um4koe/9rWvPfDAA+vXrzddAJB4ZhgA9nQ7d+787Gc/+4EPfKDynHBDBx988Ote97pCoWDGACBRGQaAPd2GDRuefvrpU0455Xf+yQMOOMB0AYAwDAATwUMPPdTX1zd9+nRTAQDCMABMFrfccsuxxx7b2dlpKgBAGAaASWHHjh233nrrW9/6VlMBAMIwAEyiMLxhw4YpU6aYCgAQhgFgchkYGDAJACAMAwAAgDAMABPU1q1bn3322UcffdRUAIAwDACTxfTp00866aQHH3zQVACAMAwAk8jxxx9/00037dy501QAgDAMAJPFYYcdtmrVqg0bNpgKABCGAWCymDlzZn9//0033fQ7/+STTz5pugBAGAaAiaBYLJ5++ukXXHDB+vXrW/yxZ5555oc//OHKlSvNGAAIwwAwEZx22mnz58//9Kc/vWvXroZ/YPv27R/96EfnzJkzNDRkugBAGAaAiaBUKl100UU33XTTN77xjbGxsZrfHR0d/fKXv/zAAw8cffTRmYy/iAEgHTlTAAC73fz58y+88MKTTz7517/+9cc+9rH+/v7yr7/44otf+MIXvvKVr6xYseInP/mJiQIAYRgAJpS3v/3t995778c+9rFXvepVRxxxRPkX77vvvoULF/785z/fZ599hGEAEIYBYAJ69atf/b3vfe+cc8454IADyr9ywAEHnHPOOZ2dnSYHAIRhAEgm8OHS5557buVf3/3ud5sTAEgcoAUAAADCMAAAAAjDAAAAIAwDAACAMAwAAADCMAAAAAjDAAAAIAwDAAAgDAMAAMBk0jE+Pm4WAAAASFSGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAABAGAYAAABhGAAAAIRhAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAAAgLTlTANS74447TAIAE8mSJUtMAiAMA60cfvjhzz//fF9fX/zQe++99w9+8IODDjroxRdfjB99aGjohz/84dKlS5944on40fv6+v7lX/7lTW96069+9av40devXz9t2rTx8fH4oV/1qlfdeuuthx122Pr16+NHnz179h133LF06dLHH388fvTu7u5HHnnkDW94Q/yi77PPPnfffffQ0NDOnTtTWfSbb775iCOOWLt2bfzoM2bMuPvuu5cuXfqb3/wmfvRisfjkk08eddRRqVzpmzZtKhaL+Xw+fui99trr5ptvPvroo9esWRM/+ty5c3/wgx+sWrVq6tSp/pYHKjpS2foAr/AwvGDBgiuvvDJ+6F27dh199NHnnXfescceGz/6U0899cY3vvG+++5L5UbAD3/4w7POOuvOO+/M5VK4Tfn+97//da973bJly+KH3rlz5+LFiy+55JLDDz88fvTHHnvsj//4j++///7u7u740b///e9feOGFt9xySyYT/dTS+Pj4u971rne84x3vfe974z/49u3bFy5c+K1vfevggw+OH/0Xv/jFiSeeeP/993d2dsaPfvXVV3/zm9+8/vrr4xc9SZKPfOQjM2bM+OQnPxk/9JYtWw499NAbbrhhv/32ix991apVb3jDGx544AFhGEhUhoHfGUpTKR0kSdLR0ZHNZlMZPZfLdXR05HK5VEbPZrMpjt7R0ZHJZFIZenx83KJns9ngocfGxlKc9tHR0RRHT/daS3HRkyTJZDJpXenlay3dK91f7oADtAAAABCGAQAAQBgG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O2688caLLroofvRXv/rVmUwmlSfkgVeyjvHxcbMA1EhljwgA7fP617/eJADCMAAAAIkDtAAAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAABAGAYAAICJLmcKAKCtRkdHq/81m82aEwAQhgFgInviiSfe+MY37rvvvuV/ffjhh//pn/5pwYIFZgYA0tUxPj5uFgBgt3v22Wf//u///vzzzz/wwAPf8573lAvC//AP/3DPPff8zd/8zZ/8yZ989atffeyxxy699FJzBQCJyjAAJBOiNforX/nKV7/61e9973uLFy/O5f7fX7gnnnji3Xff/Y53vGPTpk1mCQASB2gBwERy5513XnXVVXfdddeRRx5ZScJJkmSz2WOOOeYHP/jBBRdcsGXLFhMFAMIwACQTpkF62bJl5557buVR4RoLFy78yEc+8nd/93fTpk0zXQCQeGYYAPZ0Y2Njr3nNaw499NArrriiUCg0+2Nbt249/PDDe3p67rnnHpMGAIlnhgFgj7Zly5bt27d/4AMfaJGEkyQplUrve9/7Hn30UTMGAIk2aQDY0z355JOjo6MLFy78nX9ScxYACMMAkEyYo7MOOeSQnp4eUwEAwjAAJJPkjUo33njj8ccfX36rMAAgDAPAxLd169bbb799wYIFpgIAhGEAmERmzZo1NDRkHgBAGAYAAABhGAAmrjVr1jz99NPmAQCEYQCYLDo7O4866qiVK1eaCgAQhgFgssjlcm9729u+//3vj42NmQ0AeEX/rW0KAGA3esMb3rB8+fItW7bsllcNP/fcc/W/ODAwkMv5GxwAEpVhAHilWLBgwejo6FNPPfWH/09t3LhxZGTkXe961+IqIyMj7373u3/84x9v37799/+feumll4aHh7/+9a9bIABIVIYBYLfr6enZuXPnWWed9d3vfjebzTb7Yzt27Pj+97/fsPBbbXBw8MILL5wzZ05SdUDX9ddf/573vOeYY4659NJLC4XC7/xP2rVr12WXXZYkyb8pPwNAojIMAPyestns7bfffv/99998880t/tg111zzyCOPHHfccb/j7+lMZsqUKTOrHHzwwZ/5zGdWrFjx4x//+Morr/x9/pNuuummW265Zf/99y8WixYIAIRhAGiLvffe+4ILLviv//W/PvHEEw3/wC9+8Yuzzjrr/e9//4svvvjvG2Lfffe94oorzjnnnBtuuKHFHxsdHb3++uvf/e53n3nmmaVSydIAgDAMAG103HHHvfOd7zziiCMeeuihmt964IEHjjnmmNNPP32//fb7Q4Y48sgjly5d+qMf/ajFnznzzDM/8pGPLF++/KijjrIoAJB4ZhgA2v2OpY9//OMDAwPHHXfc6aef/uY3v7lYLHZ0dPz93//9N77xjb/+678+7bTTLr/88j9wlNNOO+0//sf/+Od//ufz5s1r+Ae++MUvnnHGGa961au86gkAhGEAiDBnzpxPfvKTb33rW4899tivfe1r5V989tlnb7vttkWLFiW7qR87k8k899xzzcJwkiSvetWrrAUACMMAECeTybz2ta999tlnq39xNz67O3Xq1IULF951112vfe1rzTYAeGYYAF5BSi+3e8P20qVLb7nlltHRUfMMAMIwAEwWw8PDt99++7p160wFAAjDADBZzJs3b+bMmd3d3aYCAIRhAAAAEIYBAABAGAYAAEAYBgAAAGEYANgTrFmzpru7O5fLmQoAEIYBYLK47bbbjjrqqM7OTlMBAMIwAEwKO3fuvPXWW9/ylreYCgD4t9JVBQDp+MQnPvEH/i+sW7fugQcemD17tskEgERlGAAmiVtvvXXx4sULFy40FQAgDAPApLBx48azzjrrtNNOy+fzZgMAhGEAmPjGxsYuvvjiGTNmHH/88WYDABLPDANAMglqwpdddtkll1zy/e9/f+rUqSYEAIRhAJhQtmzZsmLFiurXCP+f//N/7rrrrmKxeOKJJx544IGmCAD+fTrGx8fNAgC8Mp100kk1v3Lvvff+r//1v4488siuri7zAwDCMAAAACQO0AIAAABhGAAAAIRhAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAgD9AzhQA9TZt2mQSAJhIenp6TAIgDAOtHH744c8++2wmk0LnyH777ffP//zP++2339q1a+NHHx4e/slPfnLUUUf96le/ih99+vTpjzzyyBFHHPHII4/Ej759+/apU6du2bIllUW/++67DzzwwDVr1sSPPm/evJ/+9KdHH330Y489Fj/6wMDA448/vnjx4vhF33///e+7776ZM2e+9NJL8R983333/dGPfnTIIYc8/fTT8aMPDQ3dd999Rx999KOPPho/en9//+rVq1/72temcqWPjY0VCoVdu3bFD73PPvv86Ec/Ouyww1auXBk/+ujo6Nq1a1evXj116lR/ywMVHePj42YBqAnDs2bNOv/88+OHzmazJ5xwwplnnnnYYYfFj75u3bqTTjppxYoVhUIhfvSf/vSn559//rXXXjs6Oho/+plnnrlw4cI//dM/jR86k8kcd9xxn/vc5w444ID40Z9++un3ve99K1asyOVSuDt85513XnbZZd/61rfiw0k+n//gBz+4dOnS448/PpXvmbe85S3Lly/fe++944d+/PHHly1btmLFio6OjvjRb7755uuuu+7yyy9PJZGed95506ZN++AHP5hKHH3LW95yxRVXzJs3L62v93/5l38RhoFEZRj4nRvlfffdN37cnTt3FgqFmTNnpjJ6sVjM5XLz5s3r7++PH/2pp54qFArz58/P5/Pxo3d3dw8MDKQy7Tt27Mjn87NmzUpl9CRJcrnc/PnzU+mffPjhhzs7O4eHh7PZbBJeIezq6hocHExl2rdt25bP52fPnp3K6Nu3by8veqlUih/93nvvLZVKqSx6kiS9vb1TpkxJZdo3b96cy+XmzJmTyuilUimVG15A4gAtAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAQBgGAAAAYRgAAACEYQAAABCGAQAAEIYBAABgEukYHx83C8App5xS/ofx8fHbbrutv79/8eLF5V/5+te/HjB6f3//iy++ODY2dvfdd7/61a8eHByMHH1oaGj16tVbt269++67lyxZks/nZ82atWbNmpjRy/+wdu3ahx9++PWvf30m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wjAAAAAIwwAAACAMAwAAgDAMAAAAwjAAAAAIwwAAAAjDAAAAIAwDk9wZZ5zx+c9/3jxMKgceeOBpp51mHpgM/vEf/7Gnp+eFF14wFZPHypUrR0ZGNmzYYCoAYRgAAABhGAAAAIRhAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAABAGAYAAABhGAAAAIRhAAAAEIYBAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAAEAYBgAAAGEYAAAAhGEAAAAQhgEAACBIzhQA/E4PPvjgQQcdZB6ACeOhhx668sory/+8dOnSJUuWZLNZ0wIkKsMAE9W2bdv222+/+++///f/f9m0adNf/MVf/If/8B9GR0dNIH+ga665ZunSpX6WaIff/OY3CxYseOmll37nn7zkkkuOO+64X/7yl9ls9plnnjnttNM+9alPmUAgURkGoGbXODY2NnPmTFMBTABPPPHE5z//+e985zuLFy/OZDJJkvzqV79685vfvN9++5166qnmB0hUhgEYHR39zne+s3z58hNPPFEDITAx3Hjjja95zWsOO+ywchJOkmTvvfc+77zzLr/88h07dpgfQBgGIPnMZz7zV3/1V//9v//3oaEhswFMANu3b//617/+gQ98IJd7WXvgm970plWrVj311FOmCBCGAUjOPffcm2+++ZRTTjEVwMRQLBbXrVt39NFH1/x6b29vqVR68cUXTRGQeGYYgCRJ9ttvP5MAJBPrmeH6XxwbG3vuuedMDpCoDAMAMHk888wzvb29c+fONRWAMAwAwGRx1llnLV68eHBw0FQAiTZpAAAmg/Xr1//sZz/7+te/7th8IFEZBgBgkvjud787NDS0aNEiUwEkKsMAACST4zytj3/849dee22xWDQbQKIyDADAhLdz587Pfe5zf/RHf7RkyRKzASQqwwAATAY33XTTbbfddscddygLA8IwAACTwsqVKz/60Y/+7d/+rTcqAYk2aQAAJoNt27Z9+MMfXrp06Vvf+lazASQqwwAATAbf/OY3H3300a9+9au5nN0gIAwDADAJPPzww+ecc85VV101ODhoNoBEmzQAABPepk2bPvjBD55yyilHHHGE2QCEYQAAJr6xsbHly5dv37794x//eDabNSFAok0aYPKYMWPGv/7rv27ZsqX+t17/+tebH9qtq6vrnnvuyWQyfgLZ7Xbs2PHggw82/K3yT9fPfvaz66+//qMf/WjrPwYgDANMQA8++ODZZ5/d8KWaP//5z80P7XbXXXf95je/afhbfgL5A7300kvLli1reKul/NO1ePHiZ5555rzzzmv2v+CHEBCGASamzs7OtWvX/lv/v0444YQTTjjB7PGHO+mkk975zneaB9phr732Wrdu3e/8Y4899pi5Akg8Mwwkv+uclSRJdu7cOZE+VKE5K54kyTPPPJMkyfbt202Fn8DJ4Nxzz3344Ycn1U9XoaVkEjw1ffXVV/8+dw0AYRiY1En4Qx/6UEdHx9/+7d/u2rXLhEySJPyGN7yho6Pj/e9//9atW00IEz4J/83f/M3b3va2Bx54wGwkk+P8sO9+97snn3zyn/3Zn61Zs8aEgDAM0DgJn3HGGVdeeWWSJJ/4xCcuvPBCeXiSJOFHH300SZLvfOc7J5988ubNm00LEzsJJ0ny+OOPH3vssT/5yU/MycTW0dFRTsJJktx8881vf/vbV61aZVpAGAZ4mb6+vjPOOOOqq66q/Eo5D5uZia2ShMtuuOEGT7cyUV188cXlJFz2wgsvnHDCCXfccYeZmaj233//66+/vpyEy376058effTRjz/+uMkBYRjg/5k+ffpVV11VnYST3x7CbHImqlwud8MNN1Qn4bL6X4FkQtzv+9SnPlXzi+vWrXvooYdMzoSUzWbXrFlz6qmnJnW14tWrV5sfcJo0QJIkyaZNm2644Yb6V2u8973v/Z//83+an2SCdkc/+uij9U8Iz58//6677jI/TDD/+3//7/IpcdVKpdL555//X/7LfzE/yUR8TvjGG2+s/3tteHj4G9/4xlFHHWWKIFEZBig/J9wsCXd3d5uiCZmElyxZ0iwJz58/3xQxkZxzzjkXXXSRJDzZTsxatmxZfRK+6qqrJGGY5DrGx8fNAkxOGzZsqP7Xbdu2ffSjH7366qtr/tjJJ598wQUXFItFMzYBvPTSSzX/etJJJ/3yl79M6t5WevXVV8+YMaP8r729vaaOCfADf+mll372s5+t+TPd3d1nn332iSee6Kd9Qp6Ydf3119d3R8+bN++rX/3q4sWLy/86depUcwXCMDC5jIyMVP55n332+eUvf/n000/X/Jk5c+YccMABHhydMJ577rmkqvb75JNPbtu2rebPZDKZUqk0NjZW+ZVKKoY99wd+bGys/u3ZHR0dxWKxo6PDT3syEU/MWrNmTX2vU6lUOuigg6rfq/TEE0+YLkg8MwxMKj/60Y/K/7Bjx44zzzyzPgm/613v+sIXvpDP583VhLFu3brkt40A73//++uT8PDw8OWXXz5t2rTqXxwcHDR17NE/8FdeeeWXvvSlpK4m/IlPfOId73iHn/ZkIp6YdeONN37wgx+s+fW5c+dedNFFCxcuNEVAojIMlJ8Trj872nPCyUR/Tvixxx5LPCdMMimeE/70pz9d84s9PT2f//znPSecTNznhKvfopT8tjv6W9/6lueEAWEYaJWEjzjiiFtvvVUSnlRJeHBw8N5775WEmQxJuKOjY/ny5R/60IfMz+RJwqVS6Xvf+97SpUtNEZBokwaSJFm2bNk3v/nNml885JBD3vve90rCE1XDJNzT03PaaadJwkyGJFwqlZIkec973mN+JqSGSXju3LlDQ0OVE7MAEq9WArLZbFLXHf32t7/9xRdfNDkTVS6Xq++OPuaYY9auXWtymHhfcZ2dnTVJeNmyZZmM/c/E3drWLe7w8PBFF11UfWIWgDAMJBdffPH73ve+mueEq89fZeK54447Dj300JrnhJ988kkzw8TzyU9+8gtf+EK5FFxOwl/84hff9KY3mZkJ7F3veteNN944PDxc/T7h6i89AGEYSJIk6e7uvvjii0855RQnZk0e06dPv+2224444ggnZjEZfPjDH/7KV77S2dk5bdq0L37xi54TngyOO+64yy67bMaMGQcddNBVV13lxCygmf8L2hV+LAy7mGwAAAAASUVORK5CYII="
