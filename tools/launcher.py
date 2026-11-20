"""CalcBook 启动器（离线分发版，被 PyInstaller 打包为 CalcBook.exe 窗口程序）。

约定：CalcBook.exe 与 python/（内置 Python 环境）、examples/ 放在同一目录。

架构：python/ 是嵌入版 Python（见 tools/build_release.py），构建时已预装
calcbook 及全部依赖（numpy/scipy/pandas/matplotlib/openpyxl 等，含 pip）。
启动器只做三件事：环境自检 → 模板缺库自动补装（内置 pip，国内镜像）→
启动服务。完全离线可用；删掉整个解压目录即完全卸载。

窗口程序（PyInstaller --windowed）：全程无控制台黑窗；子进程一律
CREATE_NO_WINDOW；输出写 exe 同目录 calcbook.log（排障用）。

环境变量（覆盖默认行为，测试/排障用）：
  CALCBOOK_PYTHON      指定 python 可执行文件，默认用包内 python/python.exe
  CALCBOOK_PIP_INDEX   指定 pip 镜像源，默认阿里云
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path

LOG_NAME = "calcbook.log"  # 启动日志写在 exe 同目录，排障用
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 子进程一律不弹控制台窗口
PIP_INDEX = os.environ.get(
    "CALCBOOK_PIP_INDEX", "https://mirrors.aliyun.com/pypi/simple")

#: 合法的 pip 包名（同时堵住 `-` 开头的选项注入：依赖声明字符串会进 pip argv）
_PKG_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

LOG_PATH: Path | None = None  # main() 启动时指向 exe 同目录 calcbook.log

# 校验包内环境：calcbook 及核心依赖可导入，输出版本
CHECK_CODE = (
    "import calcbook, pydantic, fastapi, uvicorn, webview\n"
    "print(calcbook.__version__)\n")

# 模板依赖扫描脚本：AST 解析各模板的 __calcbook_requires__ 声明（不导入模板模块，
# 避免模块级副作用/自身缺库），用 find_spec 检查是否可用，输出缺失的 import 名。
# 单个文件解析失败只跳过该文件（stderr 记录），不让整体扫描失败——
# 否则一个语法错误的模板会让「依赖齐全」误判、自动安装永久失效。
DEPS_CHECK_SCRIPT = r'''
import ast
import importlib.util
import sys
from pathlib import Path

def collect(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__calcbook_requires__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        return [el.value for el in node.value.elts
                                if isinstance(el, ast.Constant) and isinstance(el.value, str)]
    return []

deps = []
for p in sorted(Path(sys.argv[1]).glob("*.py")):
    if p.name.startswith("_"):
        continue
    try:
        deps += collect(p)
    except (SyntaxError, OSError) as e:
        print(f"跳过无法解析的模板 {p.name}：{e}", file=sys.stderr)
missing = [d for d in dict.fromkeys(deps) if importlib.util.find_spec(d) is None]
if missing:
    print("\n".join(missing))
'''


def log(msg: str) -> None:
    print(f"[calcbook 启动器] {msg}", flush=True)


def _msgbox(text: str, title: str = "CalcBook", style: int = 0x40) -> None:
    """弹窗提示（窗口程序无控制台，错误/重要提示走系统弹窗）。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, style)
    except Exception:
        print(text, flush=True)


def fatal(msg: str) -> int:
    print(f"\n{msg}\n", flush=True)
    splash_close()
    _msgbox(f"{msg}\n\n（点击确定退出）", "CalcBook 启动失败", 0x10)  # MB_ICONERROR
    return 1


class _Tee:
    """输出重定向：launcher 为窗口程序（无控制台），全部输出写入日志留底。"""

    def __init__(self, path: Path):
        self._file = open(path, "w", encoding="utf-8")  # 每次运行重写，避免无限累积

    def write(self, s: str) -> int:
        try:
            sys.__stdout__.write(s)
            sys.__stdout__.flush()
        except Exception:
            pass
        self._file.write(s)
        self._file.flush()
        return len(s)

    def flush(self) -> None:
        try:
            sys.__stdout__.flush()
        except Exception:
            pass
        self._file.flush()


