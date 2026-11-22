//! Python 后台进程的定位、启动、协议握手与回收。
//!
//! 协议（第一里程碑固定）：宿主以无窗口方式启动
//! `python.exe -u -X utf8 -m calcbook.desktop --templates <目录>`，
//! 后台在真正监听成功后向 stdout 刷新一行 `CALCBOOK_READY {"port":12345}`。
//! 宿主关闭子进程 stdin（EOF）通知后台优雅停机，超过期限才强制终止自己启动的进程。
//! stdout、stderr 全程排空进应用日志，失败提示只给结论与日志位置。

use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use crate::logging::Log;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

/// 子进程创建参数：控制台程序也不分配可见窗口，避免任何一闪而过的黑窗。
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const READY_PREFIX: &str = "CALCBOOK_READY";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(60);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(6);
/// 轮询切片：让「应用退出」能在等待就绪的途中及时中断。
const POLL_SLICE: Duration = Duration::from_millis(200);
/// 后台输出关闭后等它落定退出码的时间。
const EXIT_GRACE: Duration = Duration::from_millis(1500);

/// 启动结果：只剩「拿到端口」与「中文诊断」两种归宿。
pub enum Startup {
    Ready { port: u16 },
    Failed { message: String },
}

/// 已解析的运行时布局（开发期可被环境变量覆盖）。
#[derive(Debug, Clone)]
pub struct Config {
    pub python: PathBuf,
    pub templates: PathBuf,
    pub work_dir: PathBuf,
}

pub struct Host {
    log: Arc<Log>,
    child: Mutex<Option<Child>>,
    /// 仅在「应用退出」时置位：用于中断在途启动、跳过已无意义的错误页。
    /// 启动失败的回收**不能**用它，否则错误页永远不显示。
    stopping: AtomicBool,
}

impl Host {
    pub fn new(log: Arc<Log>) -> Self {
        Self {
            log,
            child: Mutex::new(None),
            stopping: AtomicBool::new(false),
        }
    }

    /// 宿主角色的日志，统一打 host 标签。
    fn note(&self, message: &str) {
        self.log.write("host", message);
    }

    /// 在后台线程完成「定位 → 启动 → 等就绪」，结果通过 `notify` 回到调用方。
    /// 主线程因此始终空闲，窗口在启动期间保持可响应。
    pub fn start(host: &Arc<Self>, exe_dir: PathBuf, notify: impl Fn(Startup) + Send + 'static) {
        let worker = Arc::clone(host);
        let log = Arc::clone(&host.log);
        let spawned = std::thread::Builder::new()
            .name("calcbook-startup".into())
            .spawn(move || match worker.run_startup(&exe_dir) {
                Ok(port) => {
                    if worker.stopping.load(Ordering::SeqCst) {
                        // 启动与退出撞车：不再导航，回收刚起来的后台。
                        worker.recycle();
                    } else {
                        notify(Startup::Ready { port });
                    }
                }
                Err(message) => {
                    worker.note(&format!("启动失败：{message}"));
                    // 先把中文错误交给窗口（配置缺失这类失败往往瞬间发生），再回收子进程。
                    // 回收绝不能置 stopping，否则这里会把自己的提示挡掉。
                    if !worker.stopping.load(Ordering::SeqCst) {
                        notify(Startup::Failed { message });
                    }
                    worker.recycle();
                }
            });
        if let Err(err) = spawned {
            log.write("host", &format!("无法创建启动线程：{err}"));
        }
    }

    fn run_startup(&self, exe_dir: &Path) -> Result<u16, String> {
        let config = locate(exe_dir, env_value)?;
        self.note(&format!(
            "Python 运行环境：{}\n模板目录：{}\n工作目录：{}",
            config.python.display(),
            config.templates.display(),
            config.work_dir.display()
        ));
        let (ready, pid) = self.launch(&config)?;
        self.wait_ready(ready, pid, STARTUP_TIMEOUT)
    }

    /// 启动子进程并接上输出排空线程，返回就绪行通道与 pid。
    ///
    /// 与关闭的交界只有一处：「检查 stopping → spawn → 登记 child」在 `self.child` 锁内
    /// 一次做完。关闭方先置 stopping、再取锁，于是两种结果都安全——
    /// 要么关闭方看到已登记的子进程并回收它，要么启动方在锁内看到 stopping 而不启动。
    /// 输出线程与等待就绪一律在锁外进行。
    fn launch(&self, config: &Config) -> Result<(mpsc::Receiver<String>, u32), String> {
        let (pid, stdout, stderr) = {
            let mut slot = self
                .child
                .lock()
                .map_err(|_| "宿主内部错误：子进程登记锁不可用。".to_string())?;
            if self.stopping.load(Ordering::SeqCst) {
                return Err("启动已取消：应用正在退出。".into());
            }
            let mut child = spawn(config)?;
            let pid = child.id();
            let stdout = child.stdout.take();
            let stderr = child.stderr.take();
            // 先登记再取管道：登记之后任何失败都由 recycle() 兜底，不会漏掉这个进程。
            *slot = Some(child);
            let Some(stdout) = stdout else {
                return Err("宿主内部错误：未取得后台 stdout 管道。".into());
            };
            (pid, stdout, stderr)
            // slot 在此释放：后面的线程创建与等待都不持锁。
        };
        self.note(&format!("已启动 Python 后台，pid={pid}"));

        let ready = self.drain_stdout(stdout);
        if let Some(stderr) = stderr {
            self.drain_stderr(stderr, pid);
        }
        Ok((ready, pid))
    }

