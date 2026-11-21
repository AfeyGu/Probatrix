# CalcBook UI 设计规范

适用范围：CalcBook 桌面端操作界面（参数表单、批量表格、预览容器、工具栏、弹层）。
**计算书文档区（`.paper` / `.cb-doc`）不适用本规范**——它是黑白衬线纸面，见文末独立条款。

可视真源：`ui-concepts/v2-pro.html`。令牌值改动时，该文件与本档同步修改，两处为准，不引入第三处数值。

## 1. 设计基调

Windows 11 通透（Mica/Acrylic 毛玻璃）+ 变曲率圆角（squircle）+ 全按钮无突出色。
气质定位：正式的结构计算软件，克制、透亮、秩序感强；不做消费级 App 的炫技。

## 2. 令牌总表

```css
:root{
  /* 半径三档——全站只有这三档，禁止第四档 */
  --r-card:24px;      /* 卡片/浮层/弹窗/toast/下拉弹层 */
  --r-ctl:8px;        /* 输入框、模板选择行、开关行 */
  --r-pill:999px;     /* 所有按钮、分段控件、菜单项、chip、键帽 */

  /* 颜色：文字三级 + 线两级 + 画布 + 功能色 */
  --ink:#12161d;  --ink-2:#4e5a6b;  --ink-3:#7b8798;
  --line:rgba(15,34,64,.10);  --line-2:rgba(15,34,64,.16);
  --canvas:#e8edf5;   /* 画布底，上面叠三团彩色 radial 渐变 */
  --accent:#1a6fd4;   --accent-2:#0f5bb5;
  --accent-soft:rgba(26,111,212,.09);
  --ok:#137a52;  --warn:#9a6700;  --bad:#b42318;

  /* L1 Mica（主卡）与 L2 Acrylic（浮层）材质 */
  --l1-bg:rgba(255,255,255,.56);  --l1-blur:40px;  --l1-sat:1.9;
  --l1-hi:rgba(255,255,255,.95);  --l1-lo:rgba(15,34,64,.10);
  --l2-bg:rgba(255,255,255,.74);  --l2-blur:52px;  --l2-sat:2.1;
  --l2-hi:rgba(255,255,255,.55);  --l2-lo:rgba(30,58,92,.16);

  /* 阴影：蓝灰调、近锐远散，禁止纯黑 */
  --sh-near:0 2px 8px rgba(30,58,92,.18);
  --sh-far:0 12px 32px rgba(30,58,92,.26);

  /* 字体三级 */
  --f-display:"Segoe UI Variable Display","Segoe UI Variable Text","Segoe UI",
               system-ui,"Microsoft YaHei UI","PingFang SC",sans-serif;
  --f-text:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei UI",
           "PingFang SC",system-ui,sans-serif;
  --f-num:"Cascadia Mono","Segoe UI Variable Text",ui-monospace,Consolas,monospace;
}
```

画布背景（body）：三团 radial 渐变（蓝 `rgba(110,155,232,.52)` 左上、紫 `rgba(190,164,238,.44)` 右上、青 `rgba(126,196,222,.38)` 底部）+ `--canvas` 底色。彩色透进玻璃卡才成立，不要调到几乎看不见。

## 3. 变曲率规则（corner-shape）

- 每个可见圆角都是 `border-radius` + `corner-shape:squircle` **成对出现**（squircle 在 Chromium 139+/WebView2 原生支持；旧浏览器自动降级普通圆角，无需 `@supports`）。
- 超椭圆参数：全站用 `squircle`；`superellipse(5)` 仅页尾演示条对照，不用于产品。
- 例外：开关轨道/勾选框等几何胶囊用 `999px`；计算书纸面显式 `corner-shape:round !important; border-radius:2px !important` 退出。

## 4. 材质三级

