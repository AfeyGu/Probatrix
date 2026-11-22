//! Python 后台协议的离线验证：桩模块冒充 `calcbook.desktop`，覆盖就绪、非法端口、
//! 提前退出、超时与 stdin 关闭后的优雅停机和超期强杀。全部走真实子进程管线，
//! 因此顺带实测了「子进程没有控制台」这一条验收点（桩里读 GetConsoleWindow）。

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use super::*;

/// 桩模块：按环境变量选择行为；把自身 `GetConsoleWindow()` 结果写进 `CALCBOOK_STUB_OUT`。
const STUB_SOURCE: &str = r#"
import os, sys, time

def probe():
    out = os.environ.get("CALCBOOK_STUB_OUT")
    if not out:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        hwnd = -1
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(str(hwnd))

probe()
mode = os.environ.get("CALCBOOK_STUB_MODE", "ready")
if mode == "ready":
    print("stub: 解释器=%s" % sys.executable)
    print("stub: 普通日志行，宿主应忽略")
    sys.stdout.write('CALCBOOK_READY {"port": 43210}\n')
    sys.stdout.flush()
    sys.stdin.read()
    sys.exit(0)
elif mode == "bad_port":
    sys.stdout.write('CALCBOOK_READY {"port": 0}\n')
    sys.stdout.flush()
    time.sleep(60)
elif mode == "die":
    sys.stderr.write("模板目录不可用（桩）\n")
    sys.stderr.flush()
    sys.exit(3)
elif mode == "silent":
    time.sleep(60)
"#;

/// 改环境变量的用例串行执行：子进程会继承测试进程的环境。
static ENV_LOCK: Mutex<()> = Mutex::new(());

/// 用例失败会让锁中毒；后续用例仍应能继续跑，故统一取回内部守卫。
fn env_lock() -> std::sync::MutexGuard<'static, ()> {
    ENV_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn stub_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("calcbook-stub-{}-{tag}", std::process::id()));
    let package = dir.join("calcbook");
    fs::create_dir_all(&package).expect("创建桩目录失败");
    fs::write(package.join("__init__.py"), "").expect("写桩包失败");
    fs::write(package.join("desktop.py"), STUB_SOURCE).expect("写桩模块失败");
    dir
}

fn python_exe() -> Option<PathBuf> {
    if let Some(path) = std::env::var_os("CALCBOOK_TEST_PYTHON") {
        return Some(PathBuf::from(path));
    }
    let search = std::env::var_os("PATH")?;
    std::env::split_paths(&search)
        .map(|entry| entry.join("python.exe"))
        .find(|candidate| candidate.is_file())
}

/// 桩配置：模板目录故意带中文与空格，顺带验证 argv 传递。
fn stub_config(stub: &Path) -> Option<Config> {
    let python = python_exe()?;
    let templates = stub.join("模板 目录");
    fs::create_dir_all(&templates).ok()?;
    Some(Config {
        python,
        templates,
        work_dir: stub.to_path_buf(),
    })
}

fn ready_host(stub: &Path) -> Arc<Host> {
    Arc::new(Host::new(Arc::new(Log::open(stub.join("app.log")))))
}

fn log_text(host: &Host) -> String {
    fs::read_to_string(host.log.path()).unwrap_or_default()
}

#[test]
fn parse_ready_accepts_protocol_line() {
    let line = parse_ready("CALCBOOK_READY {\"port\":12345}");
    assert_eq!(line.and_then(|parsed| parsed.ok()), Some(12345));
    let padded = parse_ready("  CALCBOOK_READY   {\"port\": 65535}  \r");
    assert_eq!(padded.and_then(|parsed| parsed.ok()), Some(65535));
}

#[test]
fn parse_ready_rejects_bad_payloads() {
    let zero = parse_ready("CALCBOOK_READY {\"port\":0}").unwrap();
    assert!(zero.unwrap_err().contains("端口无效：0"));

    let too_big = parse_ready("CALCBOOK_READY {\"port\":70000}").unwrap();
    assert!(too_big.unwrap_err().contains("端口无效：70000"));

    let missing = parse_ready("CALCBOOK_READY {\"where\":1}").unwrap();
    assert!(missing.unwrap_err().contains("缺少 port 字段"));

    let broken = parse_ready("CALCBOOK_READY 不是 JSON").unwrap();
    assert!(broken.unwrap_err().contains("不是有效 JSON"));

    assert!(parse_ready("普通日志行").is_none());
}

#[test]
fn locate_prefers_env_overrides() {
    let base = stub_dir("locate-env");
    let python = base.join("自定义 python").join("python.exe");
    fs::create_dir_all(python.parent().unwrap()).unwrap();
    fs::write(&python, b"").unwrap();
    let templates = base.join("模板 目录");
    fs::create_dir_all(&templates).unwrap();

    let config = locate(&base.join("程序 目录"), |name| match name {
        "CALCBOOK_PYTHON" => Some(python.display().to_string()),
        "CALCBOOK_TEMPLATES" => Some(format!("  {}  ", templates.display())),
        _ => None,
    })
    .expect("环境变量覆盖应生效");
    assert_eq!(config.python, python);
    assert_eq!(config.templates, templates);
    assert_eq!(config.work_dir, base.join("程序 目录"));
}