    /// 持续排空 stdout：既是日志来源，也是就绪行的通道。
    /// 接收端停止后仍继续读，避免后台写满管道而阻塞。
    fn drain_stdout(&self, stdout: impl Read + Send + 'static) -> mpsc::Receiver<String> {
        let (tx, rx) = mpsc::channel();
        let log = Arc::clone(&self.log);
        let spawned = std::thread::Builder::new()
            .name("calcbook-stdout".into())
            .spawn(move || {
                drain_lines(stdout, |line| {
                    log.write("python:out", &line);
                    let _ = tx.send(line);
                })
            });
        if let Err(err) = spawned {
            self.note(&format!("无法创建后台输出读取线程：{err}"));
        }
        rx
    }

    fn drain_stderr(&self, stderr: impl Read + Send + 'static, pid: u32) {
        let log = Arc::clone(&self.log);
        let spawned = std::thread::Builder::new()
            .name("calcbook-stderr".into())
            .spawn(move || {
                drain_lines(stderr, |line| log.write("python:err", &line));
                log.write("host", &format!("后台 stderr 已关闭，pid={pid}"));
            });
        if let Err(err) = spawned {
            self.note(&format!("无法创建后台错误输出读取线程：{err}"));
        }
    }

    /// 等就绪行：后台退出会让 stdout 提前 EOF，这条路径同时承担「早退」检测。
    fn wait_ready(
        &self,
        ready: mpsc::Receiver<String>,
        pid: u32,
        timeout: Duration,
    ) -> Result<u16, String> {
        let deadline = Instant::now() + timeout;
        loop {
            if self.stopping.load(Ordering::SeqCst) {
                return Err("启动已取消：应用正在退出。".into());
            }
            let now = Instant::now();
            if now >= deadline {
                return Err(format!(
                    "等待 Python 后台就绪超时（{} 秒）。",
                    timeout.as_secs()
                ));
            }
            match ready.recv_timeout(POLL_SLICE.min(deadline - now)) {
                Ok(line) => {
                    // 就绪行非法时用 ? 把中文原因带回调用方。
                    if let Some(parsed) = parse_ready(&line) {
                        let port = parsed?;
                        self.note(&format!("后台就绪，监听端口 {port}"));
                        return Ok(port);
                    }
                }
                Err(RecvTimeoutError::Timeout) => {}
                Err(RecvTimeoutError::Disconnected) => return Err(self.exit_message(pid)),
            }
        }
    }

