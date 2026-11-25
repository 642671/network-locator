# Network Locator V2 第 4 步报告：详情抽屉与数据模型

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`（第 3 步提交 `3c2eae7`；第 4 步提交在本分支）  
> 版本：`1.4.0`  
> 预览：`http://127.0.0.1:4178/`（样例数据）、`http://127.0.0.1:4179/`（`--bulk 10000`）  
> 截图：`docs/screenshots/step4/`（40 张，1180×720 为主）

## 结论

**通过（有条件）**。详情抽屉、SQLite schema v2 迁移、`device_id` 主键去重、IP 历史、手动字段保护、英文完整性与大量设备分页均已落地并通过本地验证；真机 NAS 回归仍需在发布前执行。

| 检查项 | 结果 |
| --- | --- |
| 抽屉概览/地址历史/IP 历史/事件/操作 | 通过 |
| 在线/离线/未知状态与时间线 | 通过 |
| 空/加载/错误/重试状态 | 通过 |
| Device/Address/Event/ScanResult/Interface/Segment 模型 | 通过 |
| v1 → v2 原位迁移并保留旧数据 | 通过（单测） |
| 重复扫描去重、IP 变化不新增设备 | 通过（单测） |
| 手动名称/备注/收藏不被扫描覆盖 | 通过（单测） |
| 英文模式全覆盖（7 页 + 抽屉 + 预览数据） | 通过（浏览器扫描 0 中文/全角字符） |
| 大量设备分页与完整 CSV | 通过（10,009 台） |
| 构建 x86_64 / aarch64 | 通过（SHA 见下） |
| 真机 TOS 安装/扫描/卸载回归 | **未执行（发布前阻塞项）** |

## 1. 数据模型与迁移

- `SCHEMA_VERSION` 升到 **2**；初始化幂等，旧库原位升级，不删表、不重建。
- v1 → v2 迁移：`device_events` 增加 `detail_code` / `detail_args`；新增
  `scan_results`、`network_interfaces`、`network_segments`；保留原有设备、
  地址、事件和扫描任务。数据库版本高于代码时拒绝启动。
- `devices.device_id` 仍是唯一主键；MAC 优先匹配，IP + 接口 7 天兜底。
  IP 变化只更新 `device_addresses` 的当前标记并新增历史，不新增设备。
- 批量观测先按 `(mac, ip, interface, network_id, state)` 去重；`scan_results`
  再按 `(task_id, mac, ip, interface)` 唯一约束落库。
- `store.update_device` 只写 `display_name` / `note` / `favorite`；扫描和重扫
  不触碰这三个字段。
- 统计、网段计数、厂商计数改为 SQL 聚合；设备列表支持 `limit` / `offset`。

## 2. 详情抽屉

- 概览：名称、状态、IP/MAC、厂商、接口、网段、首次/最近发现、检测时间、
  发现次数、随机 MAC、`device_id`、状态原因。
- 地址历史：IP/MAC/接口/最近发现/当前或历史。
- IP 历史：首次发现、最近发现、当前或历史；本次示例设备 `dev-sample-4`
  显示当前 `192.0.2.88` 和历史 `192.0.2.80`。
- 设备事件：首次发现、IP 变化、MAC 变化、上线、离线、改名、备注、收藏；
  事件详情按 `detail_code` + 参数渲染，不依赖存储的中文文本。
- 操作：改名、备注、收藏、保存、复制 IP、复制 MAC；保存后列表即时刷新，
  重扫不覆盖手动字段。
- 状态：加载中清空旧设备内容并禁用操作；错误显示原因与“重试”；IP 变化
  在时间线显示 `旧 IP → 新 IP`。

## 3. 第 3 步验收项收尾

1. **英文完整性**：7 个页面（Dashboard/Discovery/Inventory/MAC Lookup/
   Analysis/History/Settings）与抽屉均扫描为 **0 个中文汉字、0 个中文/全角
   标点**。预览样例设备名、备注、事件、状态原因、扫描范围分隔符均按英文
   输出；用户输入文本保持原样。
2. **大量设备**：Dashboard 与 Inventory 每页 50 条，提供上一页/下一页和
   `第 N 页 · 起–止 / 总数`。10,009 台时首次加载约 **0.43s**，单页 1000 条
   接口约 **111ms**；全量导出循环取回 **10,009/10,009** 条，CSV 为表头 +
   10,009 行，耗时约 **0.78s**。
3. **真机回归**：本轮仍未执行；已列入发布前阻塞项，计划第 5 步末或测试
   NAS 空闲时完成安装、启动、TOS 入口、7 页、真实网段扫描与卸载。

## 4. 测试与构建

