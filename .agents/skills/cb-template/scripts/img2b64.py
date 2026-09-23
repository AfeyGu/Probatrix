#!/usr/bin/env python3
"""图片 → base64 内嵌片段(供 CalcBook 模板作者用)。

用途:模板需要插入**静态图片**(扫描件、节点大样图等,非 matplotlib 动态画图)时,
把图片转成可直接粘贴进模板 .py 的片段,配合 `b.image_bytes(data, mime=...)` 使用。
内嵌 base64 保持「一个模板 = 一个 .py 文件」的契约;不要用 b.image(path)(离线导出裂图)。

用法:
    python img2b64.py <图片路径> [--crop L,T,R,B] [--max-px N] [--quality Q]
                     [--to png|jpg] [--var NAME] [-o 输出.py] [--uri]

纯转换仅标准库;--crop/--max-px/--quality/--to 需要 Pillow(有 matplotlib 的环境必有)。
默认不做任何处理、原样转换(不改用户的图);要瘦身时显式给参数,处理顺序:裁剪→缩放→重编码。
--max-px:最长边缩到 N 像素(保持宽高比);--quality:JPEG 质量(默认 85,仅 JPEG 生效);
--crop:左,上,右,下,可写像素或百分比(如 "10%,10%,90%,90%");--to:转格式(PNG 转 JPEG 可大幅减小)。

默认把片段打到 stdout(--uri 则只打 data URI);-o 写入文件(大图必用,别刷屏)。
支持 png/jpg/jpeg/gif/webp/bmp/svg。
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

# 本脚本的消费者是 agent/终端(Git Bash 为 UTF-8):管道下 Windows 默认走 GBK 会乱码,强制统一
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8")

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
CHUNK = 100          # 每行 base64 字符数(方便 diff 与编辑器)
WARN_IMAGE_KB = 200  # 处理后仍超过此大小,提醒进一步瘦身
TO_FMT = {"png": ("PNG", "image/png"), "jpg": ("JPEG", "image/jpeg")}
FMT_BY_EXT = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
              ".gif": "GIF", ".webp": "WEBP", ".bmp": "BMP"}


def parse_crop(s: str, w: int, h: int) -> tuple[int, int, int, int]:
    """解析 "L,T,R,B"(像素或带 % 的百分比)为 Pillow 裁剪框,越界即报错。"""
    def val(x: str, total: int) -> int:
        x = x.strip()
        return round(total * float(x[:-1]) / 100) if x.endswith("%") else int(x)

    try:
        l, t, r, b = (val(p, n) for p, n in zip(s.split(","), (w, h, w, h)))
    except ValueError:
        sys.exit(f"错误:--crop 格式应为 L,T,R,B(像素或 %),收到 {s!r}")
    if not (0 <= l < r <= w and 0 <= t < b <= h):
        sys.exit(f"错误:裁剪框 {s} 越界或无效(原图 {w}x{h})")
    return (l, t, r, b)


def process(path: Path, args) -> tuple[bytes, str]:
    """按参数做 裁剪→缩放→重编码,返回 (处理后字节, mime);无处理参数则原样返回。"""
    ext = path.suffix.lower()
    if not (args.crop or args.max_px or args.to):
        return path.read_bytes(), MIME[ext]
    if ext == ".svg":
        sys.exit("错误:SVG 是矢量格式,不能裁剪/压缩;请先转成位图再处理")

    try:
        from PIL import Image
    except ImportError:
        sys.exit("错误:裁剪/压缩需要 Pillow:pip install pillow")

    src = path.read_bytes()
    img = Image.open(io.BytesIO(src))
    w0, h0 = img.size
    if args.crop:
        img = img.crop(parse_crop(args.crop, w0, h0))
    if args.max_px and max(img.size) > args.max_px:
        img.thumbnail((args.max_px, args.max_px), Image.LANCZOS)
    fmt, mime = TO_FMT[args.to] if args.to else (FMT_BY_EXT[ext], MIME[ext])
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.save(buf, fmt, quality=args.quality, optimize=True)
    elif fmt == "PNG":
        img.save(buf, fmt, optimize=True)
    else:
        img.save(buf, fmt)
    data = buf.getvalue()
    print(f"处理:{w0}x{h0} → {img.size[0]}x{img.size[1]},"
          f"{len(src) / 1024:.0f} KB → {len(data) / 1024:.0f} KB"
          f"({fmt}{f', q{args.quality}' if fmt == 'JPEG' else ''})", file=sys.stderr)
    return data, mime


def snippet(path: Path, var: str, mime: str, b64: str, kb: float) -> str:
    lines = "\n    ".join(f'"{b64[i:i + CHUNK]}"' for i in range(0, len(b64), CHUNK))
    return (
        f"# ==== 内嵌图片:{path.name}({kb:.1f} KB,{mime})====\n"
        f"import base64\n"
        f'{var} = base64.b64decode(\n    {lines}\n)\n'
        f'# 用法:b.image_bytes({var}, mime="{mime}", caption="{path.stem}")\n'
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="图片转 base64,生成 CalcBook 模板内嵌片段")
    ap.add_argument("image", type=Path, help="图片文件")
    ap.add_argument("--crop", metavar="L,T,R,B",
                    help='裁剪:左,上,右,下(像素或百分比,如 "10%%,10%%,90%%,90%%")')
    ap.add_argument("--max-px", dest="max_px", type=int, metavar="N",
                    help="最长边缩到 N 像素(保持宽高比)")
    ap.add_argument("--quality", type=int, default=85, help="JPEG 质量(默认 85,仅 JPEG 生效)")
    ap.add_argument("--to", choices=sorted(TO_FMT), help="转格式(png/jpg);PNG 照片转 JPEG 可大幅减小")
    ap.add_argument("--var", default="_IMG", help="片段里的变量名(默认 _IMG)")
    ap.add_argument("-o", dest="out", type=Path, help="写入文件而非 stdout")
    ap.add_argument("--uri", action="store_true", help="只输出 data URI(调试/预览用)")
    args = ap.parse_args()

    if not args.image.is_file():
        sys.exit(f"错误:找不到图片 {args.image}")
    if args.image.suffix.lower() not in MIME:
        sys.exit(f"错误:不认识的扩展名 {args.image.suffix!r},支持:{' '.join(MIME)}")

    data, mime = process(args.image, args)
    b64 = base64.b64encode(data).decode("ascii")
    kb = len(data) / 1024
    if kb > WARN_IMAGE_KB:
        print(f"警告:处理后仍 {kb:.0f} KB(base64 后 {len(b64) / 1024:.0f} KB),"
              f"内嵌会明显撑大模板文件;可再降 --max-px/--quality 或 --to jpg。", file=sys.stderr)

    if args.uri:
        text = f"data:{mime};base64,{b64}"
    else:
        text = snippet(args.image, args.var, mime, b64, kb)

    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"已写入 {args.out}({len(text) / 1024:.1f} KB)", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
