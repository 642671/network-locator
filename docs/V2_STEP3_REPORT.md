# Network Locator V2 第 3 步报告：设备总览 + 设备管理

> 日期：2026-11-25  
> 版本：`1.4.0`  
> 预览：`http://127.0.0.1:4178/`（`preview_server`，样例数据）  
> 视口：1180×720、1081、900、760、620  
> 范围：spec 4.1（设备总览）、4.3（设备管理）、5（device_id 数据模型）、6/7（UI 与真实扫描约束）

## 结论

**通过（有条件）**。Dashboard 与 Device Inventory 的目标功能均已落地并通过本地交互、自动化测试与构建校验；本轮修复了 Dashboard“立即扫描”误跳到旧 MAC 定位页的问题。真机 NAS 扫描回归仍未在本阶段执行。

| 检查项 | 结果 |
| --- | --- |
| Dashboard 统计/网段/最近设备/全局表 | 通过 |
| Dashboard 搜索/状态筛选/排序/复制/CSV | 通过 |
| Dashboard 立即扫描 | 通过（已修复为原地 inventory 扫描） |
| Inventory 全部/在线/离线/未知/收藏筛选 | 通过 |
| Inventory 搜索/排序/批量选择/批量导出 | 通过 |
| 详情抽屉改名/备注/收藏/IP 历史 | 通过 |
| device_id 主键、扫描不覆盖手动字段 | 通过（单测 + UI 重扫验证） |
| 双语 / 明暗 / 响应式 | 通过 |
| 后端 / 前端测试 | 74 / 74、34 / 34 |
| 双架构构建 | 通过 |

## 1. 实现与修复

- Dashboard 继续使用 `v2/summary` + `v2/devices`：6 张统计卡、接口/网段、最近发现、全局设备表、搜索/状态/排序、复制 IP/MAC、导出 CSV。
- Inventory 使用 `v2/devices` 查询参数：`query`、`status`、`favorite`、`sort`、`direction`；支持全选、批量收藏、导出所选、行点击与“详情”按钮打开抽屉。
- 抽屉保存仅提交 `display_name`、`note`、`favorite`；`store.update_device` 只写这三类字段，`ingest_observations` 不触碰，因此扫描不会覆盖手动信息。
- **修复**：Dashboard 的“立即扫描”原来跳到旧“网络扫描”页并聚焦 MAC 后缀。现在改为调用 `NetworkLocatorPages.scanInventory`，原地执行设备清单扫描并刷新 Dashboard（`apps/tos7/frontend/v2-pages.js:670`、`apps/tos7/frontend/v2-shell.js:430`）。
- 新增两条后端回归测试：inventory 搜索/收藏/排序、状态筛选/统计/recent（`apps/tos7/backend/tests/test_v2_features.py:117`、`:155`）。

## 2. 功能自检结果

Dashboard：

- 搜索 `Apple` → `客厅 Apple TV`、`访客 iPad`（2 台）；状态 `offline` → `访客 iPad`（1 台）。
- 点击“立即扫描” → 停留 `#dashboard`，提示“扫描完成：发现 9 台，新增 0 台，IP 变化 0 台”，统计卡刷新。
- 复制首行 IP → 写入 `192.0.2.25`（通过 bridge 捕获验证）。
- 导出 CSV → `exportDevices` 收到 9 台设备，前缀 `network-locator-dashboard`。

Device Inventory：

- 状态筛选：在线 7、离线 1、未知 1、收藏 2；全部恢复 9 台。
- 搜索：`Apple` → 2 台；`192.0.2.180` → 1 台；`Raspberry` → 1 台。
- 按名称升序排序生效；全选后批量栏显示“已选 9 台设备”；导出所选收到 9 台，前缀 `network-locator-selected`。
- 抽屉保存 `测试-TV` / `3F-机房` / 收藏后，表格立即更新；随后执行设备扫描，名称仍为 `测试-TV`，未被扫描覆盖。
- `dev-sample-4` 详情抽屉显示 2 条 IP 历史（当前 `192.0.2.88`、历史 `192.0.2.80`）和 3 条设备事件；表格、抽屉均按 `device_id` 打开。

