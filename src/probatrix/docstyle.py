"""计算书文档排版 CSS：预览与导出 HTML 共用的同一套规则。

- 前端预览通过 GET /api/doc.css 加载（见 server.py，index.html 里 link 引用）
- 导出页模板直接注入 @@DOCSTYLE@@（server.py 的 _HTML_TMPL）

改动文档排版时只改这个文件，两端自动一致——不要在别处复制这份样式。
"""

DOC_CSS = """\
/* ---- Probatrix 文档排版（.cb-doc）：预览与导出共用 ---- */
.cb-doc { font: 15px/1.75 "Source Han Serif SC", "Noto Serif SC", SimSun, serif;
          color: #111; }
.cb-doc h1, .cb-doc h2, .cb-doc h3 { font-weight: 600; margin: 18px 0 8px; }
.cb-doc h1 { font-size: 22px; }
.cb-doc h2 { font-size: 18px; }
.cb-doc h3 { font-size: 16px; }
.cb-doc h4, .cb-doc h5, .cb-doc h6 { font-weight: 600; font-size: 15px; margin: 14px 0 6px; }
.cb-doc p { margin: 8px 0; }
.cb-doc ul, .cb-doc ol { margin: 8px 0; padding-left: 26px; }
.cb-doc li { margin: 3px 0; }
.cb-doc pre { margin: 10px 0; padding: 10px 14px; background: #f7f6f3;
              border: 1px solid #e6e3dd; border-radius: 4px; overflow-x: auto;
              white-space: pre-wrap; word-break: break-word;
              font: 13px/1.65 "Cascadia Mono", Consolas, "Courier New", monospace; }
.cb-doc pre code { background: none; padding: 0; font: inherit; }
.cb-doc hr { border: 0; border-top: 1px solid #d5d3cf; margin: 18px 0; }
.cb-doc a { color: #1f5aa6; text-decoration: none; border-bottom: 1px solid #c3d3e8; }
.cb-doc table { border-collapse: collapse; margin: 12px 0; width: 100%; }
.cb-doc th, .cb-doc td { border: 1px solid #d5d3cf; padding: 4px 10px; text-align: left; }
.cb-doc th { background: #f5f4f1; font-weight: 600; }
.cb-doc blockquote { margin: 6px 0; padding: 4px 12px; color: #555;
                     border-left: 3px solid #d5d3cf; font-size: 13px; }
.cb-doc code { background: #f5f5f5; padding: 1px 4px; border-radius: 3px; }
.cb-doc img { max-width: 100%; }
.cb-doc .katex-display { margin: 10px 0; }

/* ---- 图文环绕（side="left"/"right"）：文字段落贴边环绕，块级内容收边回全宽 ---- */
.cb-doc figure.cb-float-right, .cb-doc figure.cb-float-left {
  width: 45%; margin: 6px 0 10px; }
.cb-doc figure.cb-float-right { float: right; margin-left: 16px; }
.cb-doc figure.cb-float-left { float: left; margin-right: 16px; }
.cb-doc figure.cb-float-right img, .cb-doc figure.cb-float-left img { width: 100%; }
.cb-doc figcaption { text-align: center; font-size: 12.5px; color: #555; margin-top: 6px; }

/* ---- Markdown 图片（独占一行的 ![图注](相对路径)）：居中、不放大、不超正文宽 ---- */
.cb-doc figure.cb-md-img { margin: 12px auto; text-align: center; }
.cb-doc figure.cb-md-img img { display: block; margin: 0 auto; width: auto;
                               max-width: 100%; height: auto; }
/* 图片没能嵌入时的就地提示（保留引用路径，提醒作者补图） */
.cb-doc p.cb-md-img-note { margin: 10px 0; padding: 6px 10px; color: #7a5c1e;
                           background: #fdf7e6; border: 1px dashed #e3d3a4;
                           border-radius: 4px; font-size: 13px; }
.cb-doc h1, .cb-doc h2, .cb-doc h3, .cb-doc p.formula, .cb-doc p.item,
.cb-doc blockquote, .cb-doc table, .cb-doc pre, .cb-doc ul, .cb-doc ol,
.cb-doc hr, .cb-doc figure.cb-md-img, .cb-doc p.cb-md-img-note { clear: both; }

/* ---- 打印（PDF 送审）：分页保护 ---- */
@media print {
  .cb-doc table, .cb-doc p.formula, .cb-doc pre,
  .cb-doc figure.cb-float-right, .cb-doc figure.cb-float-left,
  .cb-doc figure.cb-md-img, .cb-doc p.cb-md-img-note { page-break-inside: avoid; }
  .cb-doc h1, .cb-doc h2, .cb-doc h3, .cb-doc h4 { page-break-after: avoid; }
}
"""