| 层 | 用途 | 参数 |
|---|---|---|
| L0 | 画布 | 三团彩色渐变 + `--canvas` |
| L1 Mica | 主卡（参数/预览/批量） | `--l1-bg` + `blur(40) saturate(1.9)`，边框 `1px rgba(255,255,255,.9)`，顶部 110px 受光渐变 `linear-gradient(180deg,rgba(255,255,255,.5),transparent)`，上缘高光 `inset 0 1px 0 var(--l1-hi)`、下缘暗线 `inset 0 -1px 0 var(--l1-lo)` |
| L2 Acrylic | toast/下拉/弹窗 | `--l2-bg` + `blur(52) saturate(2.1)`，玻璃内描边（上 `.55` 白、下蓝灰暗收）+ `--sh-near --sh-far` 双层投影 |
| 输入件 | 输入框/下拉行 | 白 `.86`、边 `rgba(15,34,64,.12)`；聚焦白底 + accent 边 + `3px var(--accent-soft)` 光环 |

光从上来：任何新组件上边缘亮、下边缘暗；hover 提亮不位移。

## 5. 组件规格

| 组件 | 规格 |
|---|---|
| 按钮（全站唯一样式） | 高 32px、内边距 0 13px、胶囊半径、白玻璃底（`rgba(255,255,255,.9)`）、无边框分色；hover 白底 + accent 描边 |
| 输入控件 | 高 32px、`--r-ctl`、单位后缀右贴 |
| 分段控件（单页参数/批量表格） | 胶囊容器（深 `rgba(15,34,64,.055)`、内边距 3px）+ 胶囊选中项（白底+轻投影） |
| 开关 | 轨道 38×20 胶囊、滑块 14、回弹曲线 `cubic-bezier(.34,1.56,.64,1)` |
| chip/状态 | 胶囊、淡色底（如 `rgba(19,122,82,.10)` + `--ok`），不做边框 |
| 菜单项 | 高 30px、胶囊 |
| toast | 318px 宽、右下角 22px、L2 材质 |
| 批量表格 | 13px 紧凑密度、行内控件小号、列头单行 |

## 6. 硬规则（违反即返工）

1. **半径只许三档**：新元素必须归入 card/ctl/pill 之一，禁止自定半径值。
2. **按钮无突出色**：不做 primary 实心/彩色按钮，主次靠位置与字重表达；`--accent` 只用于聚焦环、勾选、进度、链接等功能态。
3. **阴影蓝灰调**（`rgba(30,58,92,…)`），双层（近锐+远散），禁止纯黑。
4. **动效克制**：150–200ms ease-out，只动 background/border-color/box-shadow/opacity；禁止位移缩放类大动画；`prefers-reduced-motion` 下全部关闭。
5. **数值一律等宽**：`--f-num` + `font-variant-numeric:tabular-nums`。
6. **计算书纸面独立体系**：黑白、衬线（Songti SC/SimSun）、2px 直角、纸感排版由 `docstyle.py` 唯一定义；玻璃材质、彩色、大圆角、动效一律不得进入纸面。
7. 新增界面文案密度对齐现状：操作区 12.5–13.5px，批量表 13px。

## 7. 验收自查清单

- [ ] 新元素半径归入三档，`corner-shape` 与 `border-radius` 成对
- [ ] 无新增按钮颜色/实心变体
- [ ] 材质层级正确（主卡 L1 / 浮层 L2 / 输入件轻材质），参数取令牌而非手写
- [ ] 阴影蓝灰调双层；高光在上、暗线在下
- [ ] 数值等宽；批量表密度未放松
- [ ] 计算书区未被玻璃化（黑白衬线 2px 直角）
- [ ] 动效时长/属性符合硬规则 4

## 8. 实装映射

- Vue 端：以上令牌并入 `App.vue` 的 `:root` `--cb-*` 体系；Element Plus 按钮统一走覆盖（`--el-border-radius` 等映射到三档令牌）。
- `corner-shape` 直接迁入生产 CSS，无需兼容代码；WebView2 与开发浏览器（Edge/Chrome ≥139）均原生支持。
- 窗口级 Mica/Acrylic（真系统材质）在 Tauri 壳就绪后用 `window-vibrancy` 实现，届时 L1 玻璃可减薄一层模拟感。