生产路径没有使用静态假数据：`preview_server.py` 仅用于本地 UI 预览，所有响应带 `sample: true`；实际扫描仍走 `discover_networks` + `probe_network_devices` + SQLite store。

## 3. 测试与构建

```bash
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'   # 74 / 74
node --test apps/tos7/tests/*.test.js                                  # 34 / 34
node --check frontend/{app,csv,i18n,v2-data,v2-shell,v2-pages}.js
python3 -m compileall -q backend
python3 build.py --platform x86_64
python3 build.py --platform aarch64
```

产物：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`，SHA256 `af8e44948ff2322c956479a70df4d75b78502b15508796ab59ebfbac2ff59176`。
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`，SHA256 `8154d457f3a87cb3a053924319d046a4b588a69dfcd14b7e8d0ecb31f15a48ac`。

## 4. 截图

目录 `docs/screenshots/step3/`，共 28 张：

- Dashboard × 中/英 × 浅/深（4）：`v3-dashboard-<lang>-<theme>.png`
- Dashboard 全局设备表（4）：`v3-dashboard-table-<lang>-<theme>.png`
- Inventory × 中/英 × 浅/深（4）：`v3-inventory-<lang>-<theme>.png`
- 抽屉概览（4）：`v3-drawer-<lang>-<theme>.png`
- 抽屉 IP 历史/事件（4）：`v3-drawer-history-<lang>-<theme>.png`
- 响应式（8）：`v3-responsive-dashboard-<width>-zh-light.png`、`v3-responsive-inventory-<width>-en-dark.png`（1081/900/760/620）

示例：`docs/screenshots/step3/v3-dashboard-zh-light.png`、`docs/screenshots/step3/v3-dashboard-table-en-dark.png`、`docs/screenshots/step3/v3-inventory-zh-light.png`、`docs/screenshots/step3/v3-drawer-history-zh-light.png`。

## 5. 响应式与控制台

- 1180/1081/900/760/620 下 Dashboard 与 Inventory 页面级横向溢出均为 0；导航 210px → 72px（≤1050）。
- Inventory 在 1081 英文深色下表格内部横向滚动 4px，属表格内部兜底，页面不溢出。
- 760/620 下 Dashboard 统计卡改为单列/双列，Inventory 按优先级隐藏厂商、网段、最近发现、状态等列；行点击仍可打开抽屉。
- Orca 控制台 0 错误；最近 300 条网络请求全部 HTTP 200。

## 6. 未完成项 / 已知边界

1. **真机回归未执行**：本轮使用 preview 样例数据验证 UI 与交互，未在 TOS 7.1 NAS 上执行真实扫描、暂停/恢复和大量设备压测。
2. Dashboard 全局设备表最多加载 300 条（按最近发现）；Inventory 与 CSV 使用 5000 条上限。尚未做分页/虚拟滚动。
3. 英文模式下设备名、备注、历史事件保持中文；“1 devices” 类计数语法仍可能存在。
4. 1081px 英文深色 Inventory 有 4px 表格内部横向滚动兜底。
5. AArch64 上架 App ID 绑定仍待所有者决策。
6. 本阶段未 commit 到远端、未打 Release、未提交审核。

## 7. 打包契约

未改动：App ID / package `network-locator`、unit `networklocator-system`、socket `/var/api/network-locator.sock`、用户 `network-locator`、包内路径、默认窗口 1180×720、`build.py` 规则。现有 MAC 定位扫描与旧“网络扫描”页功能保留。

## 附：1.3.8 平台状态（只读核实）

平台 API（个人令牌配置，未打印令牌）显示 1.3.8 已提交并处于审核中（`status=0`）：

| 架构 | App ID | 版本 | Version ID | 提交时间 |
| --- | --- | --- | --- | --- |
| x86_64 | `f5d5fede-c204-45fa-8132-fb007cf55d23` | 1.3.8 | `b1ed1dfb-be80-4517-9f72-6021c9acd5d4` | 2026-11-25 11:13:55 +08:00 |
| aarch64 | `dc579d95-1f9e-424e-8595-20f109c0336d` | 1.3.8 | `9a55f662-b54a-4877-86a3-b4e97c7781c8` | 2026-11-25 11:14:05 +08:00 |

