//! 无边框窗口的圆角外框（Win32 窗口区域）。
//!
//! 自绘顶栏接手窗口外框之后，圆角由本模块负责：`CreateRoundRectRgn` 造一个圆角区域，
//! `SetWindowRgn` 交给系统剪裁整个顶层窗口（WebView 等子窗口一并被裁）。
//! 相比 DWM 的 `DWMWA_WINDOW_CORNER_PREFERENCE`（半径固定为系统值、Win11 才有），
//! 区域方案可以自定义半径、Win10 也能用；代价是区域边缘不做抗锯齿，圆角有一像素锯齿。
//!
//! 三条边界：
//! - 只在窗口真正无装饰时装配。启动页保留系统标题栏，那时窗口区域与客户区之间存在
//!   非客户区偏移，硬装必然错位，所以先让系统自己画。
//!   装饰状态只能问 Tauri（`is_decorated`）：tao 在 Windows 上始终保留 `WS_CAPTION`
//!   样式位、靠 `WM_NCCALCSIZE` 把标题栏收掉，读样式位会误判。
//! - 最大化 / 全屏 / 系统贴靠时清除区域：这些状态的外框贴着屏幕边，圆角只会切掉内容。
//!   贴靠按「某个方向铺满工作区并顶到两边」几何判定——Win10 没有 `IsWindowArranged`，
//!   几何判定在 Win10/Win11 上同样成立，不必绑定新版 API。
//! - 半径按窗口当前缩放系数换算：UI 令牌的 24 逻辑像素 × scale_factor。
//!
//! 区域形状：主窗口建窗时已用 `.shadow(false)` 关掉 tao 的无装饰落影，因此客户区等于
//! 整个窗口矩形，区域就是一个覆盖窗口的圆角矩形——可见内容四角都是真圆角，四边直边段
//! 都在窗口内，`WM_NCHITTEST` 能给出 HTLEFT/HTRIGHT/HTTOP/HTBOTTOM（还有四角）。
//! 万一哪次客户区又不等于窗口矩形（装饰状态切换的瞬间、或 tao 将来改回带 insets），
//! 区域会自动变成「客户区圆角块 ∪ 上下直边带 ∪ 左右直边带」：圆角仍落在看得见的内容角上，
//! 直边带保住 resize 命中。带 insets 时若把圆角锚在窗口矩形上，下两角会被那圈非客户区
//! 顶到看不见的地方（客户区底边距窗口底边 8 像素，弧线恰好落在客户区之外）。
//!
//! 资源归属：区域一旦被 `SetWindowRgn` 接受就归系统所有，下一次设置或清除时由系统释放；
//! 我们只在它被**拒绝**时自己 `DeleteObject`，否则会泄漏 GDI 句柄。
//!
//! 触发方式：窗口事件（尺寸/位置/DPI/焦点）即时同步；装饰切换本机实测会让客户区高度变化
//! 从而触发 `Resized`，但仍留一段**有限**的启动补查（装上一次或十秒内退完即结束线程），
//! 不做常驻轮询。所有 Win32 调用都 post 到主线程执行（`SetWindowRgn` 要求调用线程拥有窗口）。
//!
//! 重入：`run_on_main_thread` 在主线程上是同步执行（不排队），而 `SetWindowRgn` 会同步派发
//! 窗口消息，可能绕回来再触发一次同步。因此写区域前**先更新缓存**，并用 `try_lock` 当门禁：
//! 绕回来的那次直接跳过，既不会递归也不会自锁。

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, TryLockError};
use std::thread;
use std::time::Duration;

use tauri::{WebviewWindow, WindowEvent};
use windows::Win32::Foundation::{HWND, POINT, RECT};
use windows::Win32::Graphics::Gdi::{
    ClientToScreen, CombineRgn, CreateRectRgn, CreateRoundRectRgn, DeleteObject, GetMonitorInfoW,
    MonitorFromWindow, SetWindowRgn, HGDIOBJ, HRGN, MONITORINFO, MONITOR_DEFAULTTONEAREST,
    RGN_ERROR, RGN_OR,
};
use windows::Win32::UI::WindowsAndMessaging::{
    GetClientRect, GetWindowRect, IsIconic, IsWindowVisible, IsZoomed,
};

