//! 应用日志：宿主自身状态与 Python 后台的 stdout/stderr 都落到同一个文件。
//!
//! 用户看到的错误提示只给出诊断结论与日志路径，细节留在日志里。
//! 时间戳用 Unix 毫秒整数：够定位先后顺序，又不引入日期库。

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct Log {
    path: PathBuf,
    file: Mutex<Option<File>>,
}

impl Log {
    /// 打开（或追加打开）日志文件；目录不可写时退化为只有路径、不写内容。
    pub fn open(path: PathBuf) -> Self {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .ok();
        Self {
            path,
            file: Mutex::new(file),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// 写一条带时间戳的日志；多行消息逐行加前缀，便于 grep。
    pub fn write(&self, tag: &str, message: &str) {
        let stamp = unix_millis();
        let mut text = String::new();
        for line in message.lines() {
            text.push_str(&format!("{stamp} [{tag}] {line}\n"));
        }
        if text.is_empty() {
            return;
        }
        if let Ok(mut guard) = self.file.lock() {
            if let Some(file) = guard.as_mut() {
                // 写失败不重试也不上报：日志故障不能反过来影响宿主启动。
                let _ = file.write_all(text.as_bytes());
                let _ = file.flush();
            }
        }
    }
}

fn unix_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis())
        .unwrap_or_default()
}
