"""命令行入口：calcbook serve [--templates 目录] [--port 端口] [--no-browser]"""

from __future__ import annotations

import argparse

from .server import default_template_dir, main


def cli() -> None:
    parser = argparse.ArgumentParser(prog="calcbook", description="CalcBook 计算书工具")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动本地服务并打开浏览器")
    serve.add_argument("--templates", default=None,
                       help=f"模板目录（默认 {default_template_dir()}）")
    serve.add_argument("--port", type=int, default=8317,
                       help="起始端口（被占用时自动递加寻找空闲端口）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--ui", choices=["browser", "webview"], default="browser",
                       help="界面形态：browser 默认浏览器 / webview 桌面窗口（需 pywebview）")

    args = parser.parse_args()
    if args.command == "serve":
        main(
            host=args.host, port=args.port,
            template_dir=args.templates,
            open_browser=not args.no_browser,
            ui=args.ui,
        )


if __name__ == "__main__":
    cli()
