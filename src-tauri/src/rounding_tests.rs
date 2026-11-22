//! `rounding` 的纯计算部分测试：半径换算与贴靠判定不需要真实窗口。

use super::*;

fn rect(left: i32, top: i32, right: i32, bottom: i32) -> RECT {
    RECT {
        left,
        top,
        right,
        bottom,
    }
}

/// 1080p、任务栏 40 像素的常见工作区。
fn work() -> RECT {
    rect(0, 0, 1920, 1040)
}

#[test]
fn radius_follows_dpi_scaling() {
    assert_eq!(radius_for(1.0, 1536, 846), 24);
    assert_eq!(radius_for(1.25, 1536, 846), 30);
    assert_eq!(radius_for(1.5, 1536, 846), 36);
    assert_eq!(radius_for(2.0, 1536, 846), 48);
}

#[test]
fn radius_never_exceeds_half_of_short_side() {
    // 缩放后半径大于窗口短边一半时，退到一半，避免整个窗口被切没。
    assert_eq!(radius_for(2.0, 40, 30), 15);
    // 极小窗口也至少留 1 像素，不能算出 0（CreateRoundRectRgn 的 0 不是圆角）。
    assert_eq!(radius_for(1.0, 1, 1), 1);
}

#[test]
fn ordinary_window_is_not_arranged() {
    assert!(!fills_work_area(rect(200, 120, 1400, 900), work()));
}

#[test]
fn left_half_snap_counts_as_arranged() {
    // 左右半屏：高度铺满并上下顶边，宽度只占一半。
    assert!(fills_work_area(rect(0, 0, 960, 1040), work()));
    assert!(fills_work_area(rect(960, 0, 1920, 1040), work()));
}

#[test]
fn top_half_snap_counts_as_arranged() {
    // 上下半屏：宽度铺满并左右顶边。
    assert!(fills_work_area(rect(0, 0, 1920, 520), work()));
}

#[test]
fn maximized_overshoot_counts_as_arranged() {
    // Win11 最大化窗口比工作区大一圈（边框藏在屏幕外），同样要按贴靠处理。
    assert!(fills_work_area(rect(-8, -8, 1928, 1048), work()));
}

#[test]
fn window_short_of_the_edges_is_left_rounded() {
    // 两个方向都没顶满：普通窗口，保留圆角。
    assert!(!fills_work_area(rect(200, 120, 1400, 900), work()));
    assert!(!fills_work_area(rect(0, 4, 1900, 1030), work()));
}

#[test]
fn full_height_band_counts_as_arranged() {
    // 已知取舍：铺满工作区高度、只是宽度窄一些的窗口（左右半屏贴靠就是这个形状）
    // 与「手动拉成通栏」无法从几何上区分，一律按贴靠处理——外框贴着屏幕上下边，
    // 圆角本来也会切掉内容。
    assert!(fills_work_area(rect(0, 0, 1900, 1040), work()));
}

/// 本机实测的无装饰窗口几何：1552×885 的 HWND，客户区 1536×876、偏移 (8,1)。
fn measured_window() -> Applied {
    Applied {
        client_x: 8,
        client_y: 1,
        client_width: 1536,
        client_height: 876,
        outer_width: 1552,
        outer_height: 885,
        radius: 24,
    }
}

#[test]
fn rounded_block_is_anchored_on_the_client_rect() {
    // 圆角必须锚在客户区：锚在 HWND 矩形上时，底部 8 像素非客户区会把下两角的弧线
    // 顶到客户区之外（实测下两角呈直角）。
    let [rounded, _, _] = region_parts(&measured_window());
    let outer = rect(0, 0, 1552, 885);
    assert_eq!(
        (rounded.left, rounded.top, rounded.right, rounded.bottom),
        (8, 1, 8 + 1536 + 1, 1 + 876 + 1),
        "圆角块应覆盖客户区"
    );
    assert!(
        rounded.bottom < outer.bottom && rounded.right < outer.right,
        "圆角块不应越过 HWND 矩形"
    );
}

#[test]
fn straight_resize_bands_stay_on_the_window_edges() {
    let [_, band_h, band_v] = region_parts(&measured_window());
    // 上下直边带：横向铺满整个窗口，只避开圆角所在的上下 24 像素。
    assert_eq!(
        (band_h.left, band_h.top, band_h.right, band_h.bottom),
        (0, 1 + 24, 1552, 1 + 876 - 24)
    );
    // 左右直边带：纵向铺满整个窗口，只避开圆角所在的左右 24 像素。
    assert_eq!(
        (band_v.left, band_v.top, band_v.right, band_v.bottom),
        (8 + 24, 0, 8 + 1536 - 24, 885)
    );
}

#[test]
fn radius_clamps_against_the_client_short_side() {
    // 客户区比 HWND 小一圈时，半径上限按客户区算，避免圆角吃进直边带。
    let mut small = measured_window();
    small.client_width = 40;
    small.client_height = 30;
    assert_eq!(radius_for(2.0, small.client_width, small.client_height), 15);
}
