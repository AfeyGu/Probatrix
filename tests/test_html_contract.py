"""to_html 内容语法契约：实现 = docs/模板开发指南.md「内容语法契约」。

结构只由 API 决定；文本一律 HTML 转义；行内格式仅 `**粗体**` 与 `$…$`。
本文件与契约文档同步维护——改这里必须同步文档，反之亦然。
"""
from calcbook import CalcBook


def book_all_kinds() -> CalcBook:
    b = CalcBook(title="测试计算书")
    b.h1("1. 总信息")
    b.h2("1.1 参数")
    b.h3("局部说明")
    b.p("采用焊接截面，**翼缘**首选用钢，强度 $f=305$ N/mm²。")
    b.formula(r"\sigma = \dfrac{M_x}{\gamma_x W_x}", cite=("GB 50017-2017", "4.1.1"))
    b.subs(r"\sigma = 150.2")
    b.check("抗弯强度", value=150.2, limit=215, expr=r"\sigma", unit="N/mm²",
            cite=("GB 50017-2017", "4.1.1"))
    b.table(["构件", "b×h"], [["梁", "200×400"]])
    b.image_bytes(b"\x89PNG-fake", caption="截面简图")
    return b


# ---------------------------------------------------------------- 结构
def test_title_and_headings() -> None:
    h = book_all_kinds().to_html()
    assert h.startswith("<h1>测试计算书</h1>")
    assert "<h1>1. 总信息</h1>" in h
    assert "<h2>1.1 参数</h2>" in h
    assert "<h3>局部说明</h3>" in h


def test_paragraph_bold_and_inline_math() -> None:
    h = book_all_kinds().to_html()
    assert "<p>采用焊接截面，<b>翼缘</b>首选用钢，强度 $f=305$ N/mm²。</p>" in h


def test_multiline_paragraph_is_lines() -> None:
    """多行文本 = 多个段落（每非空行一个 <p>），与历史行为一致。"""
    h = CalcBook().p("第一行\n第二行").p("第三行").to_html(with_summary=False)
    assert "<p>第一行</p>\n<p>第二行</p>\n<p>第三行</p>" in h


# ---------------------------------------------------------------- 公式与引用
def test_formula_block_and_cite() -> None:
    h = book_all_kinds().to_html()
    assert "<p class='formula'>$$\\sigma = \\dfrac{M_x}{\\gamma_x W_x}$$</p>" in h
    assert "<blockquote>依据：GB 50017-2017 第 4.1.1 条</blockquote>" in h


def test_check_verdict_line() -> None:
    h = book_all_kinds().to_html()
    assert "<p class='item'>• <b>抗弯强度</b>：$\\sigma$：150.2 ≤ 215 N/mm²，" \
           "应力比 0.6986 —— <b>满足</b></p>" in h


# ---------------------------------------------------------------- 表格与汇总
def test_table_structure() -> None:
    h = book_all_kinds().to_html()
    assert "<table><tr><th>构件</th><th>b×h</th></tr>" in h
    assert "<tr><td>梁</td><td>200×400</td></tr>" in h


def test_summary_table_appended() -> None:
    h = book_all_kinds().to_html()
    assert "<th>验算项</th><th>数值</th><th>应力比</th><th>结论</th><th>依据</th>" in h
    assert h.rstrip().endswith("</table>")
    assert "<table>" not in CalcBook(title="无验算").to_html(with_summary=False)


# ---------------------------------------------------------------- 插图
def test_image_centered_with_caption() -> None:
    h = book_all_kinds().to_html()
    assert "<p style='text-align:center'><img src='data:image/png;base64," in h
    assert "alt='截面简图'></p>" in h
    assert "<p style='text-align:center'><small>截面简图</small></p>" in h


# ---------------------------------------------------------------- 转义与内容边界
def test_escapes_html() -> None:
    h = CalcBook(title="T").p("<script>alert(1)</script> & \"引号\"").to_html(with_summary=False)
    assert "<script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;引号&quot;" in h


def test_content_is_never_markup() -> None:
    """契约核心：结构只由 API 决定——文本长得像 md 也按字面显示。"""
    h = CalcBook().p("## 附表").p("> 引用").p("- 列表").to_html(with_summary=False)
    assert "<h2>" not in h and "<blockquote>" not in h and "class='item'" not in h
    assert "<p>## 附表</p>" in h
    assert "<p>&gt; 引用</p>" in h
    assert "<p>- 列表</p>" in h


def test_bold_in_table_cell_and_caption() -> None:
    b = CalcBook()
    b.table(["名", "值"], [["**梁**", "1"]])
    b.image_bytes(b"x", caption="**图**注")
    h = b.to_html(with_summary=False)
    assert "<td><b>梁</b></td>" in h
    assert "<small><b>图</b>注</small>" in h
