"""<一句话说明>（<规范号> <验算类型>）。

由 cb-template skill 生成 —— 请按需填实：
1. 类名 XxxParams → 改成实际参数名
2. 字段：按 [grill 阶段 1.2] 得到的参数清单填
3. @template name/description → 按 [grill 阶段 1.6] 三件套填
4. calc() 函数体：按 [阶段 2 查到的规范条文] 填公式与 check
"""

from __future__ import annotations

from pydantic import BaseModel

from calcbook import CalcBook, Field, template


class XxxParams(BaseModel):
    """<参数中文说明>。"""

    # —— 通用参数（批量时可整组统一设置）——
    # 例：material: str = Field("C30", label="混凝土等级",
    #                           choices=["C25", "C30", "C35"],
    #                           group="材料", batch_hidden=True)
    # TODO: 填材料/系数类参数（每项一行）

    # —— 每行不同的参数（几何/荷载）——
    # 例：length: float = Field(3000, label="计算跨度", unit="mm",
    #                            gt=0, group="几何")
    # TODO: 填几何/荷载类参数


@template(
    "<显示名>",                         # 界面下拉里看到的名字
    description="<给使用者的简短说明>", # 鼠标悬停时显示
    # manual=False,                    # 计算量大才改 True
)
def calc(p: XxxParams) -> CalcBook:     # 或 (p, *, name: str = "")
    b = CalcBook(title="<计算书标题>")
    # TODO: 写计算逻辑
    # 例：sigma = p.M * 1e6 / p.W

    b.h2("1. 计算条件")
    # TODO: b.table(["参数", "取值"], [["钢材", p.steel], ...])

    b.h2("2. <验算项>")
    # 公式 → 代入 → 判定 三件套
    # b.formula(r"<符号公式>", cite=("<规范号>", "<条文号>"))
    # b.subs(rf"<代入> = {value:.1f}\ \mathrm{{<单位>}}")
    # b.check("<名称>", value=..., limit=..., unit="...",
    #         expr=r"<符号>", cite=("<规范号>", "<条文号>"))

    return b                            # ← 必须
