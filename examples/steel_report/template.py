"""读取同目录的计算书正文，并嵌入其中引用的图片。"""

from pathlib import Path

from pydantic import BaseModel

from probatrix import Probatrix, template


class ReportParams(BaseModel):
    pass


@template("图文计算书示例", description="将 Markdown 正文和截面简图排成一份计算书")
def calc(p: ReportParams) -> Probatrix:
    report = Path(__file__).with_name("report.md")
    text = report.read_text(encoding="utf-8")
    return Probatrix().markdown(text, base_dir=report.parent)
