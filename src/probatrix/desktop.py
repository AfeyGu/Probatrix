"""桌面宿主的内部后台入口：``python.exe -u -X utf8 -m probatrix.desktop --templates <目录>``。

由 Tauri 宿主（``src-tauri/``）以无控制台方式启动，不是给人敲的命令。协议：

- 只绑定 IPv4 回环 ``127.0.0.1:0``（端口由系统分配），套接字保留并交给 Uvicorn；
- Uvicorn 启动生命周期走完（lifespan 启动 + 监听已建立）之后，向 stdout 输出一行并立即刷新::

      PROBATRIX_READY {"port":12345}

  就绪时机由 Uvicorn 自己的 ``startup`` 决定：本入口不自请求探活、也不设启动超时，
  何时放弃等待是宿主的截止时间。
- **stdout 只承载这一行协议**：进程一起手就把 ``sys.stdout`` 改道 stderr，模板模块顶层或
  计算过程中的 ``print``、uvicorn 日志、访问日志全都落到 stderr；
- 关闭来源：宿主关闭 stdin（EOF）→ 通知 Uvicorn 正常停机，正常模式与异常回收都走这条路，
  启动过程中来的 EOF 同样有效；
- 任何启动失败写 stderr 并以非零码退出。

与常规 ``probatrix serve`` 的差别只在服务配置：桌面模式不留 Vite 开发用的跨来源放行，
HTTP Host 只接受 ``127.0.0.1``（端口不限）；不拉起浏览器、不打原生窗口、不装环境。
模板、API、工程契约一律复用 ``server.create_app``。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import threading
import time
from typing import IO

import uvicorn

from .server import DESKTOP_HOST, create_app

#: 宿主只认 IPv4 回环（WebView2 载入 http://127.0.0.1:<port>/），地址与 Host 白名单同源
HOST = DESKTOP_HOST
#: 就绪行前缀：宿主按「前缀 + 一行 JSON」解析，端口来源仅此一处
READY_PREFIX = "PROBATRIX_READY "
#: 停机等待上限：宿主关窗后最长等这么久，避免残留连接无限期拖住退出
GRACEFUL_TIMEOUT = 3
_CHUNK = 4096


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # stdout 专用于协议行：先留住它，再把常规输出整体改道 stderr
    # （模板模块顶层也可能 print，改道必须早于 create_app 的模板扫描）。
    out = sys.stdout
    if sys.stderr is not None:
        sys.stdout = sys.stderr

    try:
        app = create_app(args.templates, desktop=True)
    except Exception as e:                       # 模板目录缺失/不可读：说清楚再退
        _fail(f"模板目录不可用（{args.templates or '默认目录'}）：{e}")
        return 1

    try:
        sock = _bind()
    except OSError as e:
        _fail(f"无法绑定 {HOST}:0：{e}")
        return 1
    port = sock.getsockname()[1]

    server = _Server(uvicorn.Config(
        app, host=HOST, port=port,
        log_level="warning",
        access_log=False,                        # 访问日志默认走 stdout，会污染协议行
        timeout_graceful_shutdown=GRACEFUL_TIMEOUT,
    ), out=out, port=port)

    threading.Thread(target=_watch_stdin, args=(server,),
                     name="probatrix-stdin", daemon=True).start()

    code = 0
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:                    # 控制台里手动跑时的 Ctrl+C
        pass
    except SystemExit as e:                      # uvicorn 启动失败时自己 sys.exit(...)
        code = e.code if isinstance(e.code, int) and e.code else 1
    finally:
        sock.close()                             # uvicorn 停机时已关，重复 close 无害

    never_started = not server.started and not server.eof.is_set()   # 没起来也没收到 EOF
    if code == 0 and (server.failed or never_started):
        code = 1
    return code


# ----------------------------------------------------------------------
class _Server(uvicorn.Server):
    """Uvicorn 子类：只加一个动作——启动生命周期完成时发就绪行。"""

    def __init__(self, config: uvicorn.Config, *, out: IO[str] | None, port: int) -> None:
        super().__init__(config)
        self._out = out
        self._port = port
        self.eof = threading.Event()   # 宿主已关闭 stdin（正常退出或异常回收）
        self.failed = False            # 就绪行写不出去（宿主已断管道）→ 非零退出

    async def startup(self, sockets=None) -> None:
        # 基类 startup：lifespan 启动 + 监听建立，末尾置 self.started；失败时它自己 sys.exit
        await super().startup(sockets=sockets)
        if not self.started:
            return
        if self.eof.is_set():          # 启动途中宿主已关 stdin：不再宣称就绪，直接停
            self.should_exit = True
            return
        if not _emit_ready(self._out, self._port):
            self.failed = True
            self.should_exit = True


def _emit_ready(out: IO[str] | None, port: int) -> bool:
    """写就绪行并立即刷新；宿主已断管道（stdout 不可写）返回 False。"""
    line = READY_PREFIX + json.dumps({"port": port}, separators=(",", ":")) + "\n"
    try:
        if out is None:
            raise ValueError("没有 stdout")
        out.write(line)
        out.flush()
    except (OSError, ValueError, AttributeError):
        _fail("无法输出就绪行（stdout 不可写）")
        return False
    return True


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m probatrix.desktop",
        description="Probatrix 桌面宿主后台（内部入口，协议见模块文档）",
    )
    parser.add_argument("--templates", default=None,
                        help="模板目录（缺省为 ~/Probatrix模板）")
    return parser.parse_args(argv)


def _bind() -> socket.socket:
    """绑定 IPv4 回环的临时端口（0 = 系统分配），返回值直接交给 Uvicorn。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, 0))
    except OSError:
        sock.close()
        raise
    return sock


def _watch_stdin(server: _Server) -> None:
    """丢弃 stdin 数据，直到 EOF，再通知 Uvicorn 停机。"""
    try:
        fd = sys.stdin.fileno()
        if sys.platform == "win32" and stat.S_ISFIFO(os.fstat(fd).st_mode):
            _watch_windows_pipe(fd)
        else:
            # 直接读描述符，避免解释器退出时等待 BufferedReader 的锁。
            while os.read(fd, _CHUNK):
                pass
    except (AttributeError, ValueError, OSError):  # stdin 不可用，等同 EOF
        pass
    finally:
        server.eof.set()
        server.should_exit = True


def _watch_windows_pipe(fd: int) -> None:
    """只读取管道已有的数据，避免阻塞读取与 NumPy 等扩展的加载相互等待。"""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    peek = ctypes.WinDLL("kernel32").PeekNamedPipe
    peek.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD)
    peek.restype = wintypes.BOOL
    handle = msvcrt.get_osfhandle(fd)
    # 二进制模式按可用字节读取，避免文本模式在 CR 后等待 LF。
    msvcrt.setmode(fd, os.O_BINARY)
    available = wintypes.DWORD()
    while peek(handle, None, 0, None, ctypes.byref(available), None):
        if not available.value:
            time.sleep(0.05)
        elif not os.read(fd, min(_CHUNK, available.value)):
            return


def _fail(message: str) -> None:
    print(f"Probatrix 桌面后台启动失败：{message}",
          file=sys.stderr or sys.__stderr__, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
