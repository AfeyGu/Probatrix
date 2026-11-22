//! CalcBook 桌面宿主（Windows / Tauri 2）。
//!
//! 职责只有五件：开窗口、把窗口外框修成圆角、以无窗口方式拉起 Python 后台、等就绪后把
//! WebView 指到 `http://127.0.0.1:<port>/`、退出时优雅回收后台。界面与计算全部由现有
//! Vue + FastAPI 承担，宿主不内置任何业务逻辑。
//!
//! 发布版使用 Windows 图形子系统（`windows_subsystem = "windows"`），副产物是没有任何
//! 控制台窗口：本进程自身不分配控制台，子进程用 `CREATE_NO_WINDOW` 同样不分配。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod host;
mod logging;
mod rounding;
mod ui;

use std::path::{Path, PathBuf};
use std::sync::Arc;

use tauri::{ipc::CapabilityBuilder, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

use crate::host::{Host, Startup};
use crate::logging::Log;

/// 宿主创建的 WebView 窗口标签。
const WINDOW_LABEL: &str = "main";

/// 默认工作窗口尺寸，给顶栏操作和两列工作区留出空间。
const WINDOW_WIDTH: f64 = 1536.0;
const WINDOW_HEIGHT: f64 = 846.0;

/// 交给 Tauri 全局状态：退出事件里靠它拿回同一个 Host（从而只回收自己的子进程）。
struct HostState(Arc<Host>);

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let log = Arc::new(open_log(app.handle()));
            log.write("host", "==== CalcBook 桌面宿主启动 ====");

            let exe_dir = exe_dir(&log);
            log.write("host", &format!("程序目录：{}", exe_dir.display()));

            // 先建窗口并载入本机启动页：Python 起来之前用户看到的是这一步。
            let window =
                WebviewWindowBuilder::new(app, WINDOW_LABEL, WebviewUrl::App("index.html".into()))
                    .title("CalcBook")
                    .inner_size(WINDOW_WIDTH, WINDOW_HEIGHT)
                    .min_inner_size(960.0, 640.0)
                    .center()
                    // 关掉 tao 的无装饰落影：它靠一圈隐藏的非客户区合成阴影，代价是客户区
                    // 比窗口矩形各小 8 像素（可见内容外多一圈半透明带、边上出现深灰台阶），
                    // 且这种模式只命中上边框缩放。关掉之后客户区等于整个窗口矩形：外圈干净，
                    // 圆角直接落在可见内容上，保留四条缩放边。启动页继续使用系统标题栏。
                    .shadow(false)
                    .build()?;

            let host = Arc::new(Host::new(Arc::clone(&log)));
            app.manage(HostState(Arc::clone(&host)));

            // 外框圆角交给宿主：启动页期间窗口有系统标题栏，模块按 is_decorated 自己跳过；
            // 前端 setDecorations(false) 之后随窗口事件跟上。
            rounding::install(&window, Arc::clone(&log));

            Host::start(&host, exe_dir, {
                let window = window.clone();
                let log = Arc::clone(&log);
                move |outcome| match outcome {
                    Startup::Ready { port } => show_app(&window, &log, port),
                    Startup::Failed { message } => ui::show_error(&window, &message, log.path()),
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("无法初始化 CalcBook 窗口");

    app.run(|app_handle, event| match event {
        // 关窗或主动退出时回收 Python；stop_child 可重复调用，Exit 只是兜底。
        RunEvent::ExitRequested { .. } | RunEvent::Exit => shutdown(app_handle),
        _ => {}
    });
}

/// 启动页保留系统窗口边框。主页面挂载后，用本次实例的窗口权限切换到自绘顶栏。
fn show_app(window: &tauri::WebviewWindow, log: &Log, port: u16) {
    let address = format!("http://127.0.0.1:{port}/");
    match tauri::Url::parse(&address) {
        Ok(url) => {
            let controls = CapabilityBuilder::new("main-window-controls")
                .local(false)
                .webview(WINDOW_LABEL)
                .remote(address.clone())
                .permission("core:window:allow-set-decorations")
                .permission("core:window:allow-is-maximized")
                .permission("core:window:allow-start-dragging")
                .permission("core:window:allow-start-resize-dragging")
                .permission("core:window:allow-internal-toggle-maximize")
                .permission("core:window:allow-toggle-maximize")
                .permission("core:window:allow-minimize")
                .permission("core:window:allow-close");
            if let Err(err) = window.app_handle().add_capability(controls) {
                log.write("host", &format!("无法启用自绘顶栏：{err}"));
            }
            log.write("host", &format!("载入界面：{address}"));
            if let Err(err) = window.navigate(url) {
                let message = format!("无法载入界面地址 {address}：{err}");
                log.write("host", &message);
                ui::show_error(window, &message, log.path());
            }
        }
        Err(err) => {
            let message = format!("后台返回的端口无法组成界面地址：{err}");
            log.write("host", &message);
            ui::show_error(window, &message, log.path());
        }
    }
}

fn shutdown(app_handle: &tauri::AppHandle) {
    if let Some(state) = app_handle.try_state::<HostState>() {
        state.0.stop_child();
    }
}

/// 日志固定落在应用日志目录；取不到时退到临时目录，保证诊断信息不丢。
fn open_log(app_handle: &tauri::AppHandle) -> Log {
    let dir = app_handle
        .path()
        .app_log_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("CalcBook").join("logs"));
    Log::open(dir.join("calcbook-desktop.log"))
}

fn exe_dir(log: &Log) -> PathBuf {
    match std::env::current_exe() {
        Ok(path) => path
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| PathBuf::from(".")),
        Err(err) => {
            log.write("host", &format!("无法确定程序路径：{err}"));
            PathBuf::from(".")
        }
    }
}
