"""桌面宿主后台入口（``probatrix.desktop``）回归：就绪协议独占 stdout、Host/CORS 边界、
stdin EOF 生命周期。

真启动子进程（宿主同款参数 ``-u -X utf8 -m probatrix.desktop --templates``，Windows 下带
``CREATE_NO_WINDOW`` 不闪终端）；进程卡住由测试侧兜底强杀并在 finally 回收。
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from probatrix.desktop import READY_PREFIX

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
SRC = ROOT / "src"
VUE_INDEX = SRC / "probatrix" / "web" / "index.html"
VITE_ORIGIN = "http://127.0.0.1:5173"

#: 测试侧兜底（防止子进程异常卡住 pytest）；产品侧不设启动超时，截止时间归宿主
TIMEOUT = 60.0

#: 带顶层 print 与计算期 print 的模板：stdout 必须仍然只有协议行
_NOISY = '''"""回归夹具：导入期与运行期都 print，验证 stdout 不被污染。"""

import sys

from pydantic import BaseModel

from probatrix import Probatrix, Field, template

print("模板导入期 print：应进 stderr")
if sys.platform == "win32":
    import ctypes
    print("GetConsoleWindow =", ctypes.windll.kernel32.GetConsoleWindow())


class NoisyParams(BaseModel):
    a: float = Field(1.0, label="a", gt=0)


@template("带打印的验算", description="回归：顶层 print 不污染 stdout")
def calc(p: NoisyParams) -> Probatrix:
    print("计算期 print：应进 stderr")
    b = Probatrix(title="带打印的验算")
    b.check("a > 0", value=p.a, limit=0, op="ge")
    return b
'''


def _templates(tmp_path: Path) -> Path:
    """模板目录：自包含的 gl.py + 会 print 的 noisy.py。"""
    (tmp_path / "gl.py").write_text(
        (EXAMPLES / "gl.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "noisy.py").write_text(_NOISY, encoding="utf-8")
    return tmp_path


class _Desktop:
    """一次真实启动：读就绪行、顺手收集 stderr、到点强杀。"""

    def __init__(self, template_dir: Path) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-X", "utf8", "-m", "probatrix.desktop",
             "--templates", str(template_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.port = 0
        self._stderr: list[str] = []
        self._drain = threading.Thread(target=self._drain_stderr, daemon=True)
        self._drain.start()
        self._watchdog = threading.Timer(TIMEOUT, self._kill)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    def _kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()

    def wait_ready(self) -> str:
        """读一行就绪协议并解析端口，返回原始行（含换行）。"""
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline()
        assert line.startswith(READY_PREFIX), (
            f"未收到就绪行，实得 {line!r}；rc={self.proc.poll()} "
            f"stderr={self.stderr_text()!r}")
        self.port = json.loads(line[len(READY_PREFIX):])["port"]
        assert isinstance(self.port, int) and 0 < self.port < 65536, line
        return line

    def close_stdin(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()

    def wait_exit(self, timeout: float = TIMEOUT) -> int:
        return self.proc.wait(timeout=timeout)

    def rest_stdout(self) -> str:
        assert self.proc.stdout is not None
        return self.proc.stdout.read()

    def stderr_text(self) -> str:
        self._drain.join(timeout=5)
        return "".join(self._stderr)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=TIMEOUT)


@contextmanager
def _running(template_dir: Path) -> Iterator[_Desktop]:
    desk = _Desktop(template_dir)
    try:
        yield desk
    finally:
        desk._watchdog.cancel()
        desk.kill()                       # 断言失败也不留下子进程
        for pipe in (desk.proc.stdin, desk.proc.stdout, desk.proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except (OSError, ValueError):
                pass


def _request(port: int, method: str, path: str, body: dict | None = None,
             headers: dict[str, str] | None = None
             ) -> tuple[int, dict[str, str], bytes]:
    """走真实回环 HTTP：Host 由我们自己给，便于构造边界。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        hdrs = dict(headers or {})
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
    finally:
        conn.close()


