"""FastAPI API 层测试：模板列表/schema、单项与批量计算、工程读写、hash 校验、HTML 导出。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from calcbook.server import create_app

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8",
    )
    return TestClient(create_app(tmp_path), raise_server_exceptions=False)


# ----------------------------------------------------------------------
# 模板
# ----------------------------------------------------------------------
def test_list_templates(client: TestClient) -> None:
    r = client.get("/api/templates")
    assert r.status_code == 200
    data = r.json()
    assert data["templates"][0]["template_id"] == "gl.calc"
    assert data["templates"][0]["name"] == "钢梁强度验算"
    assert data["errors"] == []


def test_template_schema(client: TestClient) -> None:
    r = client.get("/api/templates/gl.calc/schema")
    assert r.status_code == 200
    params = r.json()["params"]
    names = [p["name"] for p in params]
    assert names == ["steel", "fy", "gamma_x", "Wx", "Mx"]   # 声明顺序
    steel = params[0]
    assert steel["label"] == "钢材牌号" and steel["choices"] == ["Q235B", "Q355B"]


def test_template_404(client: TestClient) -> None:
    assert client.get("/api/templates/nope.calc/schema").status_code == 404


def test_refresh(client: TestClient, tmp_path: Path) -> None:
    src = (tmp_path / "gl.py").read_text(encoding="utf-8")
    (tmp_path / "gl.py").write_text(
        src.replace('template("钢梁强度验算"', 'template("钢梁V2"'), encoding="utf-8",
    )
    r = client.post("/api/templates/refresh")
    assert r.json()["templates"][0]["name"] == "钢梁V2"


# ----------------------------------------------------------------------
# 计算
# ----------------------------------------------------------------------
def test_run_ok(client: TestClient) -> None:
    r = client.post("/api/run", json={"template_id": "gl.calc", "params": {}})
    data = r.json()
    assert data["ok"] is True and data["all_ok"] is True
    assert "验算项" in data["md"]
    assert data["checks"][0]["ratio"] == pytest.approx(0.443, abs=1e-3)


def test_run_error_visible(client: TestClient) -> None:
    r = client.post("/api/run", json={"template_id": "gl.calc", "params": {"fy": 0}})
    data = r.json()
    assert data["ok"] is False
    assert data["error_title"] == "参数校验失败"
    assert "fy" in data["error"]


def test_run_batch(client: TestClient) -> None:
    r = client.post("/api/run-batch", json={
        "template_id": "gl.calc",
        "items": [
            {"template_id": "gl.calc", "name": "GL-1", "params": {}},
            {"template_id": "gl.calc", "name": "GL-2", "params": {"Mx": 500}},
            {"template_id": "gl.calc", "name": "GL-3", "params": {"fy": 0}},  # 坏行
        ],
    })
    results = r.json()["results"]
    assert [x["id"] for x in results] == ["GL-1", "GL-2", "GL-3"]
    assert results[0]["all_ok"] is True
    assert results[1]["all_ok"] is False
    assert results[2]["ok"] is False and "fy" in results[2]["error"]


# ----------------------------------------------------------------------
# 工程
# ----------------------------------------------------------------------
def _proj_doc() -> dict:
    return {
        "name": "测试工程",
        "items": [
            {"name": "GL-1", "template_id": "gl.calc", "template_hash": "x" * 64,
             "params": {"Mx": 100}},
        ],
        "views": {"gl.calc": {"hidden_cols": ["fy"]}},
    }


def test_project_put_get_save_load(client: TestClient, tmp_path: Path) -> None:
    r = client.put("/api/project", json=_proj_doc())
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "GL-1"
    assert r.json()["items"][0]["id"]                      # 服务端补 id

    path = str(tmp_path / "p.cbproj")
    assert client.post("/api/project/save", json={"path": path}).status_code == 200

    client.post("/api/project/new", json={"name": "空工程"})
    assert client.get("/api/project").json()["items"] == []

    r = client.post("/api/project/load", json={"path": path})
    assert r.json()["name"] == "测试工程"
    assert r.json()["items"][0]["params"]["Mx"] == 100


def test_hash_check_stale(client: TestClient, tmp_path: Path) -> None:
    doc = _proj_doc()
    doc["items"][0]["template_hash"] = "0" * 64            # 伪造旧 hash
    client.put("/api/project", json=doc)
    rows = client.get("/api/hash-check").json()["items"]
    assert rows[0]["stale"] is True

    # 换成真实 hash → 不失效
    real = client.get("/api/templates/gl.calc/schema").json()["hash"]
    doc["items"][0]["template_hash"] = real
    client.put("/api/project", json=doc)
    rows = client.get("/api/hash-check").json()["items"]
    assert rows[0]["stale"] is False


# ----------------------------------------------------------------------
# 导出 HTML
# ----------------------------------------------------------------------
def test_run_returns_html(client: TestClient) -> None:
    """直通管线:/api/run 直接返回 html;md 仍保留为导出物。"""
    r = client.post("/api/run", json={"template_id": "gl.calc", "params": {}}).json()
    assert r["ok"] is True
    assert "<h1>" in r["html"] and "class='formula'" in r["html"]
    assert r["md"].startswith("# ")


def test_export_html(client: TestClient) -> None:
    html = client.post("/api/run", json={
        "template_id": "gl.calc", "params": {},
    }).json()["html"]
    r = client.post("/api/export/html", json={
        "html": html, "title": "钢梁验算",
        "meta": {"工程名称": "测试", "计算人": "张三", "日期": "2026-09-05"},
    })
    page = r.json()["html"]
    assert "$$\\sigma" in page                             # 公式原样留给 KaTeX
    assert "工程名称：测试" in page
    assert "renderMathInElement" in page
    assert "window.print" in page


def test_export_html_passthrough(client: TestClient) -> None:
    """服务端对内容不做任何再加工：原样注入模板(分页 div 由前端拼)。"""
    r = client.post("/api/export/html", json={
        "html": "<p>第一页</p><div class='page-break'></div><p>第二页</p>",
    })
    page = r.json()["html"]
    assert "<p>第一页</p><div class='page-break'></div><p>第二页</p>" in page


def test_export_html_offline(client: TestClient) -> None:
    """离线版：KaTeX 样式/脚本/字体全部内联，不依赖任何外部 URL。"""
    html = client.post("/api/run", json={"template_id": "gl.calc", "params": {}}
                       ).json()["html"]
    page = client.post("/api/export/html", json={
        "html": html, "title": "离线", "inline_assets": True,
    }).json()["html"]

    assert "cdn.jsdelivr" not in page             # 无外部依赖
    assert "url(fonts/" not in page               # 字体已 base64，无残留相对路径
    assert page.count("data:font/woff2") >= 20     # woff2 字体已内联
    assert "katex" in page.lower()                 # KaTeX 样式与脚本在文内
    assert len(page) > 500_000                     # 体量符合预期（~0.65 MB）


def test_export_html_cdn_default(client: TestClient) -> None:
    """默认仍为 CDN 轻量版，保持小文件。"""
    html = client.post("/api/run", json={"template_id": "gl.calc", "params": {}}
                       ).json()["html"]
    page = client.post("/api/export/html", json={"html": html}).json()["html"]
    assert "cdn.jsdelivr" in page
    assert "data:font/woff2" not in page
    assert len(page) < 100_000