use crate::logging::Log;

/// 圆角半径（逻辑像素）：与 UI 令牌 `--r-card` 同一口径，设计稿里卡片与窗口外框同半径。
const CORNER_RADIUS_LOGICAL: f64 = 24.0;

/// 启动补查间隔与次数：覆盖「建窗 → 前端挂载 → 切装饰」这段，装上一次即停。
/// 只在装饰切换确实不发窗口事件时才起作用，属于退路而非主路径。
const SETTLE_INTERVAL: Duration = Duration::from_millis(250);
const SETTLE_ATTEMPTS: usize = 40;

/// 贴靠/最大化判定的容差（物理像素）：DWM 会让最大化窗口比工作区略大一点。
const SNAP_TOLERANCE: i32 = 2;

/// 已经生效的区域。`None` 表示窗口当前没有自定义区域。
/// 尺寸全部是物理像素，坐标相对窗口左上角。
#[derive(Clone, Copy, PartialEq, Eq)]
struct Applied {
    /// 客户区（可见内容）在窗口内的偏移：圆角锚在这一层，才能落在看得见的内容角上。
    client_x: i32,
    client_y: i32,
    client_width: i32,
    client_height: i32,
    /// HWND 矩形尺寸（含四边 resize 非客户区）。
    outer_width: i32,
    outer_height: i32,
    /// 物理像素圆角半径。
    radius: i32,
}

/// 本轮期望的状态。
enum Plan {
    /// 状态不稳定（最小化、隐藏、取不到尺寸），保持现状。
    Skip,
    /// 需要没有自定义区域，附诊断用的原因。
    Square(&'static str),
    /// 需要圆角区域。
    Rounded(Applied),
}

struct Shared {
    window: WebviewWindow,
    log: Arc<Log>,
    /// 我们最后一次成功写入的区域；既用来把重复同步压成空操作，也是「已装上」的标志。
    applied: Mutex<Option<Applied>>,
    /// 失败诊断只写一次，避免重复同步刷日志。
    warned: AtomicBool,
}

/// 接管该窗口的外框圆角。失败不阻断启动：拿不到窗口句柄只是少一层圆角。
pub fn install(window: &WebviewWindow, log: Arc<Log>) {
    let shared = Arc::new(Shared {
        window: window.clone(),
        log: Arc::clone(&log),
        applied: Mutex::new(None),
        warned: AtomicBool::new(false),
    });

    // 主路径：拖拽缩放、跨屏 DPI、还原/最大化、切装饰都伴随这些事件。
    let on_event = Arc::clone(&shared);
    window.on_window_event(move |event| {
        if matches!(
            event,
            WindowEvent::Resized(_)
                | WindowEvent::Moved(_)
                | WindowEvent::ScaleFactorChanged { .. }
                | WindowEvent::Focused(_)
        ) {
            on_event.request_sync();
        }
    });

    // 退路：装饰切换万一没有窗口事件，建窗后短时间内补查几次，装上即止。
    let spawned = thread::Builder::new()
        .name("calcbook-frame".into())
        .spawn(move || shared.settle_after_startup());
    if let Err(err) = spawned {
        log.write("host", &format!("无法创建窗口圆角补查线程：{err}"));
    }
}

impl Shared {
    /// 把一次同步排到主线程；事件循环已结束后 post 会失败，那时没必要再做什么。
    fn request_sync(self: &Arc<Self>) {
        let shared = Arc::clone(self);
        let _ = self.window.run_on_main_thread(move || shared.sync());
    }

    fn settle_after_startup(self: Arc<Self>) {
        for _ in 0..SETTLE_ATTEMPTS {
            thread::sleep(SETTLE_INTERVAL);
            if self.has_region() {
                return;
            }
            let shared = Arc::clone(&self);
            // post 失败说明窗口已销毁或事件循环已退出，线程随之收手。
            if self
                .window
                .run_on_main_thread(move || shared.sync())
                .is_err()
            {
                return;
            }
        }
    }

