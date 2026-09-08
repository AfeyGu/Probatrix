"""CalcBook 启动器（离线分发版，被 PyInstaller 打包为 launcher.exe）。

约定：launcher.exe 与 calcbook-*.whl、examples/ 放在同一目录。

架构：calcbook 及其依赖全部安装在包目录内的 venv/ 虚拟环境中
（Python 标准库 venv 创建，位于解压目录内，不碰 site-packages）——
删掉整个解压目录即完全卸载。

首次运行（需联网）：找 Python（>=3.11，缺则自动从华为云镜像下载静默安装）
→ 创建/校验 venv/（calcbook 缺失或版本不符 → 重装 wheel，默认阿里云源）
→ 用 venv 的 python 启动桌面窗口服务。

环境变量（覆盖默认行为，测试/排障用）：
  CALCBOOK_PYTHON      指定 python 可执行文件，绕过自动探测
  CALCBOOK_PIP_INDEX   指定 pip 镜像源，默认阿里云
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import webbrowser
from pathlib import Path

EXPECTED_VERSION = "0.1.0a10"
MIN_VERSION = (3, 11)
PIP_INDEX = os.environ.get(
    "CALCBOOK_PIP_INDEX", "https://mirrors.aliyun.com/pypi/simple")
PY_MIRROR = "https://mirrors.huaweicloud.com/python/"
PY_FALLBACK_URL = "https://www.python.org/downloads/"
# 官方安装器 InstallAllUsers=0 时的默认安装目录
LOCAL_PYTHON_DIR = (Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
                    / "Programs" / "Python")

# 校验 lib/ 环境：calcbook 版本 + 运行时依赖齐全
CHECK_CODE = (
    "import calcbook, pydantic, fastapi, uvicorn, webview\n"
    "print(calcbook.__version__)\n")

# 模板依赖扫描脚本：AST 解析各模板的 __calcbook_requires__ 声明（不导入模板模块，
# 避免模块级副作用/自身缺库），用 find_spec 检查是否可用，输出缺失的 import 名。
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
    deps += collect(p)
missing = [d for d in dict.fromkeys(deps) if importlib.util.find_spec(d) is None]
if missing:
    print("\n".join(missing))
'''


def log(msg: str) -> None:
    print(f"[calcbook 启动器] {msg}", flush=True)


def _msgbox(text: str, title: str = "CalcBook", style: int = 0x40) -> None:
    """弹窗提示（错误/重要提示在终端之外再弹一次）。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, style)
    except Exception:
        print(text, flush=True)


def fatal(msg: str) -> int:
    print(f"\n{msg}\n", flush=True)
    _msgbox(f"{msg}\n\n（点击确定退出）", "CalcBook 启动失败", 0x10)  # MB_ICONERROR
    return 1


class _Tee:
    """终端 + 日志文件双写：日志写入 launcher.log 留底（黑窗隐藏后仍可排障）。"""

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


def hide_console() -> None:
    """隐藏启动器黑窗（服务就绪后调用；窗口隐藏时任务栏按钮一并消失）。
    日志仍写入包目录 launcher.log；界面顶栏显示实际服务地址。"""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


