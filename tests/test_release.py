"""发布脚本与 Python 包一致性：版本号同步、便携包组装真的带上模板资源与手册。"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

import probatrix

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = ROOT / "tools" / "build_release.py"


def test_pyproject_version_matches_package() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'version = "([^"]+)"', text)
    assert m, "pyproject.toml 里找不到 version"
    assert m.group(1) == probatrix.__version__


# ----------------------------------------------------------------------
# assemble()：用临时 ROOT 与假运行时验证真正复制了什么
# ----------------------------------------------------------------------
def _load_build_script():
    """按路径载入构建脚本（tools/ 不是包，也不该为测试塞进 sys.path）。"""
    spec = importlib.util.spec_from_file_location("build_release_under_test", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """造一棵最小仓库树：examples（两种布局 + 资源 + 缓存）、docs/manual、假 app。"""
    root = tmp_path / "repo"
    examples = root / "examples"
    examples.mkdir(parents=True)
    # 单文件模板 + 根目录数据模块 + 根目录资源
    (examples / "gl.py").write_text("# 单文件模板\n", encoding="utf-8")
    (examples / "Hsteel.py").write_text("TABLE = {}\n", encoding="utf-8")
    (examples / "gl_计算书预览.md").write_text("预览\n", encoding="utf-8")
    (examples / "assets").mkdir()
    (examples / "assets" / "logo.png").write_bytes(b"logo")
    # 文件夹模板 + 配套资源
    report = examples / "steel_report"
    (report / "images").mkdir(parents=True)
    (report / "data").mkdir()
    (report / "template.py").write_text("# 文件夹模板\n", encoding="utf-8")
    (report / "report.md").write_text("报告片段\n", encoding="utf-8")
    (report / "data" / "table.csv").write_text("a,b\n", encoding="utf-8")
    (report / "images" / "section.png").write_bytes(b"png-bytes")
    # 缓存与版本库：不进包
    (examples / "__pycache__").mkdir()
    (examples / "__pycache__" / "gl.cpython-312.pyc").write_bytes(b"pyc")
    (report / "__pycache__").mkdir()
    (report / "__pycache__" / "template.cpython-312.pyc").write_bytes(b"pyc")
    (report / "stale.pyc").write_bytes(b"pyc")
    (examples / ".git").mkdir()
    (examples / ".git" / "config").write_text("vcs\n", encoding="utf-8")
    # 手册（按阅读顺序编号）
    manual = root / "docs" / "manual"
    (manual / "images").mkdir(parents=True)
    for name in ("01-使用说明.md", "02-模板开发指南.md", "03-模板快速开始.md"):
        (manual / name).write_text(f"# {name}\n", encoding="utf-8")
    (manual / "images" / "shot.png").write_bytes(b"shot")
    # 已装好的前端站点 + 桌面程序
    app = tmp_path / "app"
    site = app / "python" / "Lib" / "site-packages" / "probatrix"
    (site / "web").mkdir(parents=True)
    (site / "vendor" / "katex").mkdir(parents=True)
    (site / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
    (site / "vendor" / "katex" / "katex.min.css").write_text("css", encoding="utf-8")
    exe = tmp_path / "Probatrix.exe"
    exe.write_bytes(b"MZ")

    module = _load_build_script()
    monkeypatch.setattr(module, "ROOT", root)
    return module, root, app, exe


def _files(base: Path) -> set[str]:
    return {p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file()}


def test_assemble_copies_examples_with_resources(release) -> None:
    """examples 整树进包：根目录数据模块/资源、文件夹模板的 images/data/md 都不漏。"""
    module, root, app, exe = release
    module.assemble(app, exe, "0.1.0")

    copied = _files(app / "examples")
    assert copied == {p for p in _files(root / "examples")
                      if "__pycache__" not in p.split("/")
                      and not p.endswith(".pyc")
                      and not p.startswith(".git/")}
    assert (app / "examples" / "steel_report" / "images" / "section.png").read_bytes() == b"png-bytes"
    assert (app / "examples" / "steel_report" / "report.md").read_text(encoding="utf-8") == "报告片段\n"
    assert (app / "examples" / "Hsteel.py").is_file()
    assert (app / "Probatrix.exe").read_bytes() == b"MZ"


def test_assemble_skips_caches_and_vcs(release) -> None:
    module, _root, app, exe = release
    module.assemble(app, exe, "0.1.0")
    examples = app / "examples"
    assert not list(examples.rglob("__pycache__"))
    assert not list(examples.rglob("*.pyc"))
    assert not (examples / ".git").exists()


def test_assemble_copies_manual_and_points_notes_at_numbered_docs(release) -> None:
    module, _root, app, exe = release
    module.assemble(app, exe, "0.1.0")

    manual = app / "docs" / "manual"
    assert (manual / "01-使用说明.md").is_file()
    assert (manual / "02-模板开发指南.md").is_file()
    assert (manual / "images" / "shot.png").is_file()

    notes = (app / "使用说明.txt").read_text(encoding="utf-8")
    assert "Probatrix 0.1.0" in notes
    assert "docs/manual/01-使用说明.md" in notes
    assert "docs/manual/02-模板开发指南.md" in notes
    assert "examples/我的模板.py" in notes            # 单文件放法
    assert "examples/我的模板/template.py" in notes    # 文件夹放法
    assert "from .materials import" in notes          # 文件夹私有模块怎么写
    assert "python\\python.exe -m pip install" in notes


def test_assemble_refuses_missing_numbered_manual(release) -> None:
    """使用说明.txt 指向的编号手册必须存在：缺了就在构建时炸，而不是发出死链。"""
    module, root, app, exe = release
    (root / "docs" / "manual" / "01-使用说明.md").unlink()
    with pytest.raises(SystemExit, match="01-使用说明"):
        module.assemble(app, exe, "0.1.0")