    fn has_region(&self) -> bool {
        self.applied
            .lock()
            .unwrap_or_else(|poison| poison.into_inner())
            .is_some()
    }

    /// 按当前窗口状态把区域对齐到期望值。必须在主线程调用（`SetWindowRgn` 的线程要求）。
    fn sync(&self) {
        if let Err(message) = self.apply_plan() {
            // 区域写不进去时窗口照常可用，只是没有圆角；诊断只写一次。
            if !self.warned.swap(true, Ordering::SeqCst) {
                self.log
                    .write("host", &format!("窗口圆角未生效：{message}"));
            }
        }
    }

    fn apply_plan(&self) -> Result<(), String> {
        // 句柄与装饰状态在窗口刚建好、正在销毁这两个瞬间可能取不到：那是瞬态，
        // 保持现状即可，不当失败（否则日志里会留下一次没有意义的告警）。
        let Ok(hwnd) = self.window.hwnd() else {
            return Ok(());
        };
        let scale = self.window.scale_factor().unwrap_or(1.0);
        // 装饰状态只能问 Tauri：tao 始终保留 WS_CAPTION 样式位（靠 WM_NCCALCSIZE 收标题栏）。
        let Ok(decorated) = self.window.is_decorated() else {
            return Ok(());
        };

        let (target, reason) = match plan(hwnd, scale, decorated) {
            Plan::Skip => return Ok(()),
            Plan::Square(reason) => (None, reason),
            Plan::Rounded(region) => (Some(region), "自绘顶栏"),
        };

        // 门禁：写区域期间持锁，绕回来的同步在 `try_lock` 处直接跳过（同一线程自锁会死等）。
        let mut applied = match self.applied.try_lock() {
            Ok(guard) => guard,
            Err(TryLockError::WouldBlock) => return Ok(()),
            Err(TryLockError::Poisoned(poison)) => poison.into_inner(),
        };
        let current = *applied;
        if current == target {
            return Ok(());
        }

        // 先记下目标状态再动系统：`SetWindowRgn` 同步派发窗口消息，事件绕回来时
        // 看到的就是新状态，不会再来第二遍。
        *applied = target;
        let outcome = match target {
            Some(region) => set_region(hwnd, region),
            None => clear_region(hwnd),
        };
        if outcome.is_err() {
            // 系统拒绝：回滚缓存，下一次窗口事件再试；窗口其余部分照常可用。
            *applied = current;
        }
        drop(applied);
        outcome?;

        let message = match target {
            Some(region) => format!(
                "窗口圆角生效（{reason}）：半径 {} 像素，窗口 {}×{}，客户区 {}×{}（偏移 {},{}），缩放 {scale:.2}",
                region.radius,
                region.outer_width,
                region.outer_height,
                region.client_width,
                region.client_height,
                region.client_x,
                region.client_y
            ),
            None => format!("窗口圆角已清除（{reason}）"),
        };
        self.log.write("host", &message);
        Ok(())
    }
}

/// 读窗口状态，决定这一轮该装什么。
fn plan(hwnd: HWND, scale: f64, decorated: bool) -> Plan {
    if decorated {
        // 启动页/回退状态：系统标题栏自己负责外框形状。
        return Plan::Square("系统标题栏");
    }
    // SAFETY: 句柄来自本进程的窗口；这里只做只读查询，任何失败都退化为「保持现状」。
    unsafe {
        if IsIconic(hwnd).as_bool() || !IsWindowVisible(hwnd).as_bool() {
            // 最小化时窗口矩形没有意义（系统给的是图标位置），此刻不动区域。
            return Plan::Skip;
        }
    }
    if let Some(reason) = arranged_reason(hwnd) {
        return Plan::Square(reason);
    }
    let Some(rect) = window_rect(hwnd) else {
        return Plan::Skip;
    };
    let outer_width = rect.right - rect.left;
    let outer_height = rect.bottom - rect.top;
    let Some((client_x, client_y, client_width, client_height)) = client_rect(hwnd) else {
        return Plan::Skip;
    };
    if outer_width <= 0
        || outer_height <= 0
        || client_width <= 0
        || client_height <= 0
        || client_x < 0
        || client_y < 0
        || client_x + client_width > outer_width
        || client_y + client_height > outer_height
    {
        // 客户区与窗口矩形对不上（极小窗、状态切换中途）：这一拍不动区域。
        return Plan::Skip;
    }
    Plan::Rounded(Applied {
        client_x,
        client_y,
        client_width,
        client_height,
        outer_width,
        outer_height,
        radius: radius_for(scale, client_width, client_height),
    })
}

/// 物理像素半径：逻辑半径按 DPI 缩放，且不超过窗口短边的一半（避免小窗整块被切）。
fn radius_for(scale: f64, width: i32, height: i32) -> i32 {
    let physical = (CORNER_RADIUS_LOGICAL * scale).round() as i32;
    let limit = (width / 2).min(height / 2);
    // 半径 0 不是圆角而是直角，极小窗口也至少留 1 像素。
    physical.min(limit).max(1)
}

/// 最大化 / 全屏 / 贴靠的判定：这些状态下外框贴着屏幕边，圆角没有意义。
fn arranged_reason(hwnd: HWND) -> Option<&'static str> {
    // SAFETY: 只读查询窗口与显示器信息，失败返回 None。
    if unsafe { IsZoomed(hwnd) }.as_bool() {
        return Some("最大化");
    }
    let rect = window_rect(hwnd)?;
    let work = work_area(hwnd)?;
    if fills_work_area(rect, work) {
        return Some("贴靠或全屏");
    }
    None
}

