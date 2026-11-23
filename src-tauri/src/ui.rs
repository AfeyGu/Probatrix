//! 启动页与错误页的状态推送。
//!
//! 页面是本机静态页（`ui/index.html`），不开放 Tauri 插件与 Rust IPC；
//! 宿主只单向调用页面里定义的 `__probatrixFail`，把启动页换成错误视图。
//! 参数经 `serde_json` 编码后拼进脚本，中文路径与引号都不会破坏脚本。
//!
//! 时序风险：页面脚本可能还没执行完（配置缺失这类失败是毫秒级的），此时 eval 会丢。
//! 页内函数放在 `<head>` 定义、对未就绪的 DOM 做延迟应用；宿主这边再按退避补发几次，
//! 两边一起把「错误页不显示」的窗口压到可以忽略。

use std::path::Path;
use std::time::Duration;

use tauri::WebviewWindow;

/// 补发时刻（毫秒，累计）：覆盖页面从创建到脚本可用的整段时间。
const RETRY_DELAYS_MS: [u64; 5] = [200, 600, 1200, 2200, 3500];

/// 通知页面进入错误态。
pub fn show_error(window: &WebviewWindow, message: &str, log_path: &Path) {
    let payload = serde_json::json!({
        "message": message,
        "logPath": log_path.to_string_lossy(),
    });
    let script = format!("window.__probatrixFail && window.__probatrixFail({payload});");
    let window = window.clone();
    let spawned = std::thread::Builder::new()
        .name("probatrix-error-page".into())
        .spawn(move || {
            let mut elapsed = 0;
            for deadline in RETRY_DELAYS_MS {
                std::thread::sleep(Duration::from_millis(deadline - elapsed));
                elapsed = deadline;
                // 页面已切到错误态时重复调用无害（纯幂等赋值）。
                if window.eval(&script).is_err() {
                    return;
                }
            }
        });
    let _ = spawned;
}
