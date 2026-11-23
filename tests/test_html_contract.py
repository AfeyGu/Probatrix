"""to_html 内容语法契约见 docs/manual/06-计算书排版.md 的「内容语法契约」。

结构只由 API 决定；文本一律 HTML 转义；行内格式仅 `**粗体**` 与 `$…$`。
本文件与契约文档同步维护——改这里必须同步文档，反之亦然。

Markdown 图片（本文件最后一节）：`markdown(text, base_dir=...)` 里独占一行的
`![图注](相对路径)` 在预览与 HTML 导出中内嵌为 base64 data URI，Markdown 导出物
保留原文；相对路径只能落在 base_dir 及其下级，失败就地提示并显示引用路径。
"""
import base64
import os
import subprocess
from pathlib import Path

import pytest

from probatrix import Probatrix


def book_all_kinds() -> Probatrix:
    b = Probatrix(title="测试计算书")
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
    h = Probatrix().p("第一行\n第二行").p("第三行").to_html(with_summary=False)
    assert "<p>第一行</p>\n<p>第二行</p>\n<p>第三行</p>" in h


# ---------------------------------------------------------------- 公式与引用
def test_formula_subs_standalone_blocks() -> None:
    """formula/subs 旧写法渲染为两个独立公式块（不自动合并——换行由模板分段）。"""
    h = book_all_kinds().to_html()
    assert "<p class='formula'>$$\\sigma = \\dfrac{M_x}{\\gamma_x W_x}$$</p>" in h
    assert "<p class='formula'>$$\\sigma = 150.2$$</p>" in h
    assert "<blockquote>依据：GB 50017-2017 第 4.1.1 条</blockquote>" in h


def test_formula_without_subs_standalone() -> None:
    """无相邻 subs 的 formula 保持独立公式块。"""
    h = Probatrix().formula(r"\sigma = \dfrac{M}{W}").to_html(with_summary=False)
    assert h == ("<p class='formula'>"
                 "$$\\sigma = \\dfrac{M}{W}$$</p>")


def test_check_verdict_line() -> None:
    h = book_all_kinds().to_html()
    assert "<p class='item'>• <b>抗弯强度</b>：$\\sigma$：150.2 ≤ 215 N/mm²，" \
           "比值 0.6986 —— <b>满足</b></p>" in h


# ---------------------------------------------------------------- 推导链（derive）
def test_derive_multiline_segments() -> None:
    """推导链：一段一行，等号对齐（换行由分段决定）。"""
    b = Probatrix()
    b.derive(r"\sigma",
             r"\dfrac{M_x}{\gamma_x W_x} \le f",
             r"\dfrac{95.2\times10^6}{1.05 \times W_x}",
             r"152.3\ \mathrm{N/mm^2}",
             cite=("GB 50017-2017", "4.1.1"))
    h = b.to_html(with_summary=False)
    assert "<p class='formula'>$$\\begin{aligned}" in h
    assert "\\sigma &amp;= \\dfrac{M_x}{\\gamma_x W_x} \\le f \\\\" in h
    assert "&amp;= \\dfrac{95.2\\times10^6}{1.05 \\times W_x} \\\\" in h
    assert "&amp;= 152.3\\ \\mathrm{N/mm^2}" in h
    assert "\\end{aligned}$$" in h
    assert "<blockquote>依据：GB 50017-2017 第 4.1.1 条</blockquote>" in h


def test_derive_one_segment_is_plain() -> None:
    """单段 = 单行公式（作者想一行连排就自己并成一段、段内用 = 连）。"""
    h = Probatrix().derive(r"\sigma",
                          r"\dfrac{M}{W} = 152.3\ \mathrm{N/mm^2}"
                          ).to_html(with_summary=False)
    assert h == ("<p class='formula'>"
                 "$$\\begin{aligned}\n\\sigma &amp;= \\dfrac{M}{W} = 152.3"
                 "\\ \\mathrm{N/mm^2}\n\\end{aligned}$$</p>")


def test_derive_requires_steps() -> None:
    with pytest.raises(ValueError):
        Probatrix().derive(r"\sigma")