/// 窗口是否在某个方向上正好铺满工作区并顶到两侧（左右半屏 / 上下半屏 / 全屏）。
fn fills_work_area(rect: RECT, work: RECT) -> bool {
    let spans_width = rect.right - rect.left >= (work.right - work.left) - SNAP_TOLERANCE
        && rect.left <= work.left + SNAP_TOLERANCE
        && rect.right >= work.right - SNAP_TOLERANCE;
    let spans_height = rect.bottom - rect.top >= (work.bottom - work.top) - SNAP_TOLERANCE
        && rect.top <= work.top + SNAP_TOLERANCE
        && rect.bottom >= work.bottom - SNAP_TOLERANCE;
    spans_width || spans_height
}

fn window_rect(hwnd: HWND) -> Option<RECT> {
    let mut rect = RECT::default();
    // SAFETY: rect 是本栈上的有效输出缓冲。
    unsafe { GetWindowRect(hwnd, &mut rect) }.ok()?;
    Some(rect)
}

/// 客户区相对窗口左上角的偏移与尺寸。区域几何与日志诊断都用这一份。
fn client_rect(hwnd: HWND) -> Option<(i32, i32, i32, i32)> {
    let window = window_rect(hwnd)?;
    let mut client = RECT::default();
    // SAFETY: client 是本栈上的有效输出缓冲。
    unsafe { GetClientRect(hwnd, &mut client) }.ok()?;
    let mut origin = POINT { x: 0, y: 0 };
    // SAFETY: 把客户区原点换算到屏幕坐标，再减窗口原点得到窗口内偏移。
    if unsafe { ClientToScreen(hwnd, &mut origin) }.as_bool() {
        Some((
            origin.x - window.left,
            origin.y - window.top,
            client.right - client.left,
            client.bottom - client.top,
        ))
    } else {
        None
    }
}

fn work_area(hwnd: HWND) -> Option<RECT> {
    // SAFETY: 只读查询；MONITORINFO.cbSize 必须先填对。
    let monitor = unsafe { MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) };
    if monitor.is_invalid() {
        return None;
    }
    let mut info = MONITORINFO {
        cbSize: std::mem::size_of::<MONITORINFO>() as u32,
        ..Default::default()
    };
    if unsafe { GetMonitorInfoW(monitor, &mut info) }.as_bool() {
        Some(info.rcWork)
    } else {
        None
    }
}

