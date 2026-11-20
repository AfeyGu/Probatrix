"""构建 CalcBook 离线发布包（全离线，内置 Python）。

产物：release/calcbook-<版本>.zip
  ├─ CalcBook.exe            （PyInstaller 单文件启动器，窗口程序，只含 stdlib）
  ├─ python/                 （嵌入版 Python，构建时预装全部依赖，含 pip）
  ├─ examples/               （模板，gl.py、stair.py、canopy.py）
  └─ docs/                   （模板开发指南）

用户侧解压双击 CalcBook.exe 即用：不依赖系统 Python、零联网、
不写注册表/环境变量，删掉解压目录即完全卸载。calcbook 的 wheel
只在构建时装进包内 python/，是构建中间产物，不再随 zip 分发。

预装清单（B 档）：calcbook wheel + numpy scipy pandas matplotlib
openpyxl（pywebview/pydantic/fastapi/uvicorn 由 wheel 依赖自动带入）。

依赖：pip install build pyinstaller pillow（pillow 仅 tools/make_icon.py 用）
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
APP = RELEASE / "_app"  # zip 的组装目录

PY_VERSION = "3.12.10"  # 嵌入版 Python：3.12 系列最后带 embed zip 的 bugfix 版
PY_MIRROR = "https://mirrors.huaweicloud.com/python"
PY_OFFICIAL = "https://www.python.org/ftp/python"
PIP_INDEX = "https://mirrors.aliyun.com/pypi/simple"
PREINSTALL = ["numpy", "scipy", "pandas", "matplotlib", "openpyxl"]


def version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        ver = tomllib.load(f).get("project", {}).get("version")
    if not ver:
        raise SystemExit("pyproject.toml 的 [project] 段里找不到 version")
    return ver


def build_wheel() -> Path:
    print("==> 构建 wheel")
    shutil.rmtree(ROOT / "dist", ignore_errors=True)  # 清残留 wheel，避免版本混淆
    r = subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"wheel 构建失败（rc={r.returncode}，见上方日志）")

    def key(p: Path) -> tuple:  # 版本序：a10 > a9（字符串序会错）
        nums = re.findall(r"\d+", p.name)
        return tuple(int(x) for x in nums) if len(nums) >= 4 else (0,)

    wheels = sorted((ROOT / "dist").glob("calcbook-*.whl"), key=key)
    if not wheels:
        raise SystemExit("wheel 构建失败（dist/ 下没有 calcbook-*.whl）")
    return wheels[-1]


def build_launcher() -> Path:
    print("==> 打包 CalcBook.exe（PyInstaller 单文件窗口程序）")
    r = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--clean",
         "--name", "CalcBook", "--icon", str(ROOT / "assets" / "icon.ico"),
         "--distpath", str(RELEASE / "_build" / "dist"),
         "--workpath", str(RELEASE / "_build" / "work"), "--specpath", str(RELEASE),
         str(ROOT / "tools" / "launcher.py")])
    if r.returncode != 0:
        raise SystemExit(f"PyInstaller 打包失败（rc={r.returncode}，见上方日志）")
    return RELEASE / "_build" / "dist" / "CalcBook.exe"


def fetch_embed_python(dest: Path) -> None:
    """下载嵌入版 Python 并解压到 dest（华为云镜像优先，官方源回退）。"""
    tag = PY_VERSION
    urls = [f"{PY_MIRROR}/{tag}/python-{tag}-embed-amd64.zip",
            f"{PY_OFFICIAL}/{tag}/python-{tag}-embed-amd64.zip"]
    zip_path = RELEASE / "_build" / "python-embed.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for url in urls:
        try:
            print(f"    下载 {url}")
            with urllib.request.urlopen(url, timeout=120) as r, open(zip_path, "wb") as f:
                shutil.copyfileobj(r, f)
            print(f"    完成（{zip_path.stat().st_size / 1e6:.1f} MB）")
            break
        except OSError as e:
            last_err = e
    else:
        raise SystemExit(f"嵌入版 Python 下载失败：{last_err}")
    shutil.unpack_archive(zip_path, dest)  # 官方 zip 内无中文路径，直接解
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
    """预装 calcbook wheel + B 档数学库。

    分两步：数学库严格仅二进制 wheel（--only-binary，杜绝源码编译）；
    calcbook 本体放开——其依赖全有 wheel，唯一例外 proxy-tools 只有
    纯 Python sdist（无 C 扩展，pip 构建 wheel 无需编译器）。
    """
    subprocess.run([str(python_exe), "-m", "pip", "install",
                    "--only-binary=:all:", "--no-warn-script-location",
                    "--progress-bar", "off", "-i", PIP_INDEX,
                    *PREINSTALL], check=True)
    subprocess.run([str(python_exe), "-m", "pip", "install",
                    "--prefer-binary", "--no-warn-script-location",
                    "--progress-bar", "off", "-i", PIP_INDEX,
                    str(whl)], check=True)
    # 构建自检：包内核心链路 import 全通
    code = ("import calcbook, pydantic, fastapi, uvicorn, webview, "
            "numpy, scipy, pandas, matplotlib, openpyxl\n"
            "print(calcbook.__version__)")
    r = subprocess.run([str(python_exe), "-c", code], capture_output=True,
                       text=True, timeout=300, cwd=str(python_exe.parent))
    if r.returncode != 0:
        raise SystemExit(f"包内环境自检失败：\n{r.stdout}\n{r.stderr}")
    print(f"    自检通过：calcbook {r.stdout.strip()}")


def trim_site_packages(python_dir: Path) -> None:
    """剔除各库自带的 tests/ 目录（不参与运行，zip 体积可减约三分之一）。"""
    site_dir = python_dir / "Lib" / "site-packages"
    n = 0
    for d in list(site_dir.rglob("tests")):
        if d.is_dir():
            shutil.rmtree(d)
            n += 1
    print(f"    已剔除 {n} 个 tests 目录")


def assemble(exe: Path, tag: str) -> Path:
    print("==> 组装发布目录")
    # 防呆：前端产物（构建时随 wheel 进 site-packages）缺了会导致离线包
    # 打开只有 JSON 页、导出 500——在打包前就报出来
    site = APP / "python" / "Lib" / "site-packages" / "calcbook"
    for rel in ("web/index.html", "vendor/katex/katex.min.css"):
        if not (site / rel).is_file():
            raise SystemExit(f"包内缺少 {rel}——前端产物未随 wheel 打入，"
                             f"请先 cd web && npm run build 再构建发布包")
    (APP / "examples").mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, APP / exe.name)
    for tpl in sorted((ROOT / "examples").glob("*.py")):
        shutil.copy2(tpl, APP / "examples" / tpl.name)
    shutil.copytree(ROOT / "docs", APP / "docs")  # 模板开发指南
    (APP / "使用说明.txt").write_text(
        f"""CalcBook {tag}（离线完整版）