def test_derive_take_line() -> None:
    """取值行:行首带「取」字、等号与上行对齐。"""
    b = Probatrix().derive(
        r"A_s",
        r"\dfrac{M}{f_y \gamma_s h_0}",
        r"\dfrac{1868847}{360 \times 0.9889 \times 77} = 68.2\ \mathrm{mm^2}",
        take=r"\max(68.2,\ 200) = 200.0\ \mathrm{mm^2}")
    h = b.to_html(with_summary=False)
    assert "\\begin{aligned}" in h
    assert "\\text{取 } A_s &amp;= \\max(68.2,\\ 200) = 200.0\\ \\mathrm{mm^2}" in h


# ---------------------------------------------------------------- 表格与汇总
def test_table_structure() -> None:
    h = book_all_kinds().to_html()
    assert "<table><tr><th>构件</th><th>b×h</th></tr>" in h
    assert "<tr><td>梁</td><td>200×400</td></tr>" in h


def test_summary_table_appended() -> None:
    h = book_all_kinds().to_html()
    assert "<th>验算项</th><th>数值</th><th>比值</th><th>结论</th><th>依据</th>" in h
    assert h.rstrip().endswith("</table>")
    assert "<table>" not in Probatrix(title="无验算").to_html(with_summary=False)


# ---------------------------------------------------------------- 插图
def test_image_centered_with_caption() -> None:
    h = book_all_kinds().to_html()
    assert "<p style='text-align:center'><img src='data:image/png;base64," in h
    assert "alt='截面简图'></p>" in h
    assert "<p style='text-align:center'><small>截面简图</small></p>" in h


# ---------------------------------------------------------------- 转义与内容边界
def test_escapes_html() -> None:
    h = Probatrix(title="T").p("<script>alert(1)</script> & \"引号\"").to_html(with_summary=False)
    assert "<script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;引号&quot;" in h


def test_content_is_never_markup() -> None:
    """契约核心：结构只由 API 决定——文本长得像 md 也按字面显示。"""
    h = Probatrix().p("## 附表").p("> 引用").p("- 列表").to_html(with_summary=False)
    assert "<h2>" not in h and "<blockquote>" not in h and "class='item'" not in h
    assert "<p>## 附表</p>" in h
    assert "<p>&gt; 引用</p>" in h
    assert "<p>- 列表</p>" in h


def test_bold_in_table_cell_and_caption() -> None:
    b = Probatrix()
    b.table(["名", "值"], [["**梁**", "1"]])
    b.image_bytes(b"x", caption="**图**注")
    h = b.to_html(with_summary=False)
    assert "<td><b>梁</b></td>" in h
    assert "<small><b>图</b>注</small>" in h


# ---------------------------------------------------------------- 图文环绕（side）
def test_image_float_right_with_caption() -> None:
    b = Probatrix()
    b.p("截面说明。")
    b.image_bytes(b"\x89PNG-float", caption="截面简图", side="right")
    b.p("环绕段落。")
    b.formula(r"E=mc^2")
    h = b.to_html(with_summary=False)
    assert "<figure class='cb-float-right'><img src='data:image/png;base64," in h
    assert "<figcaption>截面简图</figcaption></figure>" in h
    assert "<small>" not in h          # 环绕图名走 figcaption，不再有独立小注


def test_image_float_left_no_caption() -> None:
    h = Probatrix().image_bytes(b"x", side="left").to_html(with_summary=False)
    assert "<figure class='cb-float-left'><img src='data:image/png;base64,eA==' alt='图'></figure>" in h
    assert "<figcaption>" not in h     # 无图名则无 caption 元素


def test_side_unknown_rejected() -> None:
    import pydantic
    with pytest.raises(ValueError):
        Probatrix().image_bytes(b"x", side="up")  # type: ignore[arg-type]


# ---------------------------------------------------------------- Markdown 块（markdown）
def test_markdown_headings_paragraph_bold_code_math() -> None:
    """markdown() 认块级结构，行内认 code/**粗体**/$…$——与 p() 的分工见文档。"""
    md = "# 标题\n\n## 小节\n\n第一段**粗体**，行内 `code` 与公式 $f=305$。"
    h = Probatrix().markdown(md).to_html(with_summary=False)
    assert h.split("\n") == [
        "<h1>标题</h1>",
        "<h2>小节</h2>",
        "<p>第一段<b>粗体</b>，行内 <code>code</code> 与公式 $f=305$。</p>",
    ]
    assert Probatrix().markdown("#### 四级标题").to_html() == "<h4>四级标题</h4>"