/// 三段区域矩形：[客户区圆角块, 上下直边带, 左右直边带]。
/// 后两段把 resize 非客户区补成直边，圆角只作用在看得见的客户区角上。
fn region_parts(region: &Applied) -> [RECT; 3] {
    let (x, y) = (region.client_x, region.client_y);
    let (cw, ch) = (region.client_width, region.client_height);
    let (ow, oh) = (region.outer_width, region.outer_height);
    let r = region.radius;
    [
        // 右/下边界是开区间，+1 才让最右、最下一列像素落在区域内。
        RECT {
            left: x,
            top: y,
            right: x + cw + 1,
            bottom: y + ch + 1,
        },
        // 上下直边带：横向铺满整个窗口，避开圆角所在的上下 24 像素。
        RECT {
            left: 0,
            top: y + r,
            right: ow,
            bottom: y + ch - r,
        },
        // 左右直边带：纵向铺满整个窗口，避开圆角所在的左右 24 像素。
        RECT {
            left: x + r,
            top: 0,
            right: x + cw - r,
            bottom: oh,
        },
    ]
}

fn set_region(hwnd: HWND, region: Applied) -> Result<(), String> {
    let [rounded, band_h, band_v] = region_parts(&region);
    let diameter = region.radius * 2;
    let mut created = Vec::new();
    // SAFETY: 纯 GDI 调用，尺寸已由 `plan` 校验为正；任何一步失败都把已建的区域删干净。
    let combined = unsafe { build_region(&mut created, rounded, band_h, band_v, diameter) };
    let Some(combined) = combined else {
        for rgn in created {
            let _ = unsafe { DeleteObject(HGDIOBJ(rgn.0)) };
        }
        return Err(format!(
            "无法创建半径为 {} 像素的圆角区域（窗口 {}×{}）。",
            region.radius, region.outer_width, region.outer_height
        ));
    };
    // 合成完成后临时区域已经没有用；`combined` 自己还要等系统接手。
    for rgn in created {
        if rgn != combined {
            let _ = unsafe { DeleteObject(HGDIOBJ(rgn.0)) };
        }
    }

    // SAFETY: 区域句柄有效；成功后所有权移交给系统。
    if unsafe { SetWindowRgn(hwnd, Some(combined), true) } == 0 {
        // 被拒绝时区域仍归调用方，必须自己删，否则泄漏 GDI 句柄。
        let _ = unsafe { DeleteObject(HGDIOBJ(combined.0)) };
        return Err(format!(
            "系统拒绝 {}×{} 的圆角区域。",
            region.outer_width, region.outer_height
        ));
    }
    Ok(())
}

/// 建三段区域并把后两段并入第一段；成功返回合成后的句柄。
unsafe fn build_region(
    created: &mut Vec<HRGN>,
    rounded: RECT,
    band_h: RECT,
    band_v: RECT,
    diameter: i32,
) -> Option<HRGN> {
    let main = unsafe {
        CreateRoundRectRgn(
            rounded.left,
            rounded.top,
            rounded.right,
            rounded.bottom,
            diameter,
            diameter,
        )
    };
    if main.is_invalid() {
        return None;
    }
    created.push(main);
    for band in [band_h, band_v] {
        // 空带（窗口太窄/太矮）跳过：矩形右/下边界必须大于左上。
        if band.right <= band.left || band.bottom <= band.top {
            continue;
        }
        let extra = unsafe { CreateRectRgn(band.left, band.top, band.right, band.bottom) };
        if extra.is_invalid() {
            return None;
        }
        created.push(extra);
        if unsafe { CombineRgn(Some(main), Some(main), Some(extra), RGN_OR) } == RGN_ERROR {
            return None;
        }
    }
    Some(main)
}

fn clear_region(hwnd: HWND) -> Result<(), String> {
    // SAFETY: 传 None 表示取消区域，系统顺手释放上一块区域。
    if unsafe { SetWindowRgn(hwnd, None, true) } == 0 {
        return Err("无法清除已设置的窗口区域。".to_string());
    }
    Ok(())
}

#[cfg(test)]
#[path = "rounding_tests.rs"]
mod tests;
