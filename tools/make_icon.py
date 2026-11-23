"""生成 Probatrix 图标 assets/icon.ico（多尺寸：256/48/32/16）。

图形与 web/public/icon.svg 同款：深色细圆角方 + ∑ 求和符号线稿。
绘制方式：4x 超采样（抗锯齿）→ LANCZOS 降采样，无需 cairo 等原生库。

改图形时同步修改 icon.svg（网页 favicon 用）与这里。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SCALE = 4  # 超采样倍数
C = 256 * SCALE  # 设计画布 1024

BG = "#1e2430"      # 底：深蓝灰
FG = "#faf9f7"      # 线：米白
RADIUS = 52 * SCALE
STROKE = 22 * SCALE

# ∑ 折线顶点（icon.svg viewBox 256 坐标 ×SCALE）：顶横 → 中斜 → 底横
PTS = [(60, 66), (188, 66), (124, 128), (188, 190), (60, 190)]


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (C, C), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14 * SCALE] * 2 + [242 * SCALE] * 2,
                        radius=RADIUS, fill=BG)
    pts = [(x * SCALE, y * SCALE) for x, y in PTS]
    d.line(pts, fill=FG, width=STROKE, joint="curve")
    for x, y in pts[::4]:  # 线端圆头（round cap 近似）
        r = STROKE / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=FG)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [256, 48, 32, 16]
    imgs = [draw_icon(s) for s in sizes]
    out = ROOT / "assets" / "icon.ico"
    out.parent.mkdir(exist_ok=True)
    imgs[0].save(out, format="ICO", sizes=[(s, s) for s in sizes],
                 append_images=imgs[1:])
    print(f"已生成 {out}（{', '.join(str(s) for s in sizes)}px）")


if __name__ == "__main__":
    main()