def test_markdown_code_fence_verbatim() -> None:
    """围栏代码块：内容整体转义，内部的 ** 与 <tag> 一律不解析。"""
    md = "```python\nb.p('<b>**x**</b>')\n```"
    h = Probatrix().markdown(md).to_html(with_summary=False)
    assert h == ("<pre><code class='language-python'>"
                 "b.p('&lt;b&gt;**x**&lt;/b&gt;')</code></pre>")


def test_markdown_code_fence_unclosed_keeps_body() -> None:
    h = Probatrix().markdown("```\n行1\n行2").to_html(with_summary=False)
    assert h == "<pre><code>行1\n行2</code></pre>"


def test_markdown_lists() -> None:
    h = Probatrix().markdown("- 甲\n- 乙\n\n1. 一\n2. 二").to_html(with_summary=False)
    assert "<ul><li>甲</li><li>乙</li></ul>" in h
    assert "<ol><li>一</li><li>二</li></ol>" in h


def test_markdown_list_continuation_merges() -> None:
    """缩进续行并入上一项（不做深层嵌套）。"""
    h = Probatrix().markdown("- 第一项\n  续行说明").to_html(with_summary=False)
    assert h == "<ul><li>第一项\n续行说明</li></ul>"


def test_markdown_table() -> None:
    md = "| 名 | `值` |\n| --- | --- |\n| **梁** | 1 |"
    h = Probatrix().markdown(md).to_html(with_summary=False)
    assert h == ("<table><tr><th>名</th><th><code>值</code></th></tr>"
                 "<tr><td><b>梁</b></td><td>1</td></tr></table>")


def test_markdown_quote_and_rule() -> None:
    h = Probatrix().markdown("> 注意：**别忘**\n\n---").to_html(with_summary=False)
    assert h == "<blockquote><p>注意：<b>别忘</b></p></blockquote>\n<hr>"


def test_markdown_links_site_links_are_not_anchors() -> None:
    """站内链接（.md）渲染成行内代码——预览区里真链接会把整个界面跳走。"""
    md = ("见 [模板开发指南.md](模板开发指南.md) 与 "
          "[规范](https://example.com/a?b=1&c=2)。")
    h = Probatrix().markdown(md).to_html(with_summary=False)
    assert "<code>模板开发指南.md</code>" in h
    assert "<a href=" not in h.split("与 ")[0]
    assert ("<a href='https://example.com/a?b=1&amp;c=2' target='_blank' "
            "rel='noopener noreferrer'>规范</a>") in h


def test_markdown_escapes_html() -> None:
    h = Probatrix().markdown("<script>alert(1)</script>").to_html(with_summary=False)
    assert "<script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in h


def test_markdown_soft_break_join() -> None:
    """段内折行：中文直接相连；ASCII 结尾与汉字之间补空格（全角标点前不补）。"""
    md = "中文折行\n继续写。\n见 examples/gl.py\n的写法，以及 `x`\n（括号）"
    h = Probatrix().markdown(md).to_html(with_summary=False)
    assert h == ("<p>中文折行继续写。见 examples/gl.py 的写法，以及 "
                 "<code>x</code>（括号）</p>")


def test_markdown_block_mixes_with_other_items() -> None:
    b = Probatrix(title="T")
    b.h2("1. 说明")
    b.markdown("| a |\n| --- |\n| 1 |")
    h = b.to_html(with_summary=False)
    assert h == ("<h1>T</h1>\n<h2>1. 说明</h2>\n"
                 "<table><tr><th>a</th></tr><tr><td>1</td></tr></table>")


def test_markdown_block_to_markdown_is_verbatim() -> None:
    """Markdown 导出物原样回放（不二次加工）。"""
    assert Probatrix().markdown("## 标题\n\n正文").to_markdown() == "## 标题\n\n正文\n"