使用：
  1. 解压整个压缩包后，双击 CalcBook.exe。
  2. Python 与全部依赖（含 numpy / scipy / pandas / matplotlib / openpyxl 等）
     已内置在 python/ 目录，开箱即用，全程无需联网，不写注册表、
     不改系统环境；删掉整个解压文件夹即完全卸载。
  3. 模板声明的额外第三方库（__calcbook_requires__）缺失时，启动器会用
     内置 pip 从国内镜像自动装进 python/（仅此场景需要联网）。
  4. 启动全程没有命令行黑窗；完整日志写入 calcbook.log（排障用）；
     实际服务地址显示在窗口顶栏右侧（端口被占用时会自动递加）。

文件说明：
  CalcBook.exe                 —— 启动器
  python/                      —— 内置 Python {PY_VERSION} 及全部依赖（已预装，勿改动）
  examples/                    —— 计算书示例模板（gl 梁、stair 楼梯、canopy 雨篷）
  docs/模板开发指南.md          —— 模板开发指南（学习写自己的模板）
""", encoding="utf-8")
    print("==> 压缩 zip")
    import zipfile
    zip_path = RELEASE / f"calcbook-{tag}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(APP.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(APP).as_posix())
    return zip_path


def main() -> None:
    tag = version()
    print(f"==> CalcBook 离线发布包 {tag}（内置 Python {PY_VERSION}）")
    whl = build_wheel()
    exe = build_launcher()
    if APP.exists():
        shutil.rmtree(APP)
    pydir = APP / "python"
    print(f"==> 准备内置 Python {PY_VERSION}")
    fetch_embed_python(pydir)
    pyexe = setup_python(pydir)
    print("==> 预装 calcbook 及数学库（B 档）")
    preinstall(pyexe, whl)
    print("==> 精简 site-packages")
    trim_site_packages(pydir)
    zip_path = assemble(exe, tag)
    shutil.rmtree(APP)
    shutil.rmtree(RELEASE / "_build")
    (RELEASE / "CalcBook.spec").unlink(missing_ok=True)  # PyInstaller --specpath 残留
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n完成：{zip_path}（{size_mb:.1f} MB）")


if __name__ == "__main__":
    main()