def _parse_version(out: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def pick_python() -> str | None:
    """返回可用的 python 可执行文件路径（>=3.11），找不到返回 None。"""
    candidates: list[str] = []
    override = os.environ.get("CALCBOOK_PYTHON")
    if override:
        candidates.append(override)
    py = shutil.which("py")
    if py:
        try:
            out = subprocess.run([py, "-0p"], capture_output=True, text=True,
                                 timeout=10).stdout
            for line in out.splitlines():
                m = re.match(r"\s*-V:\d+(?:\.\d+)*\s*\*?\s*(.+?)\s*$", line)
                if m:
                    candidates.append(m.group(1))
        except (OSError, subprocess.TimeoutExpired):
            pass
    if LOCAL_PYTHON_DIR.is_dir():  # 刚安装/未注册 launcher 的兜底
        candidates += sorted((str(p) for p in LOCAL_PYTHON_DIR.glob("Python*/python.exe")),
                             reverse=True)
    for name in ("python", "python3"):
        p = shutil.which(name)
        if p:
            candidates.append(p)

    seen: list[str] = []
    for c in candidates:
        if c in seen:
            continue
        seen.append(c)
        try:
            out = subprocess.run([c, "--version"], capture_output=True, text=True,
                                 timeout=10).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            continue
        ver = _parse_version(out)
        if ver and ver >= MIN_VERSION:
            return c
    return None


def latest_release_with_exe() -> str:
    """从华为云镜像从最新版本向下找第一个带 Windows 安装包的版本（目录可能刚建、exe 未同步）。"""
    with urllib.request.urlopen(PY_MIRROR, timeout=20) as r:
        html = r.read().decode("utf-8", "replace")
    vers = sorted((tuple(int(x) for x in v.split("."))
                   for v in re.findall(r'href="(\d+\.\d+\.\d+)/"', html)),
                  reverse=True)
    if not vers:
        raise OSError("镜像目录解析失败")
    for v in vers[:12]:  # 最多往下试 12 个版本
        tag = ".".join(str(x) for x in v)
        req = urllib.request.Request(
            f"{PY_MIRROR}{tag}/python-{tag}-amd64.exe",
            method="HEAD", headers={"User-Agent": "calcbook-launcher"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return tag
        except OSError:
            continue
    raise OSError("镜像上没有可用的 Windows 安装包")


def download(url: str, dest: Path, label: str = "") -> None:
    """带进度的文件下载。"""
    log(f"开始下载 {label or url}")
    req = urllib.request.Request(url, headers={"User-Agent": "calcbook-launcher"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        done, last = 0, 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            marks = done // (1 << 22)  # 每 4MB 一个点
            if marks > last:
                print("." * (marks - last), end="", flush=True)
                last = marks
    size_mb = dest.stat().st_size / 1e6
    print(f"\n下载完成（{size_mb:.1f} MB）", flush=True)


def install_python() -> str | None:
    """自动下载并静默安装最新版 Python（用户级，无需管理员）。返回安装后的 exe 路径。"""
    try:
        ver = latest_release_with_exe()
    except OSError as e:
        webbrowser.open(PY_FALLBACK_URL)
        print(f"（镜像不可达：{e}）", flush=True)
        return None
    url = f"{PY_MIRROR}{ver}/python-{ver}-amd64.exe"
    dest = Path(tempfile.gettempdir()) / f"calcbook_python_{ver}.exe"
    try:
        download(url, dest, f"Python {ver} 安装包（{url}）")
        log("正在静默安装 Python（约 1–2 分钟，无安装窗口）…")
        r = subprocess.run(
            [str(dest), "/quiet", "InstallAllUsers=0", "PrependPath=1",
             "Include_pip=1", "Include_launcher=1", "Include_test=0"],
            timeout=600)
        if r.returncode != 0:
            raise OSError(f"安装器退出码 {r.returncode}")
    except (OSError, subprocess.TimeoutExpired) as e:
        webbrowser.open(PY_FALLBACK_URL)
        print(f"（自动安装失败：{e}）", flush=True)
        return None
    finally:
        dest.unlink(missing_ok=True)
    # 已装 python 的固定路径（本进程环境不刷新 PATH/launcher，直接构造）
    minor = ver.split(".")[1]
    candidate = LOCAL_PYTHON_DIR / f"Python{minor}" / "python.exe"
    if candidate.is_file():
        log(f"Python 安装完成：{candidate}")
        return str(candidate)
    return None


def venv_python(base: Path) -> Path:
    return base / "venv" / "Scripts" / "python.exe"


def check_venv(vpy: Path) -> tuple[bool, str | None]:
    """校验 venv 内 calcbook 版本与依赖，返回 (可用, 版本)。"""
    if not vpy.is_file():
        return False, None
    try:
        r = subprocess.run([str(vpy), "-c", CHECK_CODE], capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False, None
    ver = r.stdout.strip()
    return r.returncode == 0 and bool(ver), ver or None


def ensure_venv(base_py: str, base: Path, wheel: Path) -> bool:
    """确保包目录内 venv/ 可用：缺失则创建，版本不符则重装 wheel。"""
    vpy = venv_python(base)
    ok, installed = check_venv(vpy)
    if ok and installed == EXPECTED_VERSION:
        log("calcbook 虚拟环境已就绪（包目录内 venv/）。")
        return True
    if installed:
        log(f"venv 内 calcbook 是 {installed}，将更新为 {EXPECTED_VERSION}…")
    else:
        if vpy.is_file():
            log("虚拟环境损坏，重建…")
            shutil.rmtree(base / "venv", ignore_errors=True)
        log("创建虚拟环境（包目录内 venv/）…")
        r = subprocess.run([base_py, "-m", "venv", str(base / "venv")])
        if r.returncode != 0:
            return fatal("虚拟环境创建失败。") == 0
        log(f"安装 calcbook {EXPECTED_VERSION} 及依赖（联网，源：{PIP_INDEX}）…")
    r = subprocess.run([str(vpy), "-m", "pip", "install", "--upgrade",
                        "-i", PIP_INDEX, str(wheel)])
    if r.returncode != 0:
        return fatal("安装失败（请检查网络），上方是错误详情。") == 0
    return True


def missing_template_deps(vpy: Path, examples: Path) -> list[str]:
    """用 venv 的 python 扫模板声明，返回缺的第三方库（import 名）。"""
    try:
        r = subprocess.run([str(vpy), "-c", DEPS_CHECK_SCRIPT, str(examples)],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def ensure_template_deps(vpy: Path, examples: Path) -> None:
    """模板声明了但 venv 里没装的库，用同一镜像自动装进包内 venv。"""
    missing = missing_template_deps(vpy, examples)
    if not missing:
        log("模板依赖齐全，无需额外安装。")
        return
    log(f"模板需要额外库：{'、'.join(missing)}，正在自动安装（源：{PIP_INDEX}）…")
    r = subprocess.run([str(vpy), "-m", "pip", "install", "-i", PIP_INDEX, *missing])
    if r.returncode != 0:
        log("模板依赖安装失败（不影响启动；运行对应模板时会提示缺少依赖）。")


def _wheel_key(p: Path) -> tuple:
    """wheel 文件名版本排序键：calcbook-0.1.0a10 > calcbook-0.1.0a9（字符串序会错）"""
    nums = re.findall(r"\d+", p.name)
    return tuple(int(x) for x in nums) if len(nums) >= 4 else (0,)


def main() -> int:
    base = Path(sys.executable).resolve().parent  # PyInstaller 单文件：exe 所在目录
    wheels = sorted(base.glob("calcbook-*.whl"), key=_wheel_key)
    if not wheels:
        return fatal("缺少 calcbook-*.whl，请把离线包完整解压后再运行。")
    wheel = wheels[-1]
    examples = base / "examples"
    if not examples.is_dir():
        return fatal("缺少 examples/ 模板目录，请把离线包完整解压后再运行。")

    log_file = base / "launcher.log"
    try:  # 终端可见 + 日志留底
        sys.stdout = sys.stderr = _Tee(log_file)
    except OSError:
        pass

    log("正在查找本机 Python…")
    py = pick_python()
    if py is None:
        _msgbox("本机未安装 Python。\n\n点击确定后，将自动从国内镜像下载并安装"
                "（约 25 MB，需几分钟），完成后自动继续启动。")
        log(f"未找到 Python {MIN_VERSION[0]}.{MIN_VERSION[1]}+，"
            "正在从华为云镜像下载并安装最新版…")
        py = install_python()
    if py is None:
        return fatal("Python 安装未完成。已为你打开 python.org 官网，"
                     "请手动安装 Python 3.11+（勾选『Add python.exe to PATH』）后再运行。")

    log(f"使用 Python：{py}")
    if not ensure_venv(py, base, wheel):
        return 1
    ensure_template_deps(venv_python(base), examples)

    hide_console()  # 服务就绪：隐藏黑窗（日志同步写 launcher.log，界面顶栏显示地址）
    log(f"启动服务（桌面窗口模式），模板目录：{examples}")
    log(f"服务地址：http://127.0.0.1:8317（如被占用会自动递加，界面顶栏显示实际地址）")
    return subprocess.run([str(venv_python(base)), "-m", "calcbook.cli", "serve",
                           "--ui", "webview", "--templates", str(examples)]).returncode


if __name__ == "__main__":
    sys.exit(main())