class _Splash:
    """极简启动画面：仅在补装模板依赖等耗时阶段显示；tkinter 不可用时静默跳过。"""

    def __init__(self) -> None:
        self.ok = False
        self._shown = False
        try:
            import tkinter as tk
            root = tk.Tk()
            root.title("CalcBook")
            root.withdraw()
            root.overrideredirect(True)  # 无边框，不出现在任务栏
            try:
                root.attributes("-topmost", True)
            except tk.TclError:
                pass
            root.configure(bg="#ffffff", highlightthickness=1,
                           highlightbackground="#cccccc")
            self._label = tk.Label(root, justify="left", anchor="w", bg="#ffffff",
                                   fg="#333333", padx=22, pady=16,
                                   font=("Microsoft YaHei UI", 10))
            self._label.pack()
            self._root = root
            self.ok = True
        except Exception:
            self.ok = False

    def show(self, text: str) -> None:
        if not self.ok:
            return
        try:
            self._label.config(text=text)
            if not self._shown:
                self._root.update_idletasks()
                w, h = self._root.winfo_reqwidth(), self._root.winfo_reqheight()
                x = (self._root.winfo_screenwidth() - w) // 2
                y = (self._root.winfo_screenheight() - h) // 3
                self._root.geometry(f"+{x}+{y}")
                self._root.deiconify()
                self._shown = True
            self._root.update()
        except Exception:
            self.ok = False

    def tick(self) -> None:
        """保持窗口响应（等待子进程/下载循环里周期调用）。"""
        if self.ok:
            try:
                self._root.update()
            except Exception:
                self.ok = False

    def close(self) -> None:
        if self.ok:
            try:
                self._root.destroy()
            except Exception:
                pass
            self.ok = False


_SPLASH: _Splash | None = None


def splash_show(text: str) -> None:
    """显示/更新启动画面（首次调用时创建窗口）。"""
    global _SPLASH
    if _SPLASH is None:
        _SPLASH = _Splash()
        if not _SPLASH.ok:
            log("（启动画面不可用：tkinter 未打包；安装进度只写日志）")
    _SPLASH.show(text)


def splash_tick() -> None:
    if _SPLASH is not None:
        _SPLASH.tick()


def splash_close() -> None:
    global _SPLASH
    if _SPLASH is not None:
        _SPLASH.close()
        _SPLASH = None


def run_logged(cmd: list[str], timeout: float | None = None) -> int:
    """无窗口子进程：输出追加到 calcbook.log，等待期间保持启动画面响应。"""
    path = LOG_PATH or Path(LOG_NAME)
    with open(path, "a", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT,
                                creationflags=CREATE_NO_WINDOW)
        start = time.monotonic()
        while proc.poll() is None:
            splash_tick()
            if timeout is not None and time.monotonic() - start > timeout:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.05)
    return proc.returncode


