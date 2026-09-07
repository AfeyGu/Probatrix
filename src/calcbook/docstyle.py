"""计算书文档排版 CSS：预览与导出 HTML 共用的同一套规则。

- 前端预览通过 GET /api/doc.css 加载（见 server.py，index.html 里 link 引用）
- 导出页模板直接注入 @@DOCSTYLE@@（server.py 的 _HTML_TMPL）

改动文档排版时只改这个文件，两端自动一致——不要在别处复制这份样式。
"""

DOC_CSS = """\
/* ---- CalcBook 文档排版（.cb-doc）：预览与导出共用 ---- */
.cb-doc { font: 15px/1.75 "Source Han Serif SC", "Noto Serif SC", SimSun, serif;
          color: #111; }
.cb-doc h1, .cb-doc h2, .cb-doc h3 { font-weight: 600; margin: 18px 0 8px; }
.cb-doc h1 { font-size: 22px; }
.cb-doc h2 { font-size: 18px; }
.cb-doc h3 { font-size: 16px; }
.cb-doc p { margin: 8px 0; }
.cb-doc table { border-collapse: collapse; margin: 12px 0; width: 100%; }
.cb-doc th, .cb-doc td { border: 1px solid #d5d3cf; padding: 4px 10px; text-align: left; }
.cb-doc th { background: #f5f4f1; font-weight: 600; }
.cb-doc blockquote { margin: 6px 0; padding: 4px 12px; color: #555;
                     border-left: 3px solid #d5d3cf; font-size: 13px; }
.cb-doc code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
.cb-doc img { max-width: 100%; }
.cb-doc .katex-display { margin: 10px 0; }
"""