# ----------------------------------------------------------------------
# 真实启动：就绪行格式 + stdout 独占（模板顶层 print 走 stderr）+ 同源页面/API + EOF 退出
# ----------------------------------------------------------------------
def test_desktop_ready_line_owns_stdout(tmp_path: Path) -> None:
    with _running(_templates(tmp_path)) as desk:
        line = desk.wait_ready()
        assert re.fullmatch(r'PROBATRIX_READY \{"port":[1-9]\d*\}\n', line), line

        status, _, body = _request(desk.port, "GET", "/api/templates")
        assert status == 200
        data = json.loads(body)
        assert {t["template_id"] for t in data["templates"]} == {"gl.calc", "noisy.calc"}
        assert data["errors"] == []

        status, headers, body = _request(desk.port, "GET", "/")
        assert status == 200 and body
        if VUE_INDEX.is_file():            # 有构建产物时首页就是 Vue 静态页
            assert "text/html" in headers["content-type"]
            assert b'id="app"' in body

        # 计算入口照旧可用；计算期的 print 也不许进 stdout
        status, _, body = _request(desk.port, "POST", "/api/run",
                                   {"template_id": "noisy.calc", "params": {"a": 2}})
        assert status == 200 and json.loads(body)["ok"] is True

        desk.close_stdin()                 # 宿主关窗 = 关 stdin
        assert desk.wait_exit() == 0
        assert desk.rest_stdout() == ""    # stdout 只有那一行协议，别无输出
        err = desk.stderr_text()
        assert "模板导入期 print" in err and "计算期 print" in err
        assert "Traceback" not in err


@pytest.mark.skipif(sys.platform != "win32", reason="覆盖 Windows 宿主管道与 NumPy 的交互")
def test_desktop_canopy_cold_start(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    (tmp_path / "canopy.py").write_bytes((EXAMPLES / "canopy.py").read_bytes())
    with _running(tmp_path) as desk:
        desk.wait_ready()
        status, _, body = _request(desk.port, "POST", "/api/run",
                                   {"template_id": "canopy.calc", "params": {}})
        result = json.loads(body)
        assert status == 200 and result["ok"], result.get("error")
        assert "data:image/png;base64" in result["html"]
        assert _request(desk.port, "GET", "/api/templates/canopy.calc/schema")[0] == 200

        desk.close_stdin()
        assert desk.wait_exit() == 0
        assert desk.rest_stdout() == ""


# ----------------------------------------------------------------------
# 真实启动：Host 只认 127.0.0.1（端口可变），且不留 Vite 开发跨来源放行
# ----------------------------------------------------------------------
def test_desktop_host_and_cors_boundaries(tmp_path: Path) -> None:
    with _running(_templates(tmp_path)) as desk:
        desk.wait_ready()
        assert _request(desk.port, "GET", "/api/project")[0] == 200
        for host in ("evil.example", f"localhost:{desk.port}",
                     f"127.0.0.1.evil.example:{desk.port}"):
            status = _request(desk.port, "GET", "/api/project", headers={"Host": host})[0]
            assert status == 400, host
        _, headers, _ = _request(desk.port, "GET", "/api/project",
                                 headers={"Origin": VITE_ORIGIN})
        assert "access-control-allow-origin" not in headers

        desk.close_stdin()
        assert desk.wait_exit() == 0


# ----------------------------------------------------------------------
# 启动过程中就被关闭的 stdin（宿主启动失败立即回收）同样正常退出
# ----------------------------------------------------------------------
def test_desktop_exits_when_stdin_closes_during_startup(tmp_path: Path) -> None:
    with _running(_templates(tmp_path)) as desk:
        desk.close_stdin()                 # 不等就绪行：与启动竞争
        assert desk.wait_exit() == 0
        assert desk.rest_stdout() == ""    # 未就绪就不许吐任何协议行
        assert "Traceback" not in desk.stderr_text()