def probe_env(py: Path) -> tuple[bool, str | None]:
    """校验包内 python/ 环境：calcbook 及核心依赖可导入，返回 (可用, 版本)。"""
    try:
        r = subprocess.run([str(py), "-c", CHECK_CODE], capture_output=True,
                           text=True, timeout=120,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    ver = r.stdout.strip()
    return r.returncode == 0 and bool(ver), ver or None


def missing_template_deps(py: Path, examples: Path) -> list[str] | None:
    """用包内 python 扫模板声明，返回缺的第三方库（import 名）。

    扫描失败（超时/脚本异常）返回 None——与「确实无缺失」区分开，
    由调用方记日志跳过，避免把失败静默当成「依赖齐全」。
    """
    try:
        r = subprocess.run([str(py), "-c", DEPS_CHECK_SCRIPT, str(examples)],
                           capture_output=True, text=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"模板依赖扫描失败（{e}），跳过自动安装。")
        return None
    if r.returncode != 0:
        tail = " | ".join((r.stderr or "").strip().splitlines()[-3:])
        log(f"模板依赖扫描异常（rc={r.returncode}），跳过自动安装：{tail}")
        return None
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def ensure_template_deps(py: Path, examples: Path) -> None:
    """模板声明了但包内没装的库，用包内 pip（国内镜像）自动补装进 python/。"""
    missing = missing_template_deps(py, examples)
    if missing is None:                 # 扫描失败已在内部记日志
        return
    if not missing:
        log("模板依赖齐全，无需额外安装。")
        return
    # 依赖声明是 import 名，会作为 pip 参数：白名单过滤掉选项注入/非法字符
    safe = [m for m in missing if _PKG_NAME.match(m)]
    rejected = [m for m in missing if not _PKG_NAME.match(m)]
    if rejected:
        log(f"忽略不合法的依赖声明：{rejected}")
    if not safe:
        return
    log(f"模板需要额外库：{'、'.join(safe)}，正在自动安装（源：{PIP_INDEX}）…")
    splash_show(f"正在安装模板依赖：{'、'.join(safe)}…\n（详见 {LOG_NAME}）")
    try:
        rc = run_logged([str(py), "-m", "pip", "install", "-i", PIP_INDEX,
                         "--no-input", "--", *safe], timeout=1800)
    except subprocess.TimeoutExpired:
        log("模板依赖安装超时（30 分钟），已中止；不影响启动。")
        return
    if rc != 0:
        log("模板依赖安装失败（不影响启动；运行对应模板时会提示缺少依赖）。")


def main() -> int:
    global LOG_PATH
    base = Path(sys.executable).resolve().parent  # PyInstaller 单文件：exe 所在目录
    LOG_PATH = base / LOG_NAME
    try:  # 窗口程序（无控制台）：全部输出重定向进日志
        sys.stdout = sys.stderr = _Tee(LOG_PATH)
    except OSError:
        pass

    examples = base / "examples"
    if not examples.is_dir():
        return fatal("缺少 examples/ 模板目录，请把离线包完整解压后再运行。")
    py = Path(os.environ.get("CALCBOOK_PYTHON") or base / "python" / "python.exe")
    if not py.is_file():
        return fatal("缺少内置 Python（python/ 目录），请把离线包完整解压后再运行。")

    log(f"自检内置环境：{py}")
    ok, ver = probe_env(py)
    if not ok:
        return fatal("内置 Python 环境不完整或已损坏，请重新解压离线包后再运行"
                     "（详情见 calcbook.log）。")
    log(f"内置环境就绪：calcbook {ver}")

    ensure_template_deps(py, examples)

    splash_close()  # 环境就绪：收起启动画面，打开主窗口
    log(f"启动服务（桌面窗口模式），模板目录：{examples}")
    log("服务地址：http://127.0.0.1:8317（如被占用会自动递加，界面顶栏显示实际地址）")
    rc = run_logged([str(py), "-m", "calcbook.cli", "serve",
                     "--ui", "webview", "--templates", str(examples)])
    if rc != 0:     # 窗口程序：serve 异常退出时用户只看到窗口消失——弹窗提示原因
        return fatal(f"服务异常退出（代码 {rc}），详情见 {LOG_NAME}。")
    return rc


def _crash_guard() -> int:
    """兜底：main 未捕获的异常也要在窗口程序下可见（写日志 + 弹窗）。"""
    import traceback
    tb = traceback.format_exc()
    try:
        print(tb, flush=True)           # 已重定向进日志
    except Exception:
        pass
    last = tb.strip().splitlines()[-1] if tb.strip() else "未知错误"
    _msgbox(f"CalcBook 启动失败：{last}\n\n详情见 {LOG_NAME}（与 CalcBook.exe 同目录）。",
            "CalcBook 启动失败", 0x10)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        sys.exit(_crash_guard())