    /// 后台输出已关闭：给它一点时间落定退出码，比「进程仍在运行」这种模糊说法有用。
    fn exit_message(&self, pid: u32) -> String {
        let deadline = Instant::now() + EXIT_GRACE;
        while Instant::now() < deadline {
            if let Some(status) = self.status() {
                return format!("Python 后台在就绪前退出（pid={pid}，{status}）。");
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        format!("Python 后台的输出已关闭，未取到退出状态（pid={pid}）。")
    }

    fn status(&self) -> Option<String> {
        let mut slot = self.child.lock().ok()?;
        match slot.as_mut()?.try_wait() {
            Ok(Some(status)) => Some(describe(status)),
            Ok(None) => None,
            Err(err) => Some(format!("无法读取进程状态：{err}")),
        }
    }

    /// 关闭 stdin 触发后台优雅停机；超时才强制终止，并且只碰自己启动的进程。
    /// 可重复调用：句柄取出后立刻释放锁，退出路径与启动路径不会互相卡住。
    ///
    /// 正常关闭的边界：只回收本宿主登记过的子进程。宿主被强行结束时不做额外兜底
    /// （不上 Job Object 之类的新机制）——stdin 管道随本进程关闭，Python 侧读到 EOF
    /// 会自行停机。
    pub fn stop_child(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        self.recycle();
    }

    /// 仅回收子进程，不改 `stopping`——启动失败时也要走这一步，但错误页仍须显示。
    fn recycle(&self) {
        let taken = match self.child.lock() {
            Ok(mut slot) => slot.take(),
            Err(_) => None,
        };
        let Some(mut child) = taken else {
            return;
        };
        let pid = child.id();
        // 关闭 stdin：后台读到 EOF 后让 Uvicorn 正常停机。
        drop(child.stdin.take());
        self.note(&format!("已关闭后台 stdin（pid={pid}），等待其退出"));

        let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
        loop {
            match child.try_wait() {
                Ok(Some(status)) => {
                    self.note(&format!(
                        "Python 后台已退出（pid={pid}，{}）",
                        describe(status)
                    ));
                    return;
                }
                Ok(None) => {}
                Err(err) => {
                    self.note(&format!("等待后台退出出错：{err}"));
                    break;
                }
            }
            if Instant::now() >= deadline {
                self.note(&format!(
                    "后台 {} 秒内未退出（pid={pid}），强制终止",
                    SHUTDOWN_TIMEOUT.as_secs()
                ));
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        if let Err(err) = child.kill() {
            self.note(&format!("强制终止后台失败：{err}"));
        }
        match child.wait() {
            Ok(status) => self.note(&format!("后台已被回收（pid={pid}，{}）", describe(status))),
            Err(err) => self.note(&format!("回收后台进程失败：{err}")),
        }
    }
}

/// 每个 argv 元素单独传递（不经 shell），中文与空格路径原样送达 Python。
fn spawn(config: &Config) -> Result<Child, String> {
    let mut command = Command::new(&config.python);
    command
        .arg("-u")
        .arg("-X")
        .arg("utf8")
        .arg("-m")
        .arg("calcbook.desktop")
        .arg("--templates")
        .arg(&config.templates)
        .current_dir(&config.work_dir)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    command.spawn().map_err(|err| {
        format!(
            "无法启动 Python 后台：{}\n解释器：{}",
            err,
            config.python.display()
        )
    })
}

fn drain_lines(stream: impl Read, mut on_line: impl FnMut(String)) {
    let mut reader = BufReader::new(stream);
    let mut buffer = Vec::new();
    loop {
        buffer.clear();
        match reader.read_until(b'\n', &mut buffer) {
            Ok(0) => return,
            Ok(_) => {
                let line = String::from_utf8_lossy(&buffer);
                on_line(line.trim_end_matches(['\r', '\n']).to_string());
            }
            Err(err) => {
                on_line(format!("（读取后台输出出错：{err}）"));
                return;
            }
        }
    }
}

fn describe(status: ExitStatus) -> String {
    match status.code() {
        Some(code) => format!("退出码 {code}"),
        None => "被系统终止".to_string(),
    }
}

/// 解析 `CALCBOOK_READY {"port":12345}`；不是就绪行返回 None。
/// 端口按非零 u16 校验，异常一律给出中文原因。
fn parse_ready(line: &str) -> Option<Result<u16, String>> {
    let rest = line.trim().strip_prefix(READY_PREFIX)?;
    let rest = rest.trim();
    let value: serde_json::Value = match serde_json::from_str(rest) {
        Ok(value) => value,
        Err(_) => return Some(Err(format!("后台就绪信息不是有效 JSON：{rest}"))),
    };
    match value.get("port").and_then(|port| port.as_u64()) {
        Some(port) if (1..=u16::MAX as u64).contains(&port) => Some(Ok(port as u16)),
        Some(port) => Some(Err(format!("后台返回的端口无效：{port}"))),
        None => Some(Err(format!("后台就绪信息缺少 port 字段：{rest}"))),
    }
}

fn env_value(name: &str) -> Option<String> {
    std::env::var_os(name).map(|raw| raw.to_string_lossy().into_owned())
}

/// 运行时布局：环境变量覆盖 > exe 同级默认（`python/python.exe`、`examples/`）。
/// `lookup` 可注入，测试因此不必改全局环境变量。
fn locate(exe_dir: &Path, lookup: impl Fn(&str) -> Option<String>) -> Result<Config, String> {
    let python = match override_path(lookup("CALCBOOK_PYTHON"), "CALCBOOK_PYTHON")? {
        Some(path) => path,
        None => exe_dir.join("python").join("python.exe"),
    };
    if !python.is_file() {
        return Err(format!(
            "找不到 Python 运行环境：{}\nCalcBook.exe 同级目录应包含 python\\python.exe；\
             开发时用环境变量 CALCBOOK_PYTHON 指定 python.exe 的绝对路径。",
            python.display()
        ));
    }
    let templates = match override_path(lookup("CALCBOOK_TEMPLATES"), "CALCBOOK_TEMPLATES")? {
        Some(path) => path,
        None => exe_dir.join("examples"),
    };
    if !templates.is_dir() {
        return Err(format!(
            "找不到计算模板目录：{}\nCalcBook.exe 同级目录应包含 examples\\；\
             开发时用环境变量 CALCBOOK_TEMPLATES 指定模板目录。",
            templates.display()
        ));
    }
    Ok(Config {
        python,
        templates,
        work_dir: exe_dir.to_path_buf(),
    })
}

/// 覆盖值只做去空白；必须是绝对路径，免得「相对路径按谁的工作目录算」这种隐患。
fn override_path(raw: Option<String>, name: &str) -> Result<Option<PathBuf>, String> {
    let Some(raw) = raw else {
        return Ok(None);
    };
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    let path = PathBuf::from(trimmed);
    if !path.is_absolute() {
        return Err(format!("环境变量 {name} 必须是绝对路径，当前值：{trimmed}"));
    }
    Ok(Some(path))
}

#[cfg(test)]
#[path = "host_tests.rs"]
mod tests;
