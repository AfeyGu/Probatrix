"""构建 Windows x64 便携版。解压后从 Probatrix.exe 启动，目标机需要 WebView2。

在 Windows 上使用 Python 3.11+、build 与 Rust MSVC 工具链构建。
产物含 Tauri 窗口、嵌入式 Python、示例模板、模板文档和使用说明。
构建时联网准备运行时与依赖，使用时可离线运行内置示例。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
TAURI = ROOT / "src-tauri"
WINDOWS_TARGET = "x86_64-pc-windows-msvc"
PY_VERSION = "3.12.10"
PY_OFFICIAL = "https://www.python.org/ftp/python"
PREINSTALL = ["numpy", "scipy", "pandas", "matplotlib", "openpyxl"]


def version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        ver = tomllib.load(f).get("project", {}).get("version")
    if not ver:
        raise SystemExit("pyproject.toml 的 [project] 段里找不到 version")
    return ver


def build_wheel(output: Path) -> Path:
    print("==> 构建 wheel")
    # 从源码归档构建 wheel，隔离工作树 build/ 中的旧包文件。
    subprocess.run([sys.executable, "-m", "build", "--outdir", str(output)],
                   cwd=ROOT, check=True)
    wheels = list(output.glob("probatrix-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"应生成一个 Probatrix wheel，找到 {len(wheels)} 个")
    return wheels[0]


def build_desktop() -> Path:
    print("==> 构建 Tauri 桌面程序")
    target_dir = Path(os.environ.get("CARGO_TARGET_DIR") or TAURI / "target").resolve()
    subprocess.run(["cargo", "build", "--release", "--locked",
                    "--manifest-path", str(TAURI / "Cargo.toml"),
                    "--target", WINDOWS_TARGET, "--target-dir", str(target_dir)],
                   cwd=ROOT, check=True)
    return target_dir / WINDOWS_TARGET / "release" / "Probatrix.exe"


def fetch_embed_python(dest: Path, download: Path) -> None:
    url = f"{PY_OFFICIAL}/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
    print(f"    下载 {url}")
    with urllib.request.urlopen(url, timeout=120) as source, download.open("wb") as target:
        shutil.copyfileobj(source, target)
    shutil.unpack_archive(download, dest)
    if not (dest / "python.exe").is_file():
        raise SystemExit(f"解压结果异常：{dest} 下没有 python.exe")


def setup_python(python_dir: Path) -> Path:
    """启用 site、装 pip：把嵌入版变成可 pip 管理的完整运行环境。返回 python.exe。"""
    minor = PY_VERSION.rsplit(".", 1)[0].replace(".", "")  # "3.12.10" -> "312"
    pth = python_dir / f"python{minor}._pth"
    text = pth.read_text(encoding="utf-8")
    if "#import site" not in text:
        raise SystemExit(f"{pth.name} 内容异常：找不到 #import site")
    pth.write_text(text.replace("#import site", "import site"), encoding="utf-8")

    exe = python_dir / "python.exe"
    # pip 是纯 Python：用构建机的 pip --target 直装进包内，不依赖 get-pip.py
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-warn-script-location",
                    "--target", str(python_dir / "Lib" / "site-packages"), "pip"],
                   check=True)
    r = subprocess.run([str(exe), "-m", "pip", "--version"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise SystemExit(f"包内 pip 不可用：{r.stderr}")
    return exe


def preinstall(python_exe: Path, whl: Path) -> None:
    """用预构建 wheel 安装 Probatrix 及常用模板库。"""
    subprocess.run([str(python_exe), "-m", "pip", "install", "--only-binary=:all:",
                    "--no-warn-script-location", "--progress-bar", "off",
                    str(whl), *PREINSTALL], check=True)


def verify_runtime(python_exe: Path) -> None:
    code = ("import probatrix.desktop, numpy, scipy, pandas, matplotlib, openpyxl\n"
            "print('Probatrix ' + probatrix.__version__)")
    subprocess.run([str(python_exe), "-c", code], check=True,
                   timeout=60, cwd=python_exe.parent)
    subprocess.run([str(python_exe), "-m", "pip", "check"], check=True, timeout=60)


def trim_site_packages(python_dir: Path) -> None:
    """剔除各库自带的 tests/ 目录（不参与运行，zip 体积可减约三分之一）。"""
    site_dir = python_dir / "Lib" / "site-packages"
    n = 0
    for d in list(site_dir.rglob("tests")):
        if d.is_dir():
            shutil.rmtree(d)
            n += 1
    print(f"    已剔除 {n} 个 tests 目录")


def assemble(app: Path, exe: Path, tag: str) -> None:
    print("==> 组装便携目录")
    site = app / "python" / "Lib" / "site-packages" / "probatrix"
    for rel in ("web/index.html", "vendor/katex/katex.min.css"):
        if not (site / rel).is_file():
            raise SystemExit(f"包内缺少 {rel}。请先在 web/ 下执行 npm run build。")
    (app / "examples").mkdir()
    shutil.copy2(exe, app / "Probatrix.exe")
    for tpl in sorted((ROOT / "examples").glob("*.py")):
        shutil.copy2(tpl, app / "examples" / tpl.name)
    shutil.copytree(ROOT / "docs", app / "docs")
    (app / "使用说明.txt").write_text(
        f"""Probatrix {tag} · Windows x64 便携版

在已安装 Microsoft Edge WebView2 Runtime 的 Windows 10/11 x64 上，完整解压后双击
Probatrix.exe。移动时请保留整个目录。Python {PY_VERSION}、计算界面、常用计算库和
示例模板均随包提供，运行内置示例无需联网。导出时可在菜单勾选「导出离线版」。

将自定义模板和配套数据文件放进 examples/。模板需要额外的库时，退出 Probatrix，
在解压目录用包内 Python 安装（将「包名」换成模板文档里的 PyPI 包名）：
  .\\python\\python.exe -m pip install 包名

工程请保存为 .pbproj 文件，重启后可重新打开。日志位于
%LOCALAPPDATA%\\io.github.afeygu.probatrix\\logs\\probatrix-desktop.log。
模板开发指南见 docs/模板开发指南.md。
""", encoding="utf-8")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("请在 Windows 上构建便携包。")
    tag = version()
    print(f"==> Probatrix Windows x64 便携版 {tag}（内置 Python {PY_VERSION}）")
    RELEASE.mkdir(exist_ok=True)
    zip_path = RELEASE / f"probatrix-{tag}-windows-x64-portable.zip"
    with TemporaryDirectory(prefix="probatrix-build-", dir=RELEASE) as tmp:
        work = Path(tmp)
        exe = build_desktop()
        whl = build_wheel(work / "wheel")
        app = work / "app"
        pydir = app / "python"
        print(f"==> 准备内置 Python {PY_VERSION}")
        fetch_embed_python(pydir, work / "python-embed.zip")
        pyexe = setup_python(pydir)
        print("==> 预装 Probatrix 及常用模板库")
        preinstall(pyexe, whl)
        trim_site_packages(pydir)
        verify_runtime(pyexe)
        assemble(app, exe, tag)
        print("==> 压缩 zip")
        archive = work / zip_path.name
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(app.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(app).as_posix())
        archive.replace(zip_path)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n完成：{zip_path}（{size_mb:.1f} MiB）")


if __name__ == "__main__":
    main()