def test_p_still_never_parses_markdown() -> None:
    """markdown() 不改变 p() 的契约：段落里的结构标记仍是字面文字。"""
    h = Probatrix().p("## 标题").markdown("## 标题").to_html(with_summary=False)
    assert h == "<p>## 标题</p>\n<h2>标题</h2>"


# ---------------------------------------------------------------- Markdown 图片（本地相对路径内嵌）
# 独占一行的 ![图注](相对路径) → 预览/HTML 导出内嵌 base64 data URI；只读 base_dir
# 及其下级，失败就地提示并保留引用路径。契约文档：docs/manual/06-计算书排版.md。
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
_JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
_GIF = b"GIF89a-fake"
_WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 fake"


def _put(root: Path, rel: str, data: bytes = _PNG_1PX) -> Path:
    """在测试临时目录里落一张图片（可按需造子目录）。"""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _html(md: str, base_dir: Path | None = None) -> str:
    return Probatrix().markdown(md, base_dir=base_dir).to_html(with_summary=False)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_markdown_image_embeds_data_uri(tmp_path: Path) -> None:
    """成功即内嵌 base64（图注进 figcaption），不含任何文件路径。"""
    _put(tmp_path, "images/section.png")
    h = _html("![截面简图](images/section.png)", tmp_path)
    assert h == ("<figure class='cb-md-img'>"
                 f"<img src='data:image/png;base64,{_b64(_PNG_1PX)}' alt='截面简图'>"
                 "<figcaption>截面简图</figcaption></figure>")


def test_markdown_image_empty_caption_and_odd_filename(tmp_path: Path) -> None:
    """空图注（无 figcaption）与带空格、中文的文件名都可用。"""
    _put(tmp_path, "images/截面 简图 1.png")
    h = _html("![](images/截面 简图 1.png)", tmp_path)
    assert h.startswith("<figure class='cb-md-img'><img src='data:image/png;base64,")
    assert h.endswith(" alt=''></figure>")
    assert "<figcaption>" not in h


def test_markdown_image_ends_previous_paragraph(tmp_path: Path) -> None:
    """图片行自成一块，并结束上一段（不被吞进前一段落）。"""
    _put(tmp_path, "a.png")
    h = _html("说明文字\n![图](a.png)\n随后说明。", tmp_path)
    lines = h.split("\n")
    assert lines[0] == "<p>说明文字</p>"
    assert lines[1].startswith("<figure class='cb-md-img'>")
    assert lines[2] == "<p>随后说明。</p>"
    assert len(lines) == 3


def test_markdown_image_inside_fence_stays_text(tmp_path: Path) -> None:
    """围栏代码块优先：里面的图片标记是文字，不读文件、不内嵌。"""
    _put(tmp_path, "a.png")
    h = _html("```\n![图](a.png)\n```", tmp_path)
    assert h == "<pre><code>![图](a.png)</code></pre>"
    assert "data:image" not in h


def test_markdown_image_only_at_block_level(tmp_path: Path) -> None:
    """语法只认独占一行：行内混排与列表项里的图片标记仍是文字。"""
    _put(tmp_path, "a.png")
    h = _html("见图 ![图](a.png)。\n\n- ![图](a.png)", tmp_path)
    assert "data:image" not in h
    assert "<p>见图 !<code>图</code>。</p>" in h
    assert "<ul><li>!<code>图</code></li></ul>" in h


def test_markdown_image_in_quote_embeds(tmp_path: Path) -> None:
    """引用块内整行图片同样内嵌（引用递归走同一套块解析）。"""
    _put(tmp_path, "a.png")
    h = _html("> ![图](a.png)", tmp_path)
    assert h.startswith("<blockquote><figure class='cb-md-img'>")
    assert h.endswith("</figure></blockquote>")


def test_markdown_image_without_base_dir_is_note() -> None:
    """不给 base_dir 就不读文件：图片位置留一行提示，并显示引用路径。"""
    h = Probatrix().markdown("![截面简图](images/section.png)").to_html(with_summary=False)
    assert h == ("<p class='cb-md-img-note'>图片未嵌入：<code>images/section.png</code>"
                 "（未提供 base_dir，相对路径无从解析）</p>")
    assert "data:image" not in h