#[test]
fn locate_reports_missing_pieces_and_relative_override() {
    let base = stub_dir("locate-missing");

    let no_python = locate(&base, |_| None).unwrap_err();
    assert!(no_python.contains("找不到 Python 运行环境"));
    assert!(no_python.contains("python\\python.exe"));

    fs::create_dir_all(base.join("python")).unwrap();
    fs::write(base.join("python").join("python.exe"), b"").unwrap();
    let no_templates = locate(&base, |_| None).unwrap_err();
    assert!(no_templates.contains("找不到计算模板目录"));
    assert!(no_templates.contains("examples"));

    let relative = locate(&base, |name| match name {
        "CALCBOOK_TEMPLATES" => Some("相对/模板".to_string()),
        _ => None,
    })
    .unwrap_err();
    assert!(
        relative.contains("CALCBOOK_TEMPLATES 必须是绝对路径"),
        "{relative}"
    );
}

#[test]
fn ready_then_graceful_shutdown_on_stdin_close() {
    let _guard = env_lock();
    let stub = stub_dir("ready");
    let Some(config) = stub_config(&stub) else {
        eprintln!("跳过：未找到 python.exe");
        return;
    };
    let probe = stub.join("console.txt");
    std::env::set_var("PYTHONPATH", &stub);
    std::env::set_var("CALCBOOK_STUB_MODE", "ready");
    std::env::set_var("CALCBOOK_STUB_OUT", &probe);

    let host = ready_host(&stub);
    let (ready, pid) = host.launch(&config).expect("桩后台应能启动");
    let port = host
        .wait_ready(ready, pid, Duration::from_secs(20))
        .expect("应读到就绪行");
    assert_eq!(port, 43210);

    // 子进程不持有任何控制台：这就是「连一闪的黑窗都没有」的可验证证据。
    let hwnd = fs::read_to_string(&probe).unwrap_or_default();
    assert_eq!(hwnd.trim(), "0", "子进程不应持有控制台窗口");

    let started = Instant::now();
    host.stop_child();
    assert!(
        started.elapsed() < SHUTDOWN_TIMEOUT,
        "关停应在期限内完成，实际 {:?}",
        started.elapsed()
    );
    let log = log_text(&host);
    // 真正跑起来的就是配置里那个解释器（本机验收用 CALCBOOK_TEST_PYTHON 指定的 3.12）。
    let interpreter = format!("解释器={}", config.python.display()).to_lowercase();
    assert!(log.to_lowercase().contains(&interpreter), "日志：{log}");
    assert!(log.contains("已关闭后台 stdin"), "日志：{log}");
    assert!(log.contains("Python 后台已退出（pid="), "应优雅退出：{log}");
    assert!(log.contains("退出码 0"), "应优雅退出：{log}");
    assert!(!log.contains("强制终止"), "不应走到强制终止：{log}");

    // 退出路径可能重复触发：再调一次也应安全。
    host.stop_child();
}

#[test]
fn early_exit_reports_exit_code() {
    let _guard = env_lock();
    let stub = stub_dir("die");
    let Some(config) = stub_config(&stub) else {
        eprintln!("跳过：未找到 python.exe");
        return;
    };
    std::env::set_var("PYTHONPATH", &stub);
    std::env::set_var("CALCBOOK_STUB_MODE", "die");
    std::env::remove_var("CALCBOOK_STUB_OUT");

    let host = ready_host(&stub);
    let (ready, pid) = host.launch(&config).expect("桩后台应能启动");
    let message = host
        .wait_ready(ready, pid, Duration::from_secs(20))
        .unwrap_err();
    assert!(message.contains("就绪前退出"), "实际：{message}");
    assert!(message.contains("退出码 3"), "实际：{message}");
    host.stop_child();
}

#[test]
fn startup_failure_recycles_without_blocking_error_page() {
    let _guard = env_lock();
    let stub = stub_dir("silent");
    let Some(config) = stub_config(&stub) else {
        eprintln!("跳过：未找到 python.exe");
        return;
    };
    std::env::set_var("PYTHONPATH", &stub);
    std::env::set_var("CALCBOOK_STUB_MODE", "silent");
    std::env::remove_var("CALCBOOK_STUB_OUT");

    let host = ready_host(&stub);
    let (ready, pid) = host.launch(&config).expect("桩后台应能启动");
    let message = host
        .wait_ready(ready, pid, Duration::from_secs(1))
        .unwrap_err();
    assert!(message.contains("超时"), "实际：{message}");

    // 启动失败走 recycle：不置 stopping，错误页才有机会显示。
    host.recycle();
    assert!(
        !host.stopping.load(std::sync::atomic::Ordering::SeqCst),
        "启动失败回收不应标记退出流程"
    );
    let log = log_text(&host);
    assert!(log.contains("强制终止"), "沉默的后台应被强制回收：{log}");
}

#[test]
fn invalid_port_is_reported() {
    let _guard = env_lock();
    let stub = stub_dir("bad-port");
    let Some(config) = stub_config(&stub) else {
        eprintln!("跳过：未找到 python.exe");
        return;
    };
    std::env::set_var("PYTHONPATH", &stub);
    std::env::set_var("CALCBOOK_STUB_MODE", "bad_port");
    std::env::remove_var("CALCBOOK_STUB_OUT");

    let host = ready_host(&stub);
    let (ready, pid) = host.launch(&config).expect("桩后台应能启动");
    let message = host
        .wait_ready(ready, pid, Duration::from_secs(20))
        .unwrap_err();
    assert!(message.contains("端口无效：0"), "实际：{message}");
    host.stop_child();
}
