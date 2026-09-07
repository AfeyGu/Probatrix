"""构建 CalcBook 离线发布包（预览版）。

产物：release/calcbook-<版本>.zip
  ├─ launcher.exe            （PyInstaller 单文件启动器，只含 stdlib）
  ├─ calcbook-<版本>.whl     （Python 包本体，launcher 首次运行自动安装）
  └─ examples/               （模板）
                （gl.py、stair.py）

依赖：pip install build pyinstaller
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
APP = RELEASE / "_app"  # zip 的组装目录


def version() -> str:
    m = re.search(r'version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("pyproject.toml 里找不到 version")
    return m.group(1)


def build_wheel() -> Path:
    print("==> 构建 wheel")
    subprocess.run([sys.executable, "-m", "build", "--wheel"], cwd=ROOT, check=True)
    wheels = sorted((ROOT / "dist").glob("calcbook-*.whl"))
    if not wheels:
        raise SystemExit("wheel 构建失败")
    return wheels[-1]


def build_launcher() -> Path:
    print("==> 打包 launcher.exe（PyInstaller 单文件）")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--onefile", "--console", "--clean",
         "--name", "launcher", "--distpath", str(RELEASE / "_build" / "dist"),
         "--workpath", str(RELEASE / "_build" / "work"), "--specpath", str(RELEASE),
         str(ROOT / "tools" / "launcher.py")],
        check=True)
    return RELEASE / "_build" / "dist" / "launcher.exe"


def assemble(exe: Path, whl: Path, tag: str) -> Path:
    print("==> 组装发布目录")
    if APP.exists():
        shutil.rmtree(APP)
    (APP / "examples").mkdir(parents=True)
    shutil.copy2(exe, APP / exe.name)
    shutil.copy2(whl, APP / whl.name)
    for tpl in sorted((ROOT / "examples").glob("*.py")):
        shutil.copy2(tpl, APP / "examples" / tpl.name)
    (APP / "使用说明.txt").write_text(
        f"""CalcBook {tag} 预览版（离线包）

使用：
  1. 双击 launcher.exe。本机需已安装 Python 3.11+；
     没有的话会引导你去 python.org 下载安装。
  2. 首次运行会联网安装 calcbook 及其依赖库（仅首次），
     之后每次双击直接启动，自动打开浏览器。
  3. 进阶：命令行运行 calcbook serve --ui webview 可改用桌面窗口
     （需先 python -m pip install pywebview）。

文件说明：
  calcbook-{tag}-py3-none-any.whl  —— 程序本体，launcher 自动安装
  venv/（首次运行自动生成）      —— 虚拟环境：calcbook 及依赖都装在
                                     包目录内，不写入系统 Python，
                                     删掉整个文件夹即完全卸载
  examples/                        —— 计算书模板（gl 梁、stair 楼梯）
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
    print(f"==> CalcBook 离线发布包 {tag}")
    whl = build_wheel()
    launcher = build_launcher()
    zip_path = assemble(launcher, whl, tag)
    shutil.rmtree(APP)
    shutil.rmtree(RELEASE / "_build")
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"\n完成：{zip_path}（{size_mb:.1f} MB）")


if __name__ == "__main__":
    main()