def test_md_to_html_takes_base_dir_keyword(tmp_path: Path) -> None:
    """md_to_html 与 markdown() 的 base_dir 关键字约定一致。"""
    from probatrix.md import md_to_html
    _put(tmp_path, "a.png")
    assert md_to_html("![](a.png)", base_dir=tmp_path).startswith(
        "<figure class='cb-md-img'><img src='data:image/png;base64,")


def test_markdown_image_rejects_escape_out_of_base_dir(tmp_path: Path) -> None:
    """`..` 逃逸被拒——即使目标文件真实存在也读不到。"""
    base = tmp_path / "doc"
    base.mkdir()
    _put(tmp_path, "secret.png")           # base 之外、确实存在
    h = _html("![x](../secret.png)", base)
    assert h == ("<p class='cb-md-img-note'>图片未嵌入：<code>../secret.png</code>"
                 "（路径超出 base_dir 范围）</p>")


def _link_dir(link: Path, target: Path) -> bool:
    """尽力造一个指向 target 的目录链接：符号链接优先，Window 无权限时退到目录联接。

    返回是否建成——两条路都不通（权限受限）时由调用方跳过测试。
    """
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name != "nt":
        return False
    done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                          capture_output=True)
    return done.returncode == 0


def test_markdown_image_symlink_escape_rejected(tmp_path: Path) -> None:
    """目录链接指到 base_dir 之外同样被拒（resolve 之后再判包含关系）。"""
    base = tmp_path / "doc"
    base.mkdir()
    outside = tmp_path / "outside"
    _put(outside, "secret.png")            # base 之外、确实存在
    if not _link_dir(base / "pics", outside):
        pytest.skip("当前环境不允许创建符号链接或目录联接")
    h = _html("![x](pics/secret.png)", base)
    assert h == ("<p class='cb-md-img-note'>图片未嵌入：<code>pics/secret.png</code>"
                 "（路径超出 base_dir 范围）</p>")


@pytest.mark.parametrize(("ref", "reason"), [
    ("/etc/passwd.png", "只接受 base_dir 内的相对路径"),
    ("C:/Windows/a.png", "只接受 base_dir 内的相对路径"),
    (r"\\server\share\a.png", "只接受 base_dir 内的相对路径"),
    ("https://example.com/a.png", "只接受 base_dir 内的相对路径"),
    ("data:image/png;base64,AAAA", "只接受 base_dir 内的相对路径"),
    ("images/a.png:stream", "只接受 base_dir 内的相对路径"),
    ("images/a.svg", "只支持 PNG/JPEG/WebP/GIF 图片"),
    ("images/missing.png", "文件不存在"),
])
def test_markdown_image_bad_paths_are_notes(tmp_path: Path, ref: str, reason: str) -> None:
    """绝对路径、盘符、UNC、URL、ADS 数据流、格式白名单外、文件缺失——都是就地提示。"""
    h = _html(f"![图]({ref})", tmp_path)
    assert h.startswith("<p class='cb-md-img-note'>图片未嵌入：<code>")
    assert f"（{reason}）</p>" in h
    assert "<img" not in h


def test_markdown_image_note_keeps_escaping(tmp_path: Path) -> None:
    """提示里的引用路径照旧 HTML 转义（尖括号、引号不会变成标记）。"""
    h = _html('![图](images/<b>"x".png)', tmp_path)
    assert "<b>" not in h
    assert "&lt;b&gt;&quot;x&quot;.png" in h


def test_markdown_image_invalid_content_or_empty(tmp_path: Path) -> None:
    """扩展名像图片但内容不是图、空文件、目录：都以提示代替 <img>。"""
    _put(tmp_path, "fake.png", b"not an image")
    _put(tmp_path, "empty.png", b"")
    (tmp_path / "dir.png").mkdir()
    for name, reason in (
        ("fake.png", "文件内容不是 PNG/JPEG/WebP/GIF"),
        ("empty.png", "文件是空的"),
        ("dir.png", "这是目录，不是图片文件"),
    ):
        h = _html(f"![图]({name})", tmp_path)
        assert f"（{reason}）</p>" in h
        assert "data:image" not in h


@pytest.mark.parametrize(("name", "data", "mime"), [
    ("a.png", _PNG_1PX, "image/png"),
    ("a.jpg", _JPEG, "image/jpeg"),
    ("a.JPEG", _JPEG, "image/jpeg"),
    ("a.gif", _GIF, "image/gif"),
    ("a.webp", _WEBP, "image/webp"),
    ("a.png", _JPEG, "image/jpeg"),        # 扩展名骗人时按真实文件头给 MIME
])
def test_markdown_image_format_whitelist(tmp_path: Path, name: str,
                                         data: bytes, mime: str) -> None:
    """白名单四种格式都内嵌；MIME 按文件头判定，不看扩展名。"""
    _put(tmp_path, name, data)
    h = _html(f"![图]({name})", tmp_path)
    assert f"<img src='data:{mime};base64,{_b64(data)}' alt='图'>" in h


def test_markdown_image_keeps_markdown_source_in_export(tmp_path: Path) -> None:
    """Markdown 导出物保留原文（图片仍是 ![图注](路径)），只有 HTML 内嵌。"""
    _put(tmp_path, "images/section.png")
    md = "## 简图\n\n![截面简图](images/section.png)"
    book = Probatrix().markdown(md, base_dir=tmp_path)
    assert book.to_markdown() == md + "\n"
    assert "data:image/png;base64," in book.to_html(with_summary=False)


def test_markdown_image_real_repo_png() -> None:
    """仓库里的真 PNG（文档插图）也能嵌入——验证真实字节而非仅文件头。"""
    manual = Path(__file__).resolve().parents[1] / "docs" / "manual"
    if not (manual / "images" / "derive-layout.png").is_file():
        pytest.skip("仓库未带示例图片")
    h = _html("![推导排版](images/derive-layout.png)", manual)
    assert "src='data:image/png;base64,iVBORw0KGgo" in h
    assert h.endswith("<figcaption>推导排版</figcaption></figure>")


def test_p_keeps_image_syntax_literal(tmp_path: Path) -> None:
    """p() 契约不变：段落里的图片标记永远按字面文字显示。"""
    _put(tmp_path, "a.png")
    assert Probatrix().p("![图](a.png)").to_html(with_summary=False) == "<p>![图](a.png)</p>"


def test_markdown_image_unparseable_path_is_note(tmp_path: Path) -> None:
    """路径里的非法字符（NUL）只留提示：不让一张图把整篇计算顶掉。"""
    h = _html("![x](a\x00b.png)", tmp_path)
    assert h.startswith("<p class='cb-md-img-note'>图片未嵌入：<code>a\ufffdb.png</code>（")
    assert h.endswith("）</p>")
    assert "\x00" not in h                     # 控制字符不进 HTML
    assert "<img" not in h


def test_markdown_image_resolve_error_is_note(tmp_path: Path, monkeypatch) -> None:
    """解析路径本身报错（链接环等，Python 版本不同会不同）也只留提示。"""
    def boom(self, *args, **kwargs):
        raise RuntimeError("链接环")
    monkeypatch.setattr(Path, "resolve", boom)
    h = _html("![x](a.png)", tmp_path)
    assert h == ("<p class='cb-md-img-note'>图片未嵌入：<code>a.png</code>"
                 "（路径无法解析：链接环）</p>")


def test_markdown_image_read_error_is_note(tmp_path: Path, monkeypatch) -> None:
    """读文件报错（权限等）同样折成提示，不抛给计算。"""
    _put(tmp_path, "a.png")

    def boom(self, *args, **kwargs):
        raise PermissionError(13, "拒绝访问")
    monkeypatch.setattr(Path, "read_bytes", boom)
    h = _html("![x](a.png)", tmp_path)
    assert "（读取失败：拒绝访问）</p>" in h
    assert "<img" not in h


def test_markdown_image_path_kept_inside_base_dir(tmp_path: Path) -> None:
    """`..` 只在真的指到 base_dir 之外时才拒；指回目录内的相对路径照常可用。"""
    _put(tmp_path, "images/section.png")
    h = _html("![图](images/../images/section.png)", tmp_path)
    assert "<img src='data:image/png;base64," in h
