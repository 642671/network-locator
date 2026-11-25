# Network Locator V2 第 2 步自检报告

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`  
> 版本：`1.4.0`  
> 预览：`http://127.0.0.1:4178/`（`preview_server`，样例数据）  
> 浏览器：Orca Chromium；视口 1081×925、1180×720、900、760、620

## 结论

**通过（有条件）**：构建、双语、明暗主题与新页面响应式均通过；自检中发现并修复了旧“网络扫描”页在 ≤820px 的裁切/重叠。剩余项集中在真机回归和已知边界，不阻塞第 2 步收尾。

| 自检项 | 结果 |
| --- | --- |
| 构建（x86_64 / aarch64） | 通过 |
| 后端测试 / 前端测试 | 通过（72 / 72、34 / 34） |
| 中文 / 英文双语 | 通过 |
| 浅色 / 深色主题 | 通过 |
| 响应式 | 通过（760/620 旧扫描页已修复） |
| 打包契约 | 未改动，校验通过 |

## 1. 构建与测试

- `python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'`：**72 / 72 通过**。
- `node --test apps/tos7/tests/*.test.js`：**34 / 34 通过**。
- `node --check`（`app.js`、`csv.js`、`i18n.js`、`v2-data.js`、`v2-shell.js`、`v2-pages.js` 及测试）与 `python3 -m compileall -q backend`：通过。
- `python3 build.py --platform x86_64` / `aarch64`：`Verification: OK`。
- 产物：
  - `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`，SHA256 `ca61b427c4d5c17ad87876e5d36bd8d9188e814e4ac653d428d6cd32b1f08eb4`。
  - `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`，SHA256 `7a98d59f0801f5b824d275b3bf1b4f7fe627ffb2d94b90adf4df49abc3a11cc0`。
- x86_64 连续构建两次 SHA 一致（确定性构建）；包内 `webui.bz2` 已包含 `i18n.js`、`v2-data.js`、`v2-shell.*`、`v2-pages.*`、`v2-tokens.css`。

## 2. 双语与明暗截图

共 46 张，目录 `docs/screenshots/step2/`。

- 7 个页面 × 中/英 × 浅/深（28 张）：`v2-<page>-<lang>-<theme>.png`
  - 页面：`dashboard`、`discovery`、`inventory`、`mac-lookup`、`analysis`、`history`、`settings`
  - 语言：`zh`、`en`；主题：`light`、`dark`
  - 示例：`docs/screenshots/step2/v2-dashboard-zh-light.png`、`docs/screenshots/step2/v2-dashboard-en-dark.png`
- 设备详情抽屉 × 中/英 × 浅/深（4 张）：`v2-drawer-<lang>-<theme>.png`
- 响应式（12 张）：`v2-responsive-inventory-<width>-<lang>-<theme>.png`（1081/900/760/620）、`v2-responsive-discovery-<width>-zh-light.png`（1180/900/760/620）、`v2-tos1180-inventory-1180-<lang>-<theme>.png`。
- 英文模式中文残留扫描：仅设备名（如“本机 NAS”）和语言按钮“中文”，属数据不翻译的预期行为。

## 3. 响应式结果

- 1180×720、1081×925、900、760、620 下，7 个页面 `documentElement.scrollWidth - clientWidth = 0`，页面级无横向溢出。
- 导航宽度：1180/1081 为 210px；≤1050 折叠为 72px 图标栏。
- 760 宽时 `analysis` 表格内部横向滚动 12px、`history` 英文深色表格内部滚动 79px，属表格内部兜底滚动，页面本身不溢出。
- 本次修复：旧“网络扫描”页在 ≤820px 时由壳层改为可纵向滚动、网段区自然增高。修复后 760/620 下网段列表、警告、自定义范围完整可见，无控件重叠；目标窗口 1180×720 的两栏布局不变。
- 窄屏设备表按列隐藏，行点击仍可打开详情抽屉。

## 4. 交互与运行状态

- 实际点击主题按钮：`light ↔ dark` 正常，localStorage 同步。
- 实际点击语言按钮：`zh ↔ en` 正常重载，`<html lang>`、导航、页面标题同步切换。
- 浏览器控制台：0 条错误；200 条网络请求均为 HTTP 200。

## 5. 未完成项 / 已知边界

1. **真机回归未执行**：本次只验证本地 preview（`sample: true`），未在 TOS 7.1 NAS 上安装 Deb、执行真实扫描、暂停/恢复与系统标题栏高度回归。
2. **760px 分析/历史表格存在内部横向滚动**（12px / 79px）；≤620px 的表格式页面仍以内部滚动兜底。
3. **英文数据不翻译**：设备名、备注、历史记录保持中文；英文计数可能出现 “1 devices” 一类语法问题。
4. **AArch64 上架身份未定**：ARM 包已构建，但平台 App ID 架构绑定仍需所有者决策。
5. 旧版 localStorage 不自动迁移 SQLite；真实网络下的离线判定、OUI 命中率和大量设备性能未在本轮复测。
6. 本次未 commit / tag / push，也未改动审核设备或工单。

## 6. 打包契约确认

以下均未改动：App ID / package `network-locator`、systemd unit `networklocator-system`、socket `/var/api/network-locator.sock`、运行用户 `network-locator`、包内路径 `/usr/local/network-locator/`、默认窗口 1180×720、`build.py` 打包规则。

本次代码改动仅为 `apps/tos7/frontend/v2-shell.css` 末尾的 ≤820px discovery 响应式媒体块；其余为截图与文档，未删除任何现有功能。
