# Probatrix · 计算书工具

<img src="web/public/icon.svg" alt="Probatrix 图标" width="64" />

结构设计中「小构件」的批量计算与计算书生成工具。

解决的问题：验算小软件不能批量输入参数；Excel 能批量但复杂公式难写、卡、导出计算书要手动排版。

思路：**用 Python 写计算模板**（想多复杂写多复杂），**参数在表格里批量输入**（支持从 Excel 粘贴），
**计算书由模板生成 HTML + LaTeX 公式**（无代码、可打印），工程文件保存全部参数可复现。

<img src="assets/screenshot-main.png" alt="Probatrix 桌面窗口界面" width="720" />

左侧选择计算项，中间输入参数，右侧实时预览计算书。批量表格支持从 Excel 粘贴。

## 安装

**Windows 便携版**：在装有 **Microsoft Edge WebView2 Runtime** 的 Windows 10/11 x64 上，完整解压 `probatrix-<版本>-windows-x64-portable.zip`，双击 `Probatrix.exe`。移动时带上整个文件夹，包内已附 Python 与常用计算库，内置示例可离线计算。

**浏览器版**：

```bash
git clone https://github.com/AfeyGu/Probatrix.git
cd Probatrix
python -m pip install .
probatrix serve --templates examples
```

默认地址 `http://127.0.0.1:8317`，端口被占用时自动递加。

界面操作、批量表格、导出选项与常见问题见 **[docs/manual/使用说明.md](docs/manual/使用说明.md)**。

## 写一个计算模板

第一次写模板，可以先复制软件自带的钢梁示例，改名字并跑出自己的计算书。[模板快速开始](docs/manual/模板快速开始.md)

一个模板 = 一个 `.py` 文件，放进模板目录即被自动扫描：**参数声明** + **计算书写法**。

```python
from pydantic import BaseModel
from probatrix import Probatrix, Field, template


class GLParams(BaseModel):
    fy: float = Field(215, label="抗弯强度设计值", unit="N/mm²", group="材料", gt=0)
    Wx: float = Field(1.0e6, label="截面模量", unit="mm³", group="截面", gt=0)
    Mx: float = Field(100, label="弯矩设计值", unit="kN·m", group="荷载")


@template("钢梁强度验算", description="GB 50017-2017 弯曲正应力验算")
def calc(p: GLParams) -> Probatrix:
    b = Probatrix(title="钢梁强度验算")
    sigma = p.Mx * 1e6 / p.Wx                    # kN·m → N·mm
    b.h2("1. 强度验算")
    b.formula(r"\sigma = \dfrac{M_x}{W_x} \le f", cite=("GB 50017-2017", "4.1.1"))
    b.subs(rf"\sigma = {sigma:.1f}\ \mathrm{{N/mm^2}}")
    b.check("抗弯强度", value=sigma, limit=p.fy, unit="N/mm²", expr=r"\sigma \le f")
    return b
```

`Field` 的元信息直接驱动界面：单件表单、批量表格列、工程文件三处同源。`b.check()` 在正文输出判定行，并在计算书末尾自动汇总「验算结论」表；`b.metric()` 可为批量表格追加结果指标列。`b.markdown(text)` 把整篇 Markdown 当正文排（标题、代码块、列表、表格）——内置的「使用文档」模板就是用它在软件里读 `docs/` 下的手册。

模板手册按快速开始、参数输入界面、计算与验算、计算书排版组织。可运行示例在 `examples/`。[模板开发指南](docs/manual/模板开发指南.md) · [示例目录](examples/)

## 当前状态

MVP 已具备：模板加载与刷新、参数声明驱动界面、单项实时预览（与导出同源排版）、
批量表格（列显隐 / 统一设置 / Excel 粘贴 / 复制行 / 排序 / 列宽拖动）、
`.pbproj` 工程读写、模板 hash 校验、自包含 HTML 导出、三套浅色主题。

尚未实现：参数联动与派生（选截面型号自动带截面特性）、Word 导出、依赖模块 hash、模板库集中分发。

## 文档

| 我想… | 看这里 |
|---|---|
| 装软件、出计算书 | [docs/manual/使用说明.md](docs/manual/使用说明.md) |
| 写模板 | [docs/manual/模板开发指南.md](docs/manual/模板开发指南.md) |
| 改代码前了解系统怎么运转 | [docs/架构全景.md](docs/架构全景.md) |
| 调界面样式 | [docs/subsystems/UI设计规范.md](docs/subsystems/UI设计规范.md) |
| 起开发环境 / 打包发布 | [docs/cookbook/](docs/cookbook/) |
| 文档怎么组织 | [docs/README.md](docs/README.md) |

开发速览：

```bash
pip install -e .
python -m pytest tests -q
cd web && npm install && npm run dev    # 前端开发模式，代理到 8317
```

构建 Windows 便携包：`python tools/build_release.py`（详见 [docs/cookbook/构建与发布.md](docs/cookbook/构建与发布.md)）。

仓库里的 `AGENTS.md` 是给 AI agent 的开发准则与易错点清单。