```bash
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'   # 80 / 80
node --test apps/tos7/tests/*.test.js                                  # 40 / 40
node --check frontend/{app,csv,i18n,v2-data,v2-shell,v2-pages}.js      # 通过
python3 -m compileall -q backend tools                                 # 通过
python3 build.py --platform x86_64                                     # Verification: OK
python3 build.py --platform aarch64                                    # Verification: OK
```

产物：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`
  SHA256 `fe9c8d18208f1460a01d5bd59e41ecf319243014c89c37ba4c560e335a6bf940`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`
  SHA256 `157434d34d73f37eeb3faa866df7221e16236f85313c02b1aef18133a25e7427`
- x86_64 连续构建两次 SHA 一致（确定性构建）。

最终复验（英文、新开标签页）：7 个页面均为 0 个中文/全角字符；10,009 台筛选结果分页显示 `1 device` / `Page 1 · 1–1 / 1`。

## 5. 截图

目录 `docs/screenshots/step4/`，共 40 张。代表性路径：

- Dashboard：`v4-dashboard-{zh,en}-{light,dark}.png`
- Inventory：`v4-inventory-{zh,en}-{light,dark}.png`
- 抽屉概览：`v4-drawer-{zh,en}-{light,dark}.png`
- 地址/IP/事件：`v4-drawer-history-{zh,en}-{light,dark}.png`
- 离线/未知：`v4-drawer-offline-{zh-light,en-dark}.png`、`v4-drawer-unknown-{zh-light,en-dark}.png`
- 空态：`v4-inventory-empty-{zh-light,en-dark}.png`
- 错误：`v4-drawer-error-{zh-light,en-dark}.png`
- 加载：`v4-drawer-loading-{zh-light,en-dark}.png`
- 大量设备：`v4-bulk-{dashboard,inventory}{,-pager}-{zh-light,en-dark}.png`
- 响应式：`v4-responsive-inventory-{1081,760,620}-{en-dark}`、`v4-responsive-inventory-{900,760}-zh-light.png`、`v4-responsive-drawer-620-en-dark.png`

示例：`docs/screenshots/step4/v4-inventory-en-light.png`、
`docs/screenshots/step4/v4-drawer-history-en-dark.png`、
`docs/screenshots/step4/v4-bulk-inventory-pager-zh-light.png`。

## 6. 响应式与布局

- 1180×720：Dashboard/Inventory 页面溢出 0、表格内部滚动 0；设备表新增
  列宽压缩后，英文 Inventory 的“Open”列完整可见。
- 1081×925：页面溢出 0；Dashboard/Inventory 表格内部滚动约 25px/8px。
- 760×720：页面溢出 0；表格内部滚动约 14px/21px。
- 620×720：页面与表格溢出均为 0；抽屉宽 620，抽屉 body 溢出 0。
- 已知：1180 英文下个别“长名称 + 随机 MAC 徽标”的设备名会省略号收束，
  悬停标题和详情抽屉显示全名。

## 7. 未完成项 / 已知边界

1. **真机回归未执行**：需在 TOS 7.1 NAS 上安装 Deb、确认服务 active、
   从桌面打开、走完 7 页、扫描真实网段、验证暂停/恢复与卸载。计划第 5 步
   末或真机空闲时完成。
2. 1081/760 宽仍有表格内部横向滚动兜底；目标 1180 与 620 宽为 0。
3. 10,009 台为本轮上限验证，更高数量级或低内存真机仍需压测。
4. AArch64 上架 App ID 绑定仍待所有者决策（见交接回复）。
5. 本阶段未打 Release、未提交审核、未改动审核设备或工单。

## 8. 打包契约

未改动：App ID / package `network-locator`、systemd unit
`networklocator-system`、socket `/var/api/network-locator.sock`、运行用户
`network-locator`、包内路径、默认窗口 1180×720、`build.py` 打包规则。
现有扫描、MAC 定位、旧“网络扫描”页与收藏功能均保留。

## 附：1.3.8 平台状态（只读核实）

1.3.8 已用个人令牌提交，当前 `status=0`（审核中）：

| 架构 | App ID | 版本 | Version ID | 提交时间 |
| --- | --- | --- | --- | --- |
| x86_64 | `f5d5fede-c204-45fa-8132-fb007cf55d23` | 1.3.8 | `b1ed1dfb-be80-4517-9f72-6021c9acd5d4` | 2026-11-25 11:13:55 +08:00 |
| aarch64 | `dc579d95-1f9e-424e-8595-20f109c0336d` | 1.3.8 | `9a55f662-b54a-4877-86a3-b4e97c7781c8` | 2026-11-25 11:14:05 +08